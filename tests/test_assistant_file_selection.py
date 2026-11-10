from pathlib import Path

import pytest
from sqlalchemy import func, select
from streamlit.testing.v1 import AppTest

from ai_store import runs
from assistant_desk import AssistantDesk
from tests.test_assistant_desk import desk, complete
from tests.test_ui import element, healthy
from workspace import Store, WorkspaceError, dumps


def add_file(store, token, ident, text="بيانات الملف المختار", *, expected_version=None, **extra):
    return store.put(token, "files", {"id": ident, "title": ident + ".docx", "type": "doc",
        "text": text, "projectId": "p_work", **extra}, expected_version=expected_version)


def test_explicit_sources_override_ranking_and_exclude_prior_answers(desk):
    store, token, _, repo = desk
    for index in range(4):
        add_file(store, token, "auto_" + str(index), "UNSELECTED_PRIVATE_TEXT", title="تقرير النواقص")
    repo.submit(token, "p_work", "لخص التقرير", "desk_previous_answer")
    complete(repo, repo.claim(), answer="PREVIOUS_UNSELECTED_ANSWER")
    add_file(store, token, "chosen", "CHOSEN_SOURCE_TEXT", title="مرجع بعيد عن كلمات السؤال")
    repo.submit(token, "p_work", "لخص تقرير النواقص", "desk_explicit", file_ids=["chosen"])
    job = repo.claim()
    data, refs, _, guards = repo.prepare(job)
    assert job["history"] == []
    assert {s["file_id"] for s in data["sources"]} == {"chosen"}
    assert {s["file_id"] for s in refs} == {"chosen"}
    assert guards["files"] == {"chosen": 1}
    assert "CHOSEN_SOURCE_TEXT" in dumps(data)
    assert "UNSELECTED_PRIVATE_TEXT" not in dumps(data)
    assert "PREVIOUS_UNSELECTED_ANSWER" not in dumps(data)


def test_all_five_selected_files_survive_large_workspace_context(desk):
    store, token, _, repo = desk
    chosen = ["chosen_" + str(index) for index in range(5)]
    for ident in chosen:
        add_file(store, token, ident, (ident + " محتوى التقرير ") * 400)
    repo.submit(token, "p_work", "لخص الملفات المختارة", "desk_five_sources", file_ids=chosen)
    job = repo.claim()
    job["state"]["stakeholders"] = [{"id": "contact_" + str(i), "name": "جهة",
        "projectId": "p_work", "notes": "سياق آخر " * 1400} for i in range(30)]
    job["state"]["tasks"] += [{"id": "work_" + str(i), "title": "مهمة", "projectId": "p_work",
        "notes": "ملاحظات " * 250, "version": 1} for i in range(40)]
    data, refs, _, guards = repo.prepare(job)
    assert {s["file_id"] for s in data["sources"]} == set(chosen)
    assert set(guards["files"]) == set(chosen)
    assert {s["file_id"] for s in refs} == set(chosen)
    assert len(dumps(data)) <= 24000


@pytest.mark.parametrize("selection", [[], "f1", {}, [None], [["f1"]], ["f1", "f1"],
    ["f1", "f2", "f3", "f4", "f5", "f6"], ["missing"], ["outside"]])
def test_invalid_file_selections_create_no_request_or_task(desk, selection):
    store, token, _, repo = desk
    add_file(store, token, "f1")
    add_file(store, token, "outside", projectId="p_general")
    with pytest.raises(WorkspaceError):
        repo.submit(token, "p_work", "لخص الملفات", "desk_invalid_selection", file_ids=selection)
    assert store.read(token)[0]["tasks"] == []
    with store.engine.connect() as conn:
        assert conn.scalar(select(func.count()).select_from(runs)) == 0


def test_file_selection_is_durable_through_retry_and_idempotent_resubmission(desk):
    store, token, _, repo = desk
    add_file(store, token, "chosen", title="تقرير الأطباء.xlsx", type="sheet",
        sheets=[{"name": "الأطباء", "rows": [["المركز", "العدد"], ["الإسكان", 15]]}])
    ident = repo.submit(token, "p_work", "لخص الملف", "desk_durable_selection", file_ids=["chosen"])
    # Retried submissions return the original request and retain its selection.
    assert repo.submit(token, "p_work", "نص مختلف", ident, file_ids=["missing"]) == ident
    job = repo.claim()
    repo.hold(ident, job["details"]["lease"], "retry", "خطأ مؤقت")
    reopened = AssistantDesk(Store(str(store.engine.url)))
    reopened.retry(token, ident)
    recovered = reopened.claim()
    assert recovered["details"]["file_ids"] == ["chosen"]
    assert recovered["details"]["selected_files"] == [{"id": "chosen", "title": "تقرير الأطباء.xlsx"}]
    data, _, _, _ = reopened.prepare(recovered)
    assert "الإسكان | 15" in dumps(data)
    complete(reopened, recovered)
    assert reopened.list_requests(token, "p_work")[0]["details"]["file_ids"] == ["chosen"]
    assert len(store.read(token)[0]["tasks"]) == 1


