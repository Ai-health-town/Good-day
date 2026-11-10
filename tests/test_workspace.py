import base64
import copy
import io
import json
from concurrent.futures import ThreadPoolExecutor

import pytest
from docx import Document
from openpyxl import Workbook, load_workbook

from workspace import (Conflict, Forbidden, Store, WorkspaceError, prepare_import,
                       today_iso, uid)
from filetools import docx_bytes, file_text, parse_upload, plain_text, tasks_excel

PASSWORD = "Test-only-password-739!"


@pytest.fixture
def workspace(tmp_path):
    store = Store("sqlite:///" + str(tmp_path / "test.db"))
    store.bootstrap("owner", PASSWORD, "المدير")
    token = store.login("owner", PASSWORD)
    return store, token


def make_user(store, owner, role, edit=False):
    name = role + ("_edit" if edit else "")
    ident = store.create_user(owner, name, name, PASSWORD, role, agent_edit=edit)
    return ident, store.login(name, PASSWORD)


def task(ident=None):
    return {"id": ident or uid(), "title": "متابعة العمل", "projectId": "p_general", "status": "todo", "priority": "medium", "dueDate": today_iso(), "comments": [], "subtasks": []}


def test_login_required_and_wrong_password(workspace):
    store, _ = workspace
    with pytest.raises(Forbidden):
        store.read("forged-token-" * 3)
    assert store.login("owner", "wrong") is None


@pytest.mark.parametrize("role", ["manager", "member", "file_manager", "viewer", "agent"])
def test_activity_records_are_restricted_to_workspace_admin(workspace, role):
    store, owner = workspace
    _, token = make_user(store, owner, role, edit=role == "agent")
    assert store.activity(owner)
    with pytest.raises(Forbidden):
        store.activity(token)


def test_lockout_is_database_backed(workspace):
    store, token = workspace
    for _ in range(5):
        assert store.login("owner", "wrong") is None
    assert store.login("owner", PASSWORD) is None
    assert store.read(token)  # Existing sessions are not silently revoked.


def test_viewer_and_agent_permissions_enforced_on_server(workspace):
    store, owner = workspace
    _, viewer = make_user(store, owner, "viewer")
    _, readonly = make_user(store, owner, "agent")
    _, editor = make_user(store, owner, "agent", True)
    for token in (viewer, readonly):
        assert store.read(token)
        with pytest.raises(Forbidden):
            store.put(token, "tasks", task())
    store.put(editor, "tasks", task())
    with pytest.raises(Forbidden):
        store.create_user(editor, "bad", "bad", PASSWORD, "admin")
    with pytest.raises(Forbidden):
        store.clear_chat(editor, expected_revision=store.read(editor)[1])
    with pytest.raises(Forbidden):
        store.restore(editor, store.backup_bytes(store.read(owner)[0]), store.read(owner)[1])


def test_session_revocation_applies_to_existing_browser(workspace):
    store, owner = workspace
    ident, agent = make_user(store, owner, "agent", True)
    store.update_user(owner, ident, "agent", False, True)
    with pytest.raises(Forbidden):
        store.read(agent)
    assert store.login("agent_edit", PASSWORD) is None


def test_password_reset_and_last_admin_guard(workspace):
    store, owner = workspace
    actor = store.actor(owner)
    with pytest.raises(WorkspaceError):
        store.update_user(owner, actor["id"], "viewer", False)
    store.change_password(owner, PASSWORD, "Different-password-738!")
    with pytest.raises(Forbidden):
        store.read(owner)
    assert store.login("owner", "Different-password-738!")


def test_data_and_remembered_token_survive_new_store(workspace):
    store, owner = workspace
    store.put(owner, "tasks", task("persistent"))
    other = Store(str(store.engine.url))
    assert other.read(owner)[0]["tasks"][0]["id"] == "persistent"


def test_same_record_conflict_and_unrelated_updates(workspace):
    store, owner = workspace
    store.put(owner, "tasks", task("first"))
    store.put(owner, "tasks", task("second"))
    state, _ = store.read(owner)
    first, second = copy.deepcopy(state["tasks"])
    store.put(owner, "tasks", first | {"title": "تعديل عضو 1"}, first["version"])
    with pytest.raises(Conflict):
        store.put(owner, "tasks", first | {"title": "نسخة قديمة"}, first["version"])
    store.put(owner, "tasks", second | {"title": "تعديل مستقل"}, second["version"])
    assert [t["title"] for t in store.read(owner)[0]["tasks"]] == ["تعديل عضو 1", "تعديل مستقل"]


def test_concurrent_adds_are_not_lost(workspace):
    store, owner = workspace
    with ThreadPoolExecutor(max_workers=5) as pool:
        list(pool.map(lambda i: store.put(owner, "tasks", task(str(i))), range(20)))
    assert len(store.read(owner)[0]["tasks"]) == 20


