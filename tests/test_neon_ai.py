import base64
import copy
import io
import json
from pathlib import Path

import httpx
import pytest

from workspace import Store, WorkspaceError, Forbidden, Conflict, prepare_import, uid
from cloud_storage import NeonStorage, neon_host, validate_object
from filetools import parse_upload
from migration import file_fingerprint
from ai_service import AICreditsRequired, AIConfig, NeonAI, build_context
from ai_store import AIStore, normalize_actions

PASSWORD = "Only-local-test-123!"
ENDPOINT = "https://br-test.storage.c-2.eu-central-1.aws.neon.tech"


class FakeS3:
    def __init__(self):
        self.objects, self.gets, self.fail_body = {}, [], None

    def put_object(self, Bucket, Key, Body, **kwargs):
        if Body == self.fail_body:
            raise RuntimeError("do not expose secret from transport")
        self.objects[(Bucket, Key)] = Body

    def get_object(self, Bucket, Key):
        self.gets.append((Bucket, Key))
        return {"Body": io.BytesIO(self.objects[(Bucket, Key)])}

    def head_bucket(self, **kwargs):
        return {}


@pytest.fixture
def setup(tmp_path):
    store = Store("sqlite:///" + str(tmp_path / "neon.db"))
    store.bootstrap("owner", PASSWORD, "مدير التجربة")
    token = store.login("owner", PASSWORD)
    return store, token, AIStore(store)


def attach_storage(store):
    client = FakeS3()
    store.storage = NeonStorage(ENDPOINT, "gday-private", "test-access", "test-secret", "eu-central-1", client)
    return client


def add_task(store, token, ident="t1"):
    store.put(token, "tasks", {"id": ident, "title": "مراجعة الملفات", "projectId": "p_general", "status": "todo",
        "priority": "medium", "assigneeId": store.actor(token)["member_id"], "dueDate": "", "notes": "", "estimatedMinutes": 30})


def begin(repo, store, token, thread, request=None, daily=40):
    state, revision = store.read(token)
    data, refs, _ = build_context(store, token, state, "p_general", [], "اقترح مهمة")
    run = request or uid("req_")
    repo.begin(token, thread, run, "اقترح مهمة", "configured-model", data, refs, revision, daily)
    return run


def test_separate_storage_preserves_binary_dedup_and_portable_backup(setup):
    store, owner, _ = setup
    client = attach_storage(store)
    record = parse_upload("work.txt", "النص الأصلي".encode(), "p_general")
    fingerprint = file_fingerprint(record)
    store.add_files(owner, [record])
    saved = store.read(owner)[0]["files"][0]
    assert "blob" not in saved and saved["object"]["size"] == len("النص الأصلي".encode())
    assert file_fingerprint(saved) == fingerprint
    assert store.file_bytes(owner, saved["id"]) == "النص الأصلي".encode()
    assert prepare_import(store.backup_bytes(store.read(owner)[0]))["data"]["files"][0]["object"]
    portable = store.export_with_originals(owner)
    incoming = prepare_import(portable)["data"]["files"][0]
    assert "object" not in incoming and base64.b64decode(incoming["blob"]) == "النص الأصلي".encode()
    assert not any("secret" in str(x) for x in saved["object"].values())
    before = len(client.gets)
    with pytest.raises(Forbidden): store.file_bytes("invalid", saved["id"])
    assert len(client.gets) == before


def test_migration_rolls_back_if_any_upload_fails_and_is_repeatable(setup):
    store, owner, _ = setup
    store.add_files(owner, [parse_upload("a.txt", b"first", "p_general"), parse_upload("b.txt", b"second", "p_general")])
    client = attach_storage(store)
    client.fail_body = b"second"
    before, revision = store.read(owner)
    with pytest.raises(WorkspaceError): store.migrate_originals(owner, revision)
    assert store.read(owner) == (before, revision)
    client.fail_body = None
    assert store.migrate_originals(owner, revision) == 2
    assert store.migrate_originals(owner, store.read(owner)[1]) == 0
    assert {f["id"] for f in before["files"]} == {f["id"] for f in store.read(owner)[0]["files"]}
    assert len(store.list_snapshots(owner)) == 1


