from datetime import date, timedelta
from pathlib import Path

from streamlit.testing.v1 import AppTest

from tests.test_ui import element, healthy
from tests.test_workspace import task, workspace
import workspace as workspace_module


def add_task(store, token, ident, due, status="todo", project="p_general"):
    store.put(token, "tasks", task(ident) | {"dueDate": due, "status": status, "projectId": project})


def dashboard(store, token, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", str(store.engine.url))
    monkeypatch.setenv("GDAY_LOCAL_MODE", "true")
    app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py"), default_timeout=20)
    app.session_state["token"] = token
    app.session_state["navigation"] = "نظرة اليوم"
    app.run()
    healthy(app)
    return app


def progress(app):
    return next(metric for metric in app.metric if metric.label == "نسبة إنجاز اليوم")


def test_completion_counts_only_due_today_and_changes_with_task_status(workspace, monkeypatch):
    store, token = workspace
    today = workspace_module.today_iso()
    yesterday = (date.fromisoformat(today) - timedelta(days=1)).isoformat()
    tomorrow = (date.fromisoformat(today) + timedelta(days=1)).isoformat()
    for index in range(8): add_task(store, token, "past_" + str(index), yesterday, "done")
    add_task(store, token, "overdue", yesterday)
    add_task(store, token, "today_done", today, "done")
    add_task(store, token, "today_open", today, "in_progress")
    add_task(store, token, "today_waiting", today, "waiting_stakeholder")
    add_task(store, token, "future_done", tomorrow, "done")
    add_task(store, token, "future_open", tomorrow)
    add_task(store, token, "undated_done", "", "done")
    app = dashboard(store, token, monkeypatch)
    assert progress(app).value == "33%"
    assert "1 من 3" in progress(app).help
    current = next(t for t in store.read(token)[0]["tasks"] if t["id"] == "today_open")
    store.patch_tasks(token, [{"id": current["id"], "version": current["version"], "changes": {"status": "done"}}])
    app.run()
    healthy(app)
    assert progress(app).value == "67%"
    assert "2 من 3" in progress(app).help
    current = next(t for t in store.read(token)[0]["tasks"] if t["id"] == "today_done")
    store.patch_tasks(token, [{"id": current["id"], "version": current["version"], "changes": {"status": "todo"}}])
    app.run()
    healthy(app)
    assert progress(app).value == "33%"


def test_no_tasks_due_today_show_zero_instead_of_historical_completion(workspace, monkeypatch):
    store, token = workspace
    yesterday = (date.fromisoformat(workspace_module.today_iso()) - timedelta(days=1)).isoformat()
    add_task(store, token, "old_done", yesterday, "done")
    add_task(store, token, "no_date_done", "", "done")
    app = dashboard(store, token, monkeypatch)
    assert progress(app).value == "0%"
    assert "لا توجد مهام مستحقة اليوم" in progress(app).help


def test_new_riyadh_day_resets_completion_in_the_same_session(workspace, monkeypatch):
    store, token = workspace
    current_day = ["2026-11-15"]
    monkeypatch.setattr(workspace_module, "today_iso", lambda: current_day[0])
    add_task(store, token, "day_one_done", "2026-11-15", "done")
    add_task(store, token, "day_one_open", "2026-11-15")
    add_task(store, token, "day_two_done", "2026-11-16", "done")
    app = dashboard(store, token, monkeypatch)
    assert progress(app).value == "50%"
    current_day[0] = "2026-11-16"
    app.run()
    healthy(app)
    assert progress(app).value == "100%"
    assert "1 من 1" in progress(app).help


def test_daily_completion_respects_selected_project(workspace, monkeypatch):
    store, token = workspace
    today = workspace_module.today_iso()
    store.put(token, "projects", {"id": "p_other", "name": "مشروع آخر"})
    add_task(store, token, "general_done", today, "done")
    add_task(store, token, "other_open", today, project="p_other")
    app = dashboard(store, token, monkeypatch)
    assert progress(app).value == "50%"
    element(app.selectbox, "المشروع المعروض").set_value("p_other").run()
    healthy(app)
    assert progress(app).value == "0%"
    element(app.selectbox, "المشروع المعروض").set_value("p_general").run()
    healthy(app)
    assert progress(app).value == "100%"
