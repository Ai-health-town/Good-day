import copy
import json

import pytest
from sqlalchemy import event

from migration import build_merge
from workspace import Store, Forbidden, Conflict, WorkspaceError, prepare_import

PASSWORD = "Final-tests-password-739!"


@pytest.fixture
def workspace(tmp_path):
    store = Store("sqlite:///" + str(tmp_path / "final.db"))
    store.bootstrap("owner", PASSWORD, "د.عبدالله")
    return store, store.login("owner", PASSWORD)


def legacy_payload():
    return {"members": [{"id": "m1", "name": "عبدالله", "pass": "not-imported", "isAdmin": True}],
        "projects": [{"id": "p_old", "name": "الترميز الطبي"}],
        "stakeholders": [{"id": "s1", "name": "جهة تنسيق", "org": "المراكز"}],
        "files": [{"id": "f1", "title": "مستند", "type": "doc", "content": "<p>محتوى سابق</p>"},
                  {"id": "f2", "title": "جدول", "type": "sheet", "grid": [["العمود"], ["القيمة"]]}],
        "tasks": [{"id": "t1", "title": "مهمة سابقة", "assigneeId": "m1", "projectId": "p_old", "status": "doing", "priority": "med", "dueDate": "2026-11-05", "estHours": 1.5, "fileId": "f1", "stakeholderId": "s1"}],
        "chats": [{"id": "c1", "senderId": "m1", "text": "رسالة قديمة", "time": "09:30"}]}


def test_reference_schema_maps_without_importing_credentials():
    data = prepare_import(json.dumps(legacy_payload()).encode())["data"]
    task = data["tasks"][0]
    assert task["status"] == "in_progress"
    assert task["priority"] == "medium"
    assert task["estimatedMinutes"] == 90
    assert task["attachedFileId"] == "f1"
    assert data["files"][1]["sheetData"] == [["العمود"], ["القيمة"]]
    assert data["messages"][0]["authorId"] == "m1"
    assert "pass" not in data["members"][0]
    assert "isAdmin" not in data["members"][0]


def test_additive_import_as_agent_is_idempotent_and_keeps_accounts(workspace):
    store, owner = workspace
    store.create_user(owner, "assistant", "المساعد", PASSWORD, "agent", agent_edit=True)
    assistant = store.login("assistant", PASSWORD)
    raw = json.dumps(legacy_payload()).encode()
    users_before = store.list_users(owner)
    first = store.merge_workspace(assistant, raw, "p_general", store.read(assistant)[1])
    assert first["tasks_added"] == 1 and first["files_added"] == 3
    state, revision = store.read(owner)
    assert len(state["projects"]) == 1
    assert state["tasks"][0]["assigneeId"] == store.actor(owner)["member_id"]
    assert not state["messages"]
    assert state["tasks"][0]["attachedFileId"] == state["files"][0]["id"]
    second = store.merge_workspace(assistant, raw, "p_general", revision)
    assert second["tasks_added"] == second["files_added"] == second["contacts_added"] == 0
    assert store.list_users(owner) == users_before
    assert len(store.read(owner)[0]["files"]) == 3


def test_merge_never_reverts_a_changed_task(workspace):
    store, owner = workspace
    raw = json.dumps(legacy_payload()).encode()
    store.merge_workspace(owner, raw, "p_general", store.read(owner)[1])
    record = store.read(owner)[0]["tasks"][0]
    store.put(owner, "tasks", record | {"status": "done"}, record["version"])
    store.merge_workspace(owner, raw, "p_general", store.read(owner)[1])
    assert len(store.read(owner)[0]["tasks"]) == 1
    assert store.read(owner)[0]["tasks"][0]["status"] == "done"


def test_merge_permission_and_stale_preview(workspace):
    store, owner = workspace
    store.create_user(owner, "reader", "مشاهد", PASSWORD, "viewer")
    reader = store.login("reader", PASSWORD)
    raw = json.dumps(legacy_payload()).encode()
    with pytest.raises(Forbidden):
        store.merge_workspace(reader, raw, "p_general", store.read(reader)[1])
    revision = store.read(owner)[1]
    store.put(owner, "stakeholders", {"id": "x", "name": "جديدة"})
    with pytest.raises(Conflict):
        store.merge_workspace(owner, raw, "p_general", revision)