@pytest.mark.parametrize("url", ["http://bad.neon.tech", "https://evil.test", "https://x.neon.tech/v1", "https://user:secret@x.neon.tech", "https://x.neon.tech?token=a"])
def test_endpoint_rejects_credentials_paths_or_non_neon_hosts(url):
    with pytest.raises(WorkspaceError): neon_host(url)


def test_storage_ref_cannot_redirect_or_hide_corrupt_bytes(setup):
    store, owner, _ = setup
    client = attach_storage(store)
    store.add_files(owner, [parse_upload("a.txt", b"correct", "p_general")])
    record = store.read(owner)[0]["files"][0]
    client.objects[("gday-private", record["object"]["key"])] = b"corrupt"
    with pytest.raises(WorkspaceError, match="سلامة"): store.file_bytes(owner, record["id"])
    foreign = record["object"] | {"bucket": "other-private"}
    before = len(client.gets)
    with pytest.raises(WorkspaceError, match="مختلف"): store.storage.download(foreign)
    assert len(client.gets) == before
    with pytest.raises(WorkspaceError): validate_object(record["object"] | {"key": "../other"})


def test_ai_conversations_are_private_persistent_and_usage_survives_deletion(setup):
    store, owner, repo = setup
    store.create_user(owner, "other", "عضو", PASSWORD, "member")
    other = store.login("other", PASSWORD)
    thread = repo.create_thread(owner, "p_general")
    run = begin(repo, store, owner, thread, daily=1)
    repo.finish(owner, run, "رد محفوظ", [], {})
    assert not repo.list_threads(other, "p_general")
    for fn in [lambda: repo.history(other, thread), lambda: repo.proposal(other, run), lambda: repo.delete_thread(other, thread), lambda: repo.export_thread(other, thread)]:
        with pytest.raises(Forbidden): fn()
    reopened = AIStore(Store(str(store.engine.url)))
    assert reopened.history(owner, thread)[-1]["content"] == "رد محفوظ"
    repo.delete_thread(owner, thread)
    assert repo.daily_count(owner) == 1
    replacement = repo.create_thread(owner, "p_general")
    with pytest.raises(WorkspaceError, match="اليومي"): begin(repo, store, owner, replacement, daily=1)


def test_ai_request_is_reserved_once_and_blocks_parallel_submission(setup):
    store, owner, repo = setup
    thread = repo.create_thread(owner, "p_general")
    run = begin(repo, store, owner, thread)
    with pytest.raises(Conflict): begin(repo, store, owner, thread, request=run)
    with pytest.raises(Conflict): begin(repo, store, owner, thread)
    assert repo.daily_count(owner) == 1
    repo.fail(owner, run, "فشل آمن")
    assert repo.history(owner, thread)[-1]["meta"]["error"]
    assert begin(repo, store, owner, thread) != run


def test_ai_proposal_requires_review_and_applies_once_with_attribution(setup):
    store, owner, repo = setup
    add_task(store, owner)
    thread = repo.create_thread(owner, "p_general")
    run = begin(repo, store, owner, thread)
    repo.finish(owner, run, "اقتراح للمراجعة", [
        {"kind": "task_update", "target_id": "t1", "values": {"status": "done"}},
        {"kind": "task_create", "values": {"title": "متابعة الفريق"}},
        {"kind": "document_create", "values": {"title": "ملخص", "text": "نص للمراجعة"}},
        {"kind": "handover_update", "values": {"next_step": "المتابعة صباحًا"}},
    ], {"total_tokens": 100})
    assert store.read(owner)[0]["tasks"][0]["status"] == "todo"
    assert repo.decide(owner, run, apply=True)
    state = store.read(owner)[0]
    assert len(state["tasks"]) == 2 and state["tasks"][0]["completedAt"]
    assert state["tasks"][0]["aiRunId"] == run
    assert state["files"][0]["text"] == "نص للمراجعة"
    assert state["handover"]["next_step"] == "المتابعة صباحًا"
    assert repo.decide(owner, run, apply=True) is False
    assert len(store.read(owner)[0]["tasks"]) == 2
    assert len(store.list_snapshots(owner)) == 1


