import json
import threading
import time
from pathlib import Path

import pytest
from sqlalchemy import insert, select, update
from streamlit.testing.v1 import AppTest

from ai_service import AIConfig, AICreditsRequired, AIGatewayLimit, NeonAI
from ai_store import runs, usage_days
from assistant_desk import AssistantDesk, DeskWorker
from workspace import Store, Conflict, Forbidden, WorkspaceError, now_iso
from tests.test_workspace import task
from tests.test_ui import element, healthy

PASSWORD = "Test-only-password-739!"


@pytest.fixture
def desk(tmp_path):
    store = Store("sqlite:///" + str(tmp_path/"desk.db"))
    store.bootstrap("owner", PASSWORD, "المدير")
    token = store.login("owner", PASSWORD)
    service = store.create_user(token, "gday.assistant", "المساعد الذكي", PASSWORD, "agent", agent_edit=True)
    store.put(token, "projects", {"id": "p_work", "name": "مشروع الاختبار"})
    return store, token, service, AssistantDesk(store)


def submit(desk, ident="desk_test_request_001", question="لخص المشروع"):
    store, token, _, repo = desk
    return repo.submit(token, "p_work", question, ident)


def complete(repo, job, actions=None, answer="هذه نتيجة محفوظة"):
    data, sources, warnings, guards = repo.prepare(job)
    repo.finish(job["id"], job["details"]["lease"], answer, actions or [], {"total_tokens": 42}, sources, warnings, guards, "fast-test-model")


def test_request_is_assigned_to_assistant_and_submission_is_idempotent(desk):
    store, token, service, repo = desk
    ident = submit(desk)
    assert submit(desk) == ident
    state, _ = store.read(token)
    assert len(state["tasks"]) == 1
    assert state["tasks"][0]["assistantRequestId"] == ident
    service_member = next(u["member_id"] for u in store.list_users(token) if u["id"] == service)
    assert state["tasks"][0]["assigneeId"] == service_member
    assert repo.list_requests(token, "p_work")[0]["status"] == "queued"
    assert repo.claim()["id"] == ident
    assert repo.claim() is None


def test_daily_40_counter_does_not_block_new_requests(desk):
    store, token, _, repo = desk
    with store.engine.begin() as conn:
        conn.execute(insert(usage_days).values(owner_id=store.actor(token)["id"], day=now_iso()[:10], count=500))
    assert submit(desk)
    job = repo.claim()
    complete(repo, job)
    assert repo.list_requests(token, "p_work")[0]["answer"] == "هذه نتيجة محفوظة"


def test_results_are_private_and_other_accounts_cannot_retry_them(desk):
    store, token, _, repo = desk
    ident = submit(desk)
    store.create_user(token, "other", "زميل", PASSWORD, "member")
    other = store.login("other", PASSWORD)
    job = repo.claim()
    repo.hold(ident, job["details"]["lease"], "retry", "أعد المحاولة")
    assert not repo.list_requests(other, "p_work")
    with pytest.raises(Forbidden): repo.retry(other, ident)
    with pytest.raises(Forbidden): repo.submit(other, "p_work", "طلب آخر", ident)


def test_execution_saves_result_and_changes_once_with_service_attribution(desk):
    store, token, _, repo = desk
    submit(desk, question="أضف مهمة ومستندًا وجهة")
    job = repo.claim()
    complete(repo, job, [
        {"kind": "task_create", "values": {"title": "متابعة جديدة"}},
        {"kind": "document_create", "values": {"title": "تقرير", "text": "نتيجة التنفيذ"}},
        {"kind": "contact_create", "values": {"name": "جهة الاختبار", "phone": "٠٥٠٠٠٠٠٠٠١"}},
    ])
    state, revision = store.read(token)
    assert state["tasks"][0]["status"] == "done"
    assert len(state["tasks"]) == 2 and len(state["files"]) == 1
    assert state["stakeholders"][0]["phone"] == "+966500000001"
    assert state["files"][0]["updatedBy"] == state["tasks"][0]["assigneeId"]
    assert repo.list_requests(token, "p_work")[0]["meta"]["executed"] == 3
    with pytest.raises(Conflict): complete(repo, job)
    assert store.read(token)[1] == revision


