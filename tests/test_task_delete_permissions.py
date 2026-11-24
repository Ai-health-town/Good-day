import pytest

from workspace import Conflict, Forbidden, Store
from tests.test_file_actions import make_abdullah
from tests.test_task_actions import dialog, seed_task
from tests.test_task_shortcuts import platform
from tests.test_ui import element, healthy
from tests.test_workspace import workspace, make_user, task


@pytest.mark.parametrize("role,username,allowed", [
    ("admin", "owner", True),
    ("manager", "supervisor", True),
    ("file_manager", "abdullah", True),
    ("file_manager", "another_librarian", False),
    ("member", "abdullah", False),
    ("viewer", "abdullah", False),
    ("agent", "abdullah", False),
])
def test_task_delete_capability_is_specific_to_authorized_accounts(role, username, allowed):
    assert Store.can_delete_tasks({"role": role, "username": username, "agent_edit": True}) is allowed


@pytest.mark.parametrize("view", ["نظرة اليوم", "الجدول", "لوحة الإنجاز", "التفاصيل"])
def test_abdullah_can_confirm_task_deletion_in_every_task_view(workspace, monkeypatch, view):
    store, owner = workspace
    seed_task(store, owner)
    _, token = make_abdullah(store, owner)
    before = store.read(owner)[0]
    actor_before = store.actor(token)
    app = dialog(store, token, monkeypatch) if view == "التفاصيل" else platform(store, token, monkeypatch, view)
    assert not any(b.label == "حذف المهمة" and b.disabled for b in app.button)
    assert element(app.button, "حذف المهمة نهائيًا").disabled
    element(app.checkbox, "تأكيد حذف هذه المهمة").check().run()
    healthy(app)
    element(app.button, "حذف المهمة نهائيًا").click().run()
    healthy(app)
    after = store.read(owner)[0]
    assert after["tasks"] == []
    for collection in ("files", "members", "projects", "stakeholders", "messages"):
        assert after[collection] == before[collection]
    assert store.actor(token)["role"] == actor_before["role"] == "file_manager"


def test_abdullah_task_delete_keeps_other_management_permissions_and_version_checks(workspace):
    store, owner = workspace
    seed_task(store, owner)
    store.put(owner, "tasks", task("keep"))
    _, token = make_abdullah(store, owner)
    original = next(t for t in store.read(owner)[0]["tasks"] if t["id"] == "actions")
    store.put(owner, "tasks", original | {"title": "تحديث زميل"}, original["version"])
    with pytest.raises(Conflict):
        store.remove(token, "tasks", "actions", original["version"])
    for collection in ("projects", "members", "stakeholders"):
        with pytest.raises(Forbidden):
            store.remove(token, collection, "unrelated-record", 1)
    latest = next(t for t in store.read(owner)[0]["tasks"] if t["id"] == "actions")
    store.remove(token, "tasks", "actions", latest["version"])
    state = store.read(owner)[0]
    assert [t["id"] for t in state["tasks"]] == ["keep"]
    assert state["files"][0]["id"] == "attached"


def test_other_file_managers_still_cannot_delete_tasks_on_server(workspace):
    store, owner = workspace
    seed_task(store, owner)
    _, token = make_user(store, owner, "file_manager")
    before = store.read(owner)
    with pytest.raises(Forbidden):
        store.remove(token, "tasks", "actions", 1)
    assert store.read(owner) == before