def test_table_batch_is_atomic_and_completion_time_is_real(workspace):
    store, owner = workspace
    raw = json.dumps(legacy_payload()).encode()
    store.merge_workspace(owner, raw, "p_general", store.read(owner)[1])
    task = store.read(owner)[0]["tasks"][0]
    original_title = task["title"]
    with pytest.raises(Conflict):
        store.patch_tasks(owner, [{"id": task["id"], "version": task["version"], "changes": {"title": "تعديل لم يُعتمد"}}, {"id": "missing", "version": 1, "changes": {"status": "done"}}])
    assert store.read(owner)[0]["tasks"][0]["title"] == original_title
    store.patch_tasks(owner, [{"id": task["id"], "version": task["version"], "changes": {"status": "done"}}])
    changed = store.read(owner)[0]["tasks"][0]
    assert changed["completedAt"] and changed["status"] == "done"
    with pytest.raises(Conflict):
        store.patch_tasks(owner, [{"id": task["id"], "version": task["version"], "changes": {"status": "todo"}}])
    with pytest.raises(Forbidden):
        store.patch_tasks(owner, [{"id": task["id"], "version": changed["version"], "changes": {"password_hash": "bad"}}])


def test_payload_cache_checks_revision_and_auth_on_every_read(workspace):
    from unittest.mock import patch
    store, owner = workspace
    with patch("workspace.json.loads", wraps=json.loads) as decode:
        state, _, _ = store.context(owner)
        store.context(owner)
        assert decode.call_count == 1
        with pytest.raises(Forbidden):
            store.context("wrong-token-that-is-not-authorized")
        assert decode.call_count == 1
    other = Store(str(store.engine.url))
    other.put(owner, "stakeholders", {"id": "new", "name": "آخر تعديل"})
    with patch("workspace.json.loads", wraps=json.loads) as decode:
        assert store.context(owner)[0]["stakeholders"][0]["name"] == "آخر تعديل"
        assert decode.call_count == 1
    state["projects"][0]["name"] = "لا يكتب في الذاكرة المشتركة"
    assert store.context(owner)[0]["projects"][0]["name"] == "مساحة الفريق"


def test_different_sheet_contents_are_not_deduplicated():
    payload = legacy_payload()
    payload["files"].append({"id": "f3", "title": "جدول مختلف", "type": "sheet", "grid": [["بند مختلف"]]})
    state = {"members": [], "projects": [{"id": "p_general", "name": "عام"}], "files": [], "tasks": [], "stakeholders": [], "messages": []}
    additions, report = build_merge(json.dumps(payload).encode(), state, "p_general")
    assert len([f for f in additions["files"] if f["type"] == "sheet"]) == 2


def test_populated_views_and_board_actions(workspace, monkeypatch):
    from pathlib import Path
    from streamlit.testing.v1 import AppTest
    store, owner = workspace
    monkeypatch.setenv("DATABASE_URL", str(store.engine.url))
    monkeypatch.setenv("GDAY_LOCAL_MODE", "true")
    store.merge_workspace(owner, json.dumps(legacy_payload()).encode(), "p_general", store.read(owner)[1])
    app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py"), default_timeout=15)
    app.session_state["token"] = owner
    app.run()
    for page in ["نظرة اليوم", "المهام", "الملفات", "مركز المساعد", "التقارير"]:
        app.radio(key="navigation").set_value(page).run()
        assert not list(app.exception), [x.message for x in app.exception]
        assert not list(app.error), [x.value for x in app.error]
    app.radio(key="navigation").set_value("المهام").run()
    next(r for r in app.radio if r.label == "طريقة العرض").set_value("لوحة الإنجاز").run()
    next(b for b in app.button if b.label == "إنجاز ✓").click().run()
    assert not list(app.error)
    assert store.read(owner)[0]["tasks"][0]["status"] == "done"
    assert store.read(owner)[0]["tasks"][0]["completedAt"]


def test_inline_table_edit_reaches_persistent_storage(workspace, monkeypatch):
    import hashlib
    from pathlib import Path
    from streamlit.testing.v1 import AppTest
    store, owner = workspace
    monkeypatch.setenv("DATABASE_URL", str(store.engine.url))
    monkeypatch.setenv("GDAY_LOCAL_MODE", "true")
    store.put(owner, "tasks", {"id": "grid_task", "title": "مهمة الجدول", "projectId": "p_general", "status": "todo", "priority": "medium", "dueDate": "2026-11-05", "estimatedMinutes": 30})
    app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py"), default_timeout=15)
    app.session_state["token"] = owner
    app.run(); app.radio(key="navigation").set_value("المهام").run()
    view = hashlib.sha256(json.dumps([["grid_task"], "", "", "كل المهام"]).encode()).hexdigest()[:14]
    app.session_state["grid_" + view] = {"edited_rows": {0: {"المرحلة": "مكتملة"}}, "added_rows": [], "deleted_rows": []}
    next(b for b in app.button if b.label == "حفظ تعديلات الجدول").click().run()
    assert not list(app.error), [e.value for e in app.error]
    assert store.read(owner)[0]["tasks"][0]["status"] == "done"