def test_conflicting_edit_rolls_back_the_entire_result(desk):
    store, token, _, repo = desk
    store.put(token, "tasks", task("t1") | {"projectId": "p_work"})
    submit(desk)
    job = repo.claim()
    _, sources, warnings, guards = repo.prepare(job)
    old = next(t for t in store.read(token)[0]["tasks"] if t["id"] == "t1")
    store.put(token, "tasks", old | {"title": "تعديل الزميل"}, old["version"])
    before = store.read(token)
    with pytest.raises(Conflict):
        repo.finish(job["id"], job["details"]["lease"], "رد", [
            {"kind": "document_create", "values": {"title": "لا يحفظ جزئيًا", "text": "نص"}},
            {"kind": "task_update", "target_id": "t1", "values": {"status": "done"}},
        ], {}, sources, warnings, guards, "test")
    assert store.read(token) == before


def test_disabled_assistant_and_readonly_requester_cannot_apply_changes(desk):
    store, token, service, repo = desk
    store.create_user(token, "viewer", "قارئ", PASSWORD, "viewer")
    viewer = store.login("viewer", PASSWORD)
    repo.submit(viewer, "p_work", "سؤال", "desk_readonly_request")
    job = repo.claim()
    with pytest.raises(Forbidden): complete(repo, job, [{"kind": "task_create", "values": {"title": "غير مسموح"}}])
    complete(repo, job)
    assert store.read(token)[0]["tasks"][0]["status"] == "done"
    store.update_user(token, service, "agent", False, True)
    with pytest.raises(WorkspaceError): submit(desk)


def test_stale_worker_lease_cannot_save_after_recovery(desk):
    store, token, _, repo = desk
    ident = submit(desk)
    abandoned = repo.claim()
    with store.engine.begin() as conn:
        conn.execute(update(runs).where(runs.c.id == ident).values(started=time.time()-181))
    replacement = repo.claim()
    with pytest.raises(Conflict): complete(repo, abandoned)
    complete(repo, replacement)
    assert repo.list_requests(token, "p_work")[0]["status"] == "complete"


@pytest.mark.parametrize("action", [
    {"kind": "delete", "values": {"id": "t1"}},
    {"kind": "contact_create", "values": {"name": "x", "role": "admin"}},
    {"kind": "document_update", "target_id": "unknown", "values": {"text": "x"}},
])
def test_model_cannot_delete_escalate_or_edit_unseen_records(desk, action):
    store, token, _, repo = desk
    submit(desk)
    job = repo.claim()
    before = store.read(token)
    with pytest.raises(WorkspaceError): complete(repo, job, [action])
    assert store.read(token) == before


def test_worker_runs_in_background_and_retains_credit_blocked_requests(desk):
    store, token, _, repo = desk
    submit(desk)
    started, release = threading.Event(), threading.Event()

    class FakeClient:
        def __init__(self, config): pass
        def answer(self, *args, **kwargs):
            started.set()
            release.wait(5)
            raise AICreditsRequired("private transport detail")

    worker = DeskWorker(repo, AIConfig("https://test.neon.tech", "not-real", "test"), FakeClient)
    worker.kick()
    assert started.wait(3)
    assert repo.list_requests(token, "p_work")[0]["status"] == "pending"
    release.set()
    worker.pool.shutdown(wait=True)
    saved = repo.list_requests(token, "p_work")[0]
    assert saved["status"] == "waiting" and saved["details"]["error_code"] == "credits"
    assert "private transport detail" not in saved["details"]["error"]
    repo.retry(token, saved["id"])
    assert repo.list_requests(token, "p_work")[0]["status"] == "queued"