def test_ai_proposal_conflict_rolls_back_entire_batch(setup):
    store, owner, repo = setup
    add_task(store, owner)
    thread = repo.create_thread(owner, "p_general")
    run = begin(repo, store, owner, thread)
    repo.finish(owner, run, "اقتراح", [
        {"kind": "task_create", "values": {"title": "لا تضاف جزئيًا"}},
        {"kind": "task_update", "target_id": "t1", "values": {"status": "done"}},
    ], {})
    task = store.read(owner)[0]["tasks"][0]
    store.put(owner, "tasks", task | {"title": "تعديل زميل"}, task["version"])
    before = store.read(owner)
    with pytest.raises(Conflict): repo.decide(owner, run, apply=True)
    assert store.read(owner) == before
    assert repo.proposal(owner, run)[1] == "pending"
    assert repo.decide(owner, run, apply=False)


@pytest.mark.parametrize("action", [
    {"kind": "delete", "values": {"id": "t1"}},
    {"kind": "task_create", "values": {"title": "x", "role": "admin"}},
    {"kind": "task_update", "target_id": "not-in-context", "values": {"title": "x"}},
    {"kind": "task_create", "values": {"title": "x", "status": {"sql": "DROP TABLE"}}},
    {"kind": "handover_update", "values": {"next_step": "x"}},
])
def test_model_cannot_escalate_or_touch_unseen_records(setup, action):
    store, owner, _ = setup
    state, _ = store.read(owner)
    with pytest.raises(WorkspaceError): normalize_actions([action], state, "p_general", {"tasks": {}, "handover": None})


def test_viewer_cannot_apply_even_if_role_changed_after_proposal(setup):
    store, owner, repo = setup
    store.create_user(owner, "agent", "المساعد", PASSWORD, "agent", agent_edit=True)
    agent = store.login("agent", PASSWORD)
    thread = repo.create_thread(agent, "p_general")
    run = begin(repo, store, agent, thread)
    repo.finish(agent, run, "اقتراح", [{"kind": "task_create", "values": {"title": "تجربة"}}], {})
    user = next(u for u in store.list_users(owner) if u["username"] == "agent")
    store.update_user(owner, user["id"], "agent", True, False)
    with pytest.raises(Forbidden): repo.decide(agent, run, apply=True)
    reader = store.login("agent", PASSWORD)
    with pytest.raises(Forbidden): repo.decide(reader, run, apply=True)
    assert not store.read(owner)[0]["tasks"]


def test_gateway_request_shapes_are_bounded_and_errors_redacted():
    captured = []
    def handle(request):
        captured.append(request)
        return httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {
            "content": [{"type": "text", "text": "رد [S1]"}], "tool_calls": [{"function": {
                "name": "propose_workspace_changes", "arguments": json.dumps({"actions": [{"kind": "task_create", "values": {"title": "مهمة"}}]})}}]}}],
            "usage": {"total_tokens": 80}})
    cfg = AIConfig("https://br-test.ai.c-2.eu-central-1.aws.neon.tech", "test-secret", "configured-model")
    content, actions, usage = NeonAI(cfg, httpx.MockTransport(handle)).answer("طلب", {"project": {"id": "p_general"}}, [], True)
    assert content == "رد [S1]" and len(actions) == 1 and usage["total_tokens"] == 80
    payload = json.loads(captured[0].content)
    assert str(captured[0].url).endswith("/v1/chat/completions")
    assert payload["max_tokens"] == 1800 and "test-secret" not in captured[0].content.decode()
    assert "test-secret" not in repr(cfg)
    bad = httpx.MockTransport(lambda _: httpx.Response(403, json={"error": {"message": "test-secret"}}))
    with pytest.raises(WorkspaceError) as error: NeonAI(cfg, bad).models()
    assert "test-secret" not in str(error.value)


