import copy
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from tests.test_ui import element, healthy
from tests.test_workspace import workspace, task, make_user
from workspace import Forbidden


def seed_task(store, token):
    store.put(token, "files", {"id": "attached", "title": "ملف مرتبط", "type": "doc", "text": "الأصل", "comments": []})
    store.put(token, "tasks", task("actions") | {
        "attachedFileId": "attached", "dueTime": "14:30", "reminderEnabled": True, "reminderMinutes": 15,
        "notes": "ملاحظات المهمة الأصلية",
        "comments": [{"id": "comment", "text": "تعليق محفوظ", "authorId": store.actor(token)["member_id"]}],
        "subtasks": [{"id": "one", "text": "الخطوة الأولى", "done": True}, {"id": "two", "text": "الخطوة الثانية", "done": False}],
    })


def dialog(store, token, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", str(store.engine.url))
    source = '''
import os
import streamlit as st
from workspace import Store
from components import edit_task
store = Store(os.environ['DATABASE_URL'])
token = st.session_state['token']
state, _, actor = store.context(token)
record = next((r for r in state['tasks'] if r['id'] == 'actions'), None)
if record:
    edit_task(store, token, state, actor, st.session_state.get('frozen_record', record))
'''
    app = AppTest.from_string(source, default_timeout=20)
    app.session_state["token"] = token
    app.run()
    healthy(app)
    return app


def test_edit_and_delete_subtasks_preserve_the_task_and_other_step(workspace, monkeypatch):
    store, owner = workspace
    seed_task(store, owner)
    before = store.read(owner)[0]["tasks"][0]
    app = dialog(store, owner, monkeypatch)
    assert all(button.disabled for button in app.button if button.label == "حذف الخطوة نهائيًا")
    element(app.text_input, "نص الخطوة").set_value("الخطوة الأولى بعد التعديل")
    element(app.button, "حفظ الخطوة").click().run()
    healthy(app)
    changed = store.read(owner)[0]["tasks"][0]
    assert changed["subtasks"] == [before["subtasks"][0] | {"text": "الخطوة الأولى بعد التعديل"}, before["subtasks"][1]]
    for field in ("comments", "notes", "attachedFileId", "dueDate", "dueTime", "reminderEnabled", "reminderMinutes"):
        assert changed[field] == before[field]
    element(app.checkbox, "تأكيد حذف الخطوة").check().run()
    element(app.button, "حذف الخطوة نهائيًا").click().run()
    healthy(app)
    assert store.read(owner)[0]["tasks"][0]["subtasks"] == [before["subtasks"][1]]
    element(app.checkbox, "تأكيد حذف الخطوة").check().run()
    element(app.button, "حذف الخطوة نهائيًا").click().run()
    healthy(app)
    assert store.read(owner)[0]["tasks"][0]["subtasks"] == []
    assert any(c.value == "لا توجد خطوات فرعية بعد." for c in app.caption)
    element(app.text_input, "إضافة خطوة فرعية").set_value("خطوة بديلة")
    element(app.button, "إضافة الخطوة").click().run()
    healthy(app)
    assert store.read(owner)[0]["tasks"][0]["subtasks"][0]["text"] == "خطوة بديلة"


def test_blank_and_stale_step_edits_do_not_overwrite_work(workspace, monkeypatch):
    store, owner = workspace
    seed_task(store, owner)
    app = dialog(store, owner, monkeypatch)
    original = store.read(owner)[0]["tasks"][0]
    element(app.text_input, "نص الخطوة").set_value("   ")
    element(app.button, "حفظ الخطوة").click().run()
    assert [e.value for e in app.error] == ["اكتب نص الخطوة قبل الحفظ."]
    assert store.read(owner)[0]["tasks"][0] == original
    app.session_state["frozen_record"] = original
    latest = copy.deepcopy(original)
    latest["subtasks"][1]["text"] = "تعديل زميل بالتزامن"
    store.put(owner, "tasks", latest, original["version"])
    element(app.text_input, "نص الخطوة").set_value("تعديل من نسخة قديمة")
    element(app.button, "حفظ الخطوة").click().run()
    assert any("عدّل شخص آخر" in e.value for e in app.error)
    assert store.read(owner)[0]["tasks"][0]["subtasks"] == latest["subtasks"]
    element(app.checkbox, "تأكيد حذف الخطوة").check().run()
    element(app.button, "حذف الخطوة نهائيًا").click().run()
    assert any("عدّل شخص آخر" in e.value for e in app.error)
    assert store.read(owner)[0]["tasks"][0]["subtasks"] == latest["subtasks"]


def test_task_delete_requires_confirmation_and_preserves_attached_files(workspace, monkeypatch):
    store, owner = workspace
    seed_task(store, owner)
    app = dialog(store, owner, monkeypatch)
    assert element(app.button, "حذف المهمة نهائيًا").disabled
    element(app.checkbox, "تأكيد حذف هذه المهمة").check().run()
    assert not element(app.button, "حذف المهمة نهائيًا").disabled
    element(app.button, "حذف المهمة نهائيًا").click().run()
    healthy(app)
    state = store.read(owner)[0]
    assert not state["tasks"]
    assert state["files"][0]["id"] == "attached"


@pytest.mark.parametrize("role,edit", [("manager", False), ("member", False), ("viewer", False), ("agent", False), ("agent", True)])
def test_subtask_actions_follow_existing_permissions(workspace, monkeypatch, role, edit):
    store, owner = workspace
    seed_task(store, owner)
    _, token = make_user(store, owner, role, edit)
    app = dialog(store, token, monkeypatch)
    editable = role in ("member", "manager") or role == "agent" and edit
    assert any(b.label == "حفظ الخطوة" for b in app.button) == editable
    assert any(b.label == "حذف الخطوة نهائيًا" for b in app.button) == editable
    assert element(app.checkbox, "الخطوة الأولى").disabled == (not editable)
    assert any(b.label == "حذف المهمة نهائيًا" for b in app.button) == (role == "manager")
    if role != "manager":
        with pytest.raises(Forbidden):
            store.remove(token, "tasks", "actions", 1)
    if not editable:
        modified = copy.deepcopy(store.read(owner)[0]["tasks"][0])
        modified["subtasks"] = []
        with pytest.raises(Forbidden):
            store.put(token, "tasks", modified, modified["version"])


def test_step_changes_reopen_details_in_the_full_app(workspace, monkeypatch):
    store, owner = workspace
    seed_task(store, owner)
    monkeypatch.setenv("DATABASE_URL", str(store.engine.url))
    monkeypatch.setenv("GDAY_LOCAL_MODE", "true")
    app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py"), default_timeout=20)
    app.session_state["token"] = owner
    app.session_state["navigation"] = "المهام"
    app.session_state["search_target"] = ("tasks", "actions")
    app.run()
    healthy(app)
    # AppTest reruns the whole script instead of the dialog fragment; mount it
    # for the incoming widget event. The mutation must then reopen it itself.
    app.session_state["search_target"] = ("tasks", "actions")
    element(app.checkbox, "الخطوة الثانية").check().run()
    healthy(app)
    assert element(app.text_input, "عنوان المهمة").value == "متابعة العمل"
    assert element(app.checkbox, "الخطوة الثانية").value is True
    app.session_state["search_target"] = ("tasks", "actions")
    element(app.checkbox, "تأكيد حذف الخطوة").check().run()
    app.session_state["search_target"] = ("tasks", "actions")
    element(app.button, "حذف الخطوة نهائيًا").click().run()
    healthy(app)
    assert element(app.text_input, "عنوان المهمة").value == "متابعة العمل"
    assert not any(c.label == "الخطوة الأولى" for c in app.checkbox)
    assert element(app.checkbox, "الخطوة الثانية").value is True