def test_simple_center_submits_and_displays_a_result_without_old_controls(desk, monkeypatch):
    import assistant_ui
    store, token, _, repo = desk

    class InlineWorker:
        def kick(self):
            job = repo.claim()
            if job: complete(repo, job)

    monkeypatch.setattr(assistant_ui, "resources", lambda *args: (repo, InlineWorker()))
    monkeypatch.setenv("DATABASE_URL", str(store.engine.url))
    monkeypatch.setenv("GDAY_LOCAL_MODE", "true")
    app = AppTest.from_file(str(Path(__file__).resolve().parents[1]/"app.py"), default_timeout=20)
    app.session_state["token"] = token
    app.session_state["navigation"] = "مركز المساعد"
    app.run(); healthy(app)
    assert not any("طلبات حسابك اليوم" in x.value for x in app.caption)
    assert not any(x.label in ("محادثاتي المحفوظة", "مشروع المحادثة") for x in app.selectbox)
    element(app.text_area, "وش تحتاج من المساعد؟").set_value("لخص المشروع")
    element(app.button, "إرسال إلى المساعد ←").click().run(); healthy(app)
    assert any("هذه نتيجة محفوظة" in x.value for x in app.markdown)
    assert store.read(token)[0]["tasks"][0]["status"] == "done"


def test_provider_limit_is_deferred_durably_and_resumes_without_duplicate_tasks(desk):
    store, token, _, repo = desk
    ident = submit(desk)
    job = repo.claim()
    repo.defer(ident, job["details"]["lease"], 3600, "حد مؤقت لدى المزود")
    assert repo.claim() is None
    with pytest.raises(Conflict): repo.retry(token, ident)
    reopened = AssistantDesk(Store(str(store.engine.url)))
    assert reopened.next_wakeup() > time.time()
    with store.engine.begin() as conn:
        conn.execute(update(runs).where(runs.c.id == ident).values(started=time.time()-1))
    recovered = reopened.claim()
    assert recovered["details"]["attempts"] == 1
    complete(reopened, recovered)
    assert len(store.read(token)[0]["tasks"]) == 1
    assert repo.list_requests(token, "p_work")[0]["status"] == "complete"


def test_delayed_request_keeps_relative_dates_anchored_to_submission(desk, monkeypatch):
    import ai_service
    store, token, _, repo = desk
    ident = submit(desk, question="أضف ثلاث مهام لغد")
    with store.engine.begin() as conn:
        conn.execute(update(runs).where(runs.c.id == ident).values(day="2026-11-09"))
    monkeypatch.setattr(ai_service, "today_iso", lambda: "2026-11-10")
    job = repo.claim()
    repo.defer(ident, job["details"]["lease"], 3600, "حد مؤقت")
    with store.engine.begin() as conn:
        conn.execute(update(runs).where(runs.c.id == ident).values(started=time.time()-1))
    resumed = AssistantDesk(Store(str(store.engine.url))).claim()
    context, _, _, _ = repo.prepare(resumed)
    assert context["request_date_riyadh"] == context["date_riyadh"] == "2026-11-09"
    assert context["processing_date_riyadh"] == "2026-11-10"


def test_worker_respects_recorded_provider_cooldown_after_restart(desk):
    store, token, _, repo = desk
    ident = submit(desk)
    job = repo.claim()
    repo.defer(ident, job["details"]["lease"], 3600, "حد مؤقت")
    submit(desk, "desk_second_request")
    calls = []

    class NeverCalled:
        def __init__(self, config): calls.append(True)

    worker = DeskWorker(repo, AIConfig("https://test.neon.tech", "not-real", "test"), NeverCalled)
    worker.kick()
    for future in list(worker.futures): future.result(timeout=5)
    worker.close()
    assert not calls
    assert all(j["status"] == "deferred" for j in repo.list_requests(token, "p_work"))