def test_legacy_import_and_accounts_are_separate(workspace):
    store, owner = workspace
    legacy = {"currentUserId": "old_admin", "members": [{"id": "old_admin", "name": "عضو قديم", "role": "admin"}],
              "tasks": [task("old-task")], "files": [{"id": "f1", "type": "doc", "title": "مستند قديم", "content": "<p>النص الأصلي</p>"}],
              "messages": [{"id": "m1", "authorId": "old_admin", "text": "رسالة قديمة"}], "projects": []}
    raw = json.dumps(legacy).encode()
    prepared = prepare_import(raw)
    assert "role" not in prepared["data"]["members"][0]
    store.restore(owner, raw, store.read(owner)[1])
    state, _ = store.read(owner)
    assert state["tasks"][0]["id"] == "old-task"
    assert file_text(state["files"][0]) == "النص الأصلي"
    assert len(store.list_users(owner)) == 1
    assert any(p["id"] == store.actor(owner)["member_id"] for p in state["members"])
    assert len(store.list_snapshots(owner)) == 1


def test_backup_roundtrip_with_binary_and_handover(workspace):
    store, owner = workspace
    record = parse_upload("notes.txt", "محتوى عربي".encode(), "p_general")
    store.put(owner, "files", record)
    store.save_handover(owner, {"summary": "تم الإنجاز", "next_step": "المتابعة غدًا", "decisions": "اعتماد الخطة"}, 1)
    state, revision = store.read(owner)
    raw = store.backup_bytes(state)
    assert b"password_hash" not in raw and b"token_hash" not in raw
    store.put(owner, "tasks", task())
    with pytest.raises(Conflict):
        store.restore(owner, raw, revision)
    store.restore(owner, raw, store.read(owner)[1])
    restored, _ = store.read(owner)
    assert base64.b64decode(restored["files"][0]["blob"]) == "محتوى عربي".encode()
    assert restored["handover"]["next_step"] == "المتابعة غدًا"


@pytest.mark.parametrize("payload", [[], {}, {"tasks": "bad"}, {"tasks": [task("duplicate"), task("duplicate")]},
    {"tasks": [task() | {"status": "invalid"}]}, {"tasks": [task() | {"dueDate": "tomorrow"}]},
    {"tasks": [], "files": [{"id": "f", "title": "x", "blob": "broken"}]},
    {"format": "gday.workspace", "schema_version": 9, "data": {"tasks": []}}])
def test_malformed_backup_rejected_without_overwriting(workspace, payload):
    store, owner = workspace
    state, revision = store.read(owner)
    with pytest.raises(WorkspaceError):
        store.restore(owner, json.dumps(payload).encode(), revision)
    assert store.read(owner) == (state, revision)


def test_chat_clear_and_ownership(workspace):
    store, owner = workspace
    _, one = make_user(store, owner, "member")
    _, other = make_user(store, owner, "manager")
    store.put(one, "messages", {"id": "m1", "text": "رسالة خاصة بالعضو", "projectId": "p_general"})
    store.put(owner, "messages", {"id": "m2", "text": "رسالة المدير", "projectId": "elsewhere"})
    with pytest.raises(Forbidden):
        store.remove(one, "messages", "m2", 1)
    revision = store.read(owner)[1]
    store.clear_chat(other, "p_general", revision)
    assert [m["id"] for m in store.read(owner)[0]["messages"]] == ["m2"]
    store.clear_chat(owner, expected_revision=store.read(owner)[1])
    assert not store.read(owner)[0]["messages"]
    assert "رسالة خاصة" not in json.dumps(store.activity(owner), ensure_ascii=False)


def test_real_docx_xlsx_csv_parsing_and_safe_exports(workspace):
    original_doc = docx_bytes("العنوان", "المحتوى العربي\nسطر ثانٍ")
    record = parse_upload("test.docx", original_doc, "p_general")
    assert "المحتوى العربي" in record["text"]
    assert base64.b64decode(record["blob"]) == original_doc
    book = Workbook()
    book.active.append(["الاسم", "القيمة"])
    book.active.append(["حقيقي", 5678])
    buf = io.BytesIO()
    book.save(buf)
    record = parse_upload("actual.xlsx", buf.getvalue(), "p_general")
    assert record["sheets"][0]["rows"][1] == ["حقيقي", "5678"]
    record = parse_upload("comma.csv", 'اسم,ملاحظة\nعربي,"فاصلة, داخل النص"'.encode(), "p_general")
    assert record["sheets"][0]["rows"][1][1] == "فاصلة, داخل النص"
    store, token = workspace
    store.put(token, "tasks", task() | {"title": '=HYPERLINK("https://example.test")'})
    exported = load_workbook(io.BytesIO(tasks_excel(store.read(token)[0])))
    assert exported.active["A2"].data_type == "s"
    assert plain_text("<script>bad()</script><p>نص آمن</p>") == "نص آمن"


def test_upload_batch_rolls_back_on_invalid_record(workspace):
    store, token = workspace
    record = parse_upload("a.txt", b"original", "p_general")
    with pytest.raises(WorkspaceError):
        store.add_files(token, [record, record])
    assert not store.read(token)[0]["files"]


def test_restore_cannot_reuse_stale_deleted_record_version(workspace):
    store, token = workspace
    store.put(token, "tasks", task("a"))
    old = store.read(token)[0]["tasks"][0]
    raw = store.backup_bytes(store.read(token)[0])
    store.remove(token, "tasks", "a", old["version"])
    store.restore(token, raw, store.read(token)[1])
    with pytest.raises(Conflict):
        store.put(token, "tasks", old | {"title": "قديم"}, old["version"])