@pytest.mark.parametrize("change", ["delete", "move"])
def test_deleted_or_moved_selection_does_not_fall_back_to_another_file(desk, change):
    store, token, _, repo = desk
    add_file(store, token, "chosen")
    add_file(store, token, "unselected", "NEVER_FALL_BACK_TO_THIS")
    repo.submit(token, "p_work", "لخص الملف", "desk_changed_selection", file_ids=["chosen"])
    if change == "delete":
        store.remove(token, "files", "chosen", 1)
    else:
        add_file(store, token, "chosen", projectId="p_general", expected_version=1)
    with pytest.raises(WorkspaceError, match="حُذف أو نُقل"):
        repo.prepare(repo.claim())


def test_unreadable_selection_is_reported_without_summarizing_another_file(desk):
    store, token, _, repo = desk
    add_file(store, token, "empty", "")
    add_file(store, token, "chosen", "نص يمكن قراءته")
    repo.submit(token, "p_work", "لخص الملفين", "desk_partially_readable", file_ids=["empty", "chosen"])
    data, _, warnings, _ = repo.prepare(repo.claim())
    assert {s["file_id"] for s in data["sources"]} == {"chosen"}
    assert any("empty.docx" in warning and "لا يوجد نص" in warning for warning in warnings)
    repo.submit(token, "p_work", "لخص الملف", "desk_unreadable", file_ids=["empty"])
    with pytest.raises(WorkspaceError, match="لم يتوفر نص"):
        repo.prepare(repo.claim())


def ui(desk, monkeypatch, worker):
    import assistant_ui
    store, token, _, repo = desk
    monkeypatch.setattr(assistant_ui, "resources", lambda *args: (repo, worker))
    monkeypatch.setenv("DATABASE_URL", str(store.engine.url))
    monkeypatch.setenv("GDAY_LOCAL_MODE", "true")
    app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py"), default_timeout=20)
    app.session_state["token"] = token
    app.session_state["navigation"] = "مركز المساعد"
    app.run()
    healthy(app)
    return app


def test_summary_picker_submits_exact_files_and_shows_saved_names(desk, monkeypatch):
    store, token, _, repo = desk
    add_file(store, token, "chosen", title="تقرير الأطباء.docx")
    add_file(store, token, "other", title="مرجع آخر.docx")
    add_file(store, token, "outside", projectId="p_general")
    prepared = []

    class InlineWorker:
        def kick(self):
            job = repo.claim()
            if job:
                prepared.append(repo.prepare(job)[0])
                complete(repo, job)

    app = ui(desk, monkeypatch, InlineWorker())
    assert not list(app.multiselect)
    element(app.button, "▤ تلخيص الملفات").click().run()
    healthy(app)
    picker = element(app.multiselect, "الملفات المطلوب تلخيصها")
    assert picker.options == ["تقرير الأطباء.docx", "مرجع آخر.docx"]
    assert picker.max_selections == 5
    assert not element(app.button, "إرسال إلى المساعد ←").disabled
    picker.set_value(["chosen"])
    element(app.button, "إرسال إلى المساعد ←").click().run()
    healthy(app)
    assert {source["file_id"] for source in prepared[0]["sources"]} == {"chosen"}
    saved = repo.list_requests(token, "p_work")[0]
    assert saved["details"]["file_ids"] == ["chosen"]
    assert any("الملفات المختارة: تقرير الأطباء.docx" in item.value for item in app.caption)
    assert element(app.multiselect, "الملفات المطلوب تلخيصها").value == []
    element(app.button, "✳ ملخص المشروع").click().run()
    healthy(app)
    assert not list(app.multiselect)


def test_picker_empty_selection_is_validated_and_empty_library_cannot_submit(desk, monkeypatch):
    store, token, _, repo = desk

    class IdleWorker:
        def kick(self): pass

    app = ui(desk, monkeypatch, IdleWorker())
    element(app.button, "▤ تلخيص الملفات").click().run()
    healthy(app)
    assert element(app.button, "إرسال إلى المساعد ←").disabled
    assert any("لا توجد ملفات" in item.value for item in app.info)
    add_file(store, token, "available")
    app.run()
    healthy(app)
    element(app.button, "إرسال إلى المساعد ←").click().run()
    assert not list(app.exception)
    assert any("اختر ملفًا" in item.value for item in app.error)
    assert repo.list_requests(token, "p_work") == []