def test_context_excludes_unselected_files_credentials_and_other_projects(setup):
    store, owner, _ = setup
    store.put(owner, "projects", {"id": "p2", "name": "ثانٍ"})
    store.add_files(owner, [parse_upload("selected.txt", "نص مسموح".encode(), "p_general"),
        parse_upload("hidden.txt", "نص لم يختره المستخدم".encode(), "p_general"), parse_upload("other.txt", b"other-project", "p2")])
    state, _ = store.read(owner)
    selected = state["files"][0]["id"]
    context, refs, _ = build_context(store, owner, state, "p_general", [selected], "ملخص", False)
    encoded = json.dumps(context, ensure_ascii=False)
    assert "نص مسموح" in encoded
    assert "نص لم يختره المستخدم" not in encoded and "other-project" not in encoded
    assert "blob" not in encoded and PASSWORD not in encoded and "password_hash" not in encoded
    assert context["tasks"] == [] and context["members"] == [] and len(refs) == 1
    with pytest.raises(WorkspaceError): build_context(store, owner, state, "p_general", [state["files"][-1]["id"]], "x")


def test_gateway_distinguishes_empty_credits_from_invalid_credentials():
    cfg = AIConfig("https://br-test.ai.c-2.eu-central-1.aws.neon.tech", "test-secret", "configured-model")
    transport = httpx.MockTransport(lambda _: httpx.Response(403, json={"error": {"message": "AI Gateway credits required. Add credits to continue."}}))
    with pytest.raises(WorkspaceError, match="رصيد استدلال") as error:
        NeonAI(cfg, transport).answer("اختبار", {}, [], False)
    assert "test-secret" not in str(error.value)


def test_inference_check_requires_an_actual_bounded_reply_without_team_data():
    captured = []
    def handle(request):
        captured.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": "READY"}}]})
    cfg = AIConfig("https://br-test.ai.c-2.eu-central-1.aws.neon.tech", "test-secret", "configured-model")
    NeonAI(cfg, httpx.MockTransport(handle)).check_inference()
    assert len(captured) == 1
    assert captured[0]["max_tokens"] == 32 and captured[0]["tools"]
    assert captured[0]["tool_choice"] == "none"
    assert captured[0]["messages"] == [{"role": "user", "content": "Reply with the word READY only."}]
    bad = httpx.MockTransport(lambda _: httpx.Response(200, json={"choices": []}))
    with pytest.raises(WorkspaceError, match="دون إجابة اختبارية"):
        NeonAI(cfg, bad).check_inference()


@pytest.mark.parametrize("allow_actions", [True, False])
def test_luna_uses_the_gateway_fast_mode_with_execution_tools(allow_actions):
    from assistant_desk import DESK_TOOL, SYSTEM
    captured = []
    def gateway(request):
        payload = json.loads(request.content)
        captured.append(payload)
        # Reproduce the actual upstream rejection observed in production.
        if payload.get("tools") and payload.get("reasoning_effort") != "none":
            return httpx.Response(400, json={"error_code": "BAD_REQUEST", "message":
                "Function tools with reasoning_effort are not supported for gpt-6-luna in /v1/chat/completions. "
                "To use function tools, use /v1/responses or set reasoning_effort to 'none'."})
        return httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {"content": "READY"}}]})
    cfg = AIConfig("https://br-test.ai.c-2.eu-central-1.aws.neon.tech", "test-secret", "gpt-6-luna")
    client = NeonAI(cfg, httpx.MockTransport(gateway))
    answer, actions, _ = client.answer("اختبار", {}, [], allow_actions, system=SYSTEM, tool=DESK_TOOL)
    assert answer == "READY" and actions == []
    assert captured[0]["reasoning_effort"] == "none"
    assert bool(captured[0].get("tools")) == allow_actions
    client.check_inference()
    assert captured[1]["reasoning_effort"] == "none" and captured[1]["tools"]
    assert captured[1]["tool_choice"] == "none" and captured[1]["max_tokens"] == 32


