import json
from pathlib import Path

import pytest
from sqlalchemy import select
from streamlit.testing.v1 import AppTest

from workspace import Conflict, Forbidden, WorkspaceError, snapshots
from tests.test_workspace import workspace, make_user, task
from tests.test_ui import healthy


def seed(store, token):
    store.put(token, "projects", {"id": "p_target", "name": "مشروع الاختبار"})
    store.put(token, "projects", {"id": "p_other", "name": "مشروع آخر"})
    store.put(token, "tasks", task("t_source") | {"attachedFileId": "f_source", "stakeholderId": "s_shared",
              "comments": [{"text": "يبقى التعليق"}], "subtasks": [{"id": "step", "text": "خطوة محفوظة", "done": True}]})
    store.put(token, "tasks", task("t_other") | {"projectId": "p_other"})
    store.put(token, "files", {"id": "f_source", "title": "جدول الاختبار", "type": "sheet", "projectId": "p_general",
              "blob": "b3JpZ2luYWw=", "sheets": [{"name": "Sheet1", "rows": [["قيمة", "نتيجة"], [0, "=A2+1"]]}],
              "comments": [{"text": "تعليق الملف"}]})
    store.put(token, "stakeholders", {"id": "s_shared", "name": "جهة مشتركة", "phone": "+966500000001"})
    store.put(token, "stakeholders", {"id": "s_source", "name": "جهة المصدر", "projectId": "p_general"})
    store.put(token, "stakeholders", {"id": "s_other", "name": "جهة أخرى", "projectId": "p_other"})
    store.put(token, "messages", {"id": "m_keep", "text": "محادثة محفوظة", "projectId": "p_general"})


def test_project_move_preserves_content_links_and_saves_a_recovery_point(workspace):
    store, token = workspace
    seed(store, token)
    before, revision = store.read(token)
    assert store.move_project_contents(token, "p_general", "p_target", revision) == {"tasks": 1, "files": 1, "stakeholders": 2}
    after, new_revision = store.read(token)
    assert new_revision == revision + 1
    for name in ("tasks", "files", "stakeholders"):
        for old, new in zip(before[name], after[name]):
            moved = old.get("projectId") == "p_general" or name == "stakeholders" and not old.get("projectId")
            if moved:
                assert new["projectId"] == "p_target"
                assert new["version"] == old["version"] + 1
                clean_new = {k: v for k, v in new.items() if k not in ("projectId", "version", "updatedAt", "updatedBy")}
                clean_old = {k: v for k, v in old.items() if k not in ("projectId", "version", "updatedAt", "updatedBy")}
                assert clean_new == clean_old
            else:
                assert new == old
    for name in ("projects", "members", "messages", "handover"):
        assert after[name] == before[name]
    with store.engine.connect() as conn:
        saved = conn.execute(select(snapshots.c.payload)).scalar_one()
        assert json.loads(saved) == before
    assert store.move_project_contents(token, "p_general", "p_target", new_revision) == {"tasks": 0, "files": 0, "stakeholders": 0}
    assert store.read(token)[1] == new_revision


def test_project_move_rejects_stale_state_invalid_destinations_and_readonly_accounts(workspace):
    store, token = workspace
    seed(store, token)
    _, revision = store.read(token)
    for source, target in [("p_general", "p_general"), ("missing", "p_target"), ("p_general", "missing")]:
        with pytest.raises(WorkspaceError):
            store.move_project_contents(token, source, target, revision)
    with pytest.raises(Conflict):
        store.move_project_contents(token, "p_general", "p_target", revision - 1)
    for role in ("viewer", "agent"):
        _, readonly = make_user(store, token, role)
        with pytest.raises(Forbidden):
            store.move_project_contents(readonly, "p_general", "p_target", store.read(token)[1])


def test_project_contacts_follow_selected_scope_and_project_removal(workspace, monkeypatch):
    store, token = workspace
    seed(store, token)
    store.move_project_contents(token, "p_general", "p_target", store.read(token)[1])
    monkeypatch.setenv("DATABASE_URL", str(store.engine.url))
    monkeypatch.setenv("GDAY_LOCAL_MODE", "true")
    app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py"), default_timeout=20)
    app.session_state["token"] = token
    app.session_state["navigation"] = "الجهات"
    app.session_state["scope_project"] = "p_target"
    app.run(); healthy(app)
    names = [x.value for x in app.subheader]
    assert "جهة مشتركة" in names and "جهة المصدر" in names and "جهة أخرى" not in names
    app.selectbox(key="scope_project").set_value("p_general").run(); healthy(app)
    assert not any(x.value in ("جهة مشتركة", "جهة المصدر", "جهة أخرى") for x in app.subheader)
    store.remove(token, "projects", "p_target", 1)
    state, _ = store.read(token)
    assert all(s.get("projectId") == "p_general" for s in state["stakeholders"] if s["id"] != "s_other")