def test_gateway_recognizes_top_level_daily_spend_limit_and_retry_after():
    import httpx
    transport = httpx.MockTransport(lambda request: httpx.Response(429, headers={"Retry-After": "3600"},
        json={"error_code": "REQUEST_LIMIT_EXCEEDED", "message": "You've reached your AI Gateway daily spend limit."}))
    with pytest.raises(AIGatewayLimit) as error:
        NeonAI(AIConfig("https://test.neon.tech", "not-real", "test"), transport).check_inference()
    assert error.value.retry_after == 3600
    assert "اليومي" in str(error.value)
    assert error.value.kind == "daily_spend"


def test_account_daily_cap_without_reset_header_keeps_request_and_does_not_loop(desk):
    import httpx
    store, token, _, repo = desk
    submit(desk)
    calls = []
    def respond(request):
        calls.append(request)
        return httpx.Response(429, headers={"x-request-id": "support-reference-123"}, json={
            "error_code": "REQUEST_LIMIT_EXCEEDED", "message": "You've reached your AI Gateway daily spend limit. Credits remain."})
    client = lambda config: NeonAI(config, httpx.MockTransport(respond))
    worker = DeskWorker(repo, AIConfig("https://test.neon.tech", "never-store-this-secret", "test-model"), client)
    worker.kick()
    for future in list(worker.futures): future.result(timeout=10)
    worker.kick()
    for future in list(worker.futures): future.result(timeout=10)
    worker.close()
    saved = repo.list_requests(token, "p_work")[0]
    assert len(calls) == 1
    assert saved["status"] == "waiting" and saved["details"]["limit_kind"] == "daily_spend"
    assert saved["details"]["gateway_request_id"] == "support-reference-123"
    assert saved["details"]["failed_model"] == "test-model"
    assert "مستقل عن الرصيد" in saved["details"]["error"]
    assert "never-store-this-secret" not in json.dumps(saved)
    repo.retry(token, saved["id"])
    complete(repo, repo.claim())
    assert len(store.read(token)[0]["tasks"]) == 1
    assert repo.list_requests(token, "p_work")[0]["details"]["limit_kind"] == ""


def test_existing_daily_cap_request_explains_balance_and_retry_time(desk, monkeypatch):
    import assistant_ui
    store, token, _, repo = desk
    submit(desk)
    job = repo.claim()
    repo.defer(job["id"], job["details"]["lease"], 3600, "وصلت خدمة الذكاء إلى حد الصرف اليومي لدى Neon.")
    class PausedWorker:
        def kick(self): pass
    monkeypatch.setattr(assistant_ui, "resources", lambda *args: (repo, PausedWorker()))
    monkeypatch.setenv("DATABASE_URL", str(store.engine.url))
    monkeypatch.setenv("GDAY_LOCAL_MODE", "true")
    app = AppTest.from_file(str(Path(__file__).resolve().parents[1]/"app.py"), default_timeout=20)
    app.session_state["token"] = token
    app.session_state["navigation"] = "مركز المساعد"
    app.run(); healthy(app)
    assert any("مستقل عن الرصيد" in item.value for item in app.warning)
    assert any("لا يضمن انتهاء القيد" in item.value for item in app.caption)
    assert element(app.button, "إعادة المحاولة").disabled


def test_arabic_filenames_with_underscores_are_selected_automatically(desk):
    store, token, _, repo = desk
    for ident, title in [("f1", "مقدمة"), ("f2", "مرجع"), ("f3", "تقرير عام"), ("f4", "الأشرفية_نواقص_الأطباء.docx")]:
        store.put(token, "files", {"id": ident, "title": title, "text": "بيانات التقرير", "type": "doc", "projectId": "p_work"})
    submit(desk, question="لخص ملف الأشرفية")
    data, _, _, _ = repo.prepare(repo.claim())
    assert data["sources"][0]["file_id"] == "f4"