def test_connection_page_keeps_diagnostics_and_hides_completed_setup(tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest
    from tests.test_ui import healthy, element
    import cloud_storage
    url = "sqlite:///" + str(tmp_path / "ui_connections.db")
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("GDAY_LOCAL_MODE", "true")
    monkeypatch.setenv("NEON_AI_GATEWAY_BASE_URL", "https://br-test.ai.c-2.eu-central-1.aws.neon.tech")
    monkeypatch.setenv("NEON_AI_GATEWAY_TOKEN", "test-secret-not-real")
    monkeypatch.setenv("NEON_AI_MODEL", "configured-model")
    storage = NeonStorage(ENDPOINT, "gday-private", "test-access", "test-secret", "eu-central-1", FakeS3())
    monkeypatch.setattr(cloud_storage, "storage_from_settings", lambda _: (storage, ""))
    def needs_credit(_):
        raise AICreditsRequired("يحتاج رصيد استدلال للاختبار")
    monkeypatch.setattr(NeonAI, "check_inference", needs_credit)
    store = Store(url)
    store.bootstrap("owner", PASSWORD)
    app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py"), default_timeout=20)
    app.session_state["token"] = store.login("owner", PASSWORD)
    app.run()
    app.radio(key="navigation").set_value("الربط والتخزين").run()
    healthy(app)
    assert not app.code
    assert not any(b.label == "نقل الملفات الحالية" for b in app.button)
    element(app.button, "فحص مخزن الملفات").click().run()
    healthy(app)
    assert any("نجح الوصول إلى المخزن الخاص" in x.value for x in app.success)
    element(app.button, "اختبار تشغيل المساعد").click().run()
    healthy(app)
    assert any("رصيد استدلال" in x.value for x in app.warning)
    app.run()
    assert any("رصيد استدلال" in x.value for x in app.warning)
    assert any("نجح الوصول إلى المخزن الخاص" in x.value for x in app.success)
    monkeypatch.setenv("NEON_AI_GATEWAY_TOKEN", "replacement-test-key")
    app.run()
    healthy(app)
    assert not any("رصيد استدلال" in x.value for x in app.warning)


def test_native_ai_ui_persists_reply_and_reviewed_task(tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest
    from tests.test_ui import healthy, element
    url = "sqlite:///" + str(tmp_path / "ui_ai.db")
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("GDAY_LOCAL_MODE", "true")
    monkeypatch.setenv("NEON_AI_GATEWAY_BASE_URL", "https://br-test.ai.c-2.eu-central-1.aws.neon.tech")
    monkeypatch.setenv("NEON_AI_GATEWAY_TOKEN", "test-secret-not-real")
    monkeypatch.setenv("NEON_AI_MODEL", "configured-model")
    store = Store(url)
    store.bootstrap("owner", PASSWORD)
    token = store.login("owner", PASSWORD)
    monkeypatch.setattr(NeonAI, "answer", lambda *args, **kwargs: ("مقترح جاهز للمراجعة", [
        {"kind": "task_create", "values": {"title": "مهمة من محادثة AI"}}], {"total_tokens": 50}))
    app = AppTest.from_string('''
import os
import streamlit as st
from app import setting
from ai_ui import assistant_chat
from workspace import Store
store=Store(os.environ['DATABASE_URL'])
token=st.session_state['token']
state,_,actor=store.context(token)
assistant_chat(store,token,state,actor,setting)
''', default_timeout=20)
    app.session_state["token"] = token
    app.run()
    healthy(app)
    app.chat_input[0].set_value("جهز مهمة للمراجعة").run()
    healthy(app)
    assert not store.read(token)[0]["tasks"]
    assert any("مقترح جاهز" in x.value for x in app.markdown)
    element(app.checkbox, "راجعت المقترح وأريد حفظ هذه التغييرات").check().run()
    element(app.button, "تطبيق وحفظ").click().run()
    healthy(app)
    assert store.read(token)[0]["tasks"][0]["title"] == "مهمة من محادثة AI"
