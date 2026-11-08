import copy
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from tests.test_task_actions import seed_task
from tests.test_ui import element, healthy
from tests.test_workspace import workspace, make_user, task


def platform(store, token, monkeypatch, view="الجدول"):
    monkeypatch.setenv("DATABASE_URL", str(store.engine.url))
    monkeypatch.setenv("GDAY_LOCAL_MODE", "true")
    app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py"), default_timeout=20)
    app.session_state["token"] = token
    app.session_state["navigation"] = "نظرة اليوم" if view == "نظرة اليوم" else "المهام"
    app.run()
    if view == "لوحة الإنجاز":
        element(app.radio, "طريقة العرض").set_value(view).run()
    healthy(app)
    return app


@pytest.mark.parametrize("view,button_key", [("نظرة اليوم", "focus_actions"), ("الجدول", "edit_selected_task"), ("لوحة الإنجاز", "board_actions")])
def test_clear_edit_shortcut_opens_and_saves_the_existing_task(workspace, monkeypatch, view, button_key):
    store, owner = workspace
    seed_task(store, owner)
    before = store.read(owner)[0]["tasks"][0]
    app = platform(store, owner, monkeypatch, view)
    assert app.button(key=button_key).label == "تعديل المهمة"
    assert any(button.label == "حذف المهمة نهائيًا" and button.disabled for button in app.button)
    app.button(key=button_key).click().run()
    healthy(app)
    assert element(app.text_input, "عنوان المهمة").value == before["title"]
    # AppTest reruns whole scripts rather than dialog fragments for form events.
    app.session_state["search_target"] = ("tasks", "actions")
    element(app.text_input, "عنوان المهمة").set_value("المهمة بعد تعديل عنوانها")
    element(app.button, "حفظ المهمة").click().run()
    healthy(app)
    after = store.read(owner)[0]["tasks"][0]
    assert after["title"] == "المهمة بعد تعديل عنوانها"
    if view == "الجدول":
        assert app.dataframe[0].value.iloc[0]["المهمة"] == after["title"]
    for field in ("subtasks", "comments", "attachedFileId", "dueDate", "dueTime", "reminderEnabled", "reminderMinutes"):
        assert after[field] == before[field]


def test_table_deletes_only_the_selected_task_and_recovers_selection(workspace, monkeypatch):
    store, owner = workspace
    seed_task(store, owner)
    store.put(owner, "tasks", task("second") | {"title": "مهمة أخرى للحذف"})
    app = platform(store, owner, monkeypatch)
    app.selectbox(key="task_action_choice").set_value("second").run()
    healthy(app)
    assert app.button(key="remove_task_table_second_1").disabled
    app.checkbox(key="confirm_task_table_second_1").check().run()
    app.button(key="remove_task_table_second_1").click().run()
    healthy(app)
    state = store.read(owner)[0]
    assert [t["id"] for t in state["tasks"]] == ["actions"]
    assert state["tasks"][0]["comments"] and state["tasks"][0]["subtasks"]
    assert state["files"][0]["id"] == "attached"
    assert app.selectbox(key="task_action_choice").value == "actions"


@pytest.mark.parametrize("role,edit", [("manager", False), ("member", False), ("viewer", False), ("agent", False), ("agent", True)])
def test_shortcuts_show_task_permissions_clearly(workspace, monkeypatch, role, edit):
    store, owner = workspace
    seed_task(store, owner)
    _, token = make_user(store, owner, role, edit)
    app = platform(store, token, monkeypatch)
    editable = role in ("member", "manager") or edit
    assert app.button(key="edit_selected_task").label == ("تعديل المهمة" if editable else "عرض المهمة")
    if role != "manager":
        assert app.button(key="task_delete_disabled_table").disabled
        assert not any(b.label == "حذف المهمة نهائيًا" for b in app.button)
    else:
        assert app.button(key="remove_task_table_actions_1").disabled


def test_delete_shortcut_rejects_a_stale_task_confirmation(workspace, monkeypatch):
    store, owner = workspace
    seed_task(store, owner)
    original = store.read(owner)[0]["tasks"][0]
    monkeypatch.setenv("DATABASE_URL", str(store.engine.url))
    source = '''
import os
import streamlit as st
from workspace import Store
from components import task_delete_control
store = Store(os.environ['DATABASE_URL'])
token = st.session_state['token']
task_delete_control(store, token, store.actor(token), st.session_state['original'], key='stale')
'''
    app = AppTest.from_string(source, default_timeout=20)
    app.session_state["token"] = owner
    app.session_state["original"] = original
    app.run()
    changed = copy.deepcopy(original)
    changed["title"] = "عنوان أحدث من زميل"
    store.put(owner, "tasks", changed, original["version"])
    element(app.checkbox, "تأكيد حذف هذه المهمة").check().run()
    element(app.button, "حذف المهمة نهائيًا").click().run()
    assert any("السجل تغير أو حُذف" in e.value for e in app.error)
    assert store.read(owner)[0]["tasks"][0]["title"] == changed["title"]
