import copy
import io
from pathlib import Path

import pytest
from openpyxl import load_workbook
from streamlit.testing.v1 import AppTest

from ai_service import build_context
from contacttools import task_contact_ids, task_contact_names
from filetools import tasks_excel
from tests.test_ui import element, healthy
from tests.test_workspace import PASSWORD, make_user, task, workspace
from workspace import Conflict, Forbidden, Store, WorkspaceError, prepare_import


@pytest.fixture
def contacts(workspace):
    store, token = workspace
    for index, name in enumerate(["الجهة الأولى", "الجهة الثانية", "الجهة الثالثة"], 1):
        store.put(token, "stakeholders", {"id": "s" + str(index), "name": name, "org": "فريق المركز", "projectId": "p_general"})
    return store, token


def editor(store, token, monkeypatch, *, legacy=False):
    monkeypatch.setenv("DATABASE_URL", str(store.engine.url))
    source = '''
import os
import streamlit as st
from components import edit_task
from workspace import Store
store = Store(os.environ['DATABASE_URL'])
token = st.session_state['token']
state, _, actor = store.context(token)
record = next((r for r in state['tasks'] if r['id'] == 'linked'), None)
if record and st.session_state.get('legacy') and record.get('version') == 1:
    record.pop('stakeholderIds', None)
edit_task(store, token, state, actor, record)
'''
    app = AppTest.from_string(source, default_timeout=20)
    app.session_state["token"] = token
    app.session_state["legacy"] = legacy
    app.run()
    healthy(app)
    return app


@pytest.mark.parametrize("record, expected", [
    ({"stakeholderId": "s1"}, ["s1"]),
    ({}, []),
    ({"stakeholderId": "s1", "stakeholderIds": []}, []),
    ({"stakeholderId": "s1", "stakeholderIds": ["s2", "s3", "s2"]}, ["s2", "s3"]),
])
def test_legacy_and_explicit_contact_selections(record, expected):
    assert task_contact_ids(record) == expected


def test_existing_task_can_add_remove_and_clear_contacts_without_losing_details(contacts, monkeypatch):
    store, token = contacts
    store.put(token, "tasks", task("linked") | {"stakeholderId": "s1", "estimatedMinutes": 45,
        "dueTime": "19:30", "reminderEnabled": True, "reminderMinutes": 30, "notes": "ملاحظات محفوظة",
        "comments": [{"id": "c1", "text": "تعليق محفوظ"}], "subtasks": [{"id": "step", "text": "خطوة", "done": True}]})
    before = copy.deepcopy(store.read(token)[0]["tasks"][0])
    app = editor(store, token, monkeypatch, legacy=True)
    picker = element(app.multiselect, "الأشخاص وجهات التواصل")
    assert picker.value == ["s1"]
    picker.set_value(["s1", "s2", "s3"])
    element(app.button, "حفظ المهمة").click().run()
    healthy(app)
    saved = Store(str(store.engine.url)).read(token)[0]["tasks"][0]
    assert saved["stakeholderIds"] == ["s1", "s2", "s3"]
    assert saved["stakeholderId"] == "s1"
    for field in ("title", "notes", "comments", "subtasks", "dueDate", "dueTime", "reminderEnabled", "reminderMinutes", "estimatedMinutes"):
        assert saved[field] == before[field]
    element(app.multiselect, "الأشخاص وجهات التواصل").set_value(["s2", "s3"])
    element(app.button, "حفظ المهمة").click().run()
    healthy(app)
    assert store.read(token)[0]["tasks"][0]["stakeholderId"] == "s2"
    element(app.multiselect, "الأشخاص وجهات التواصل").set_value([])
    element(app.button, "حفظ المهمة").click().run()
    healthy(app)
    saved = store.read(token)[0]["tasks"][0]
    assert saved["stakeholderIds"] == [] and saved["stakeholderId"] == ""


def test_new_task_accepts_multiple_contacts(contacts, monkeypatch):
    store, token = contacts
    app = editor(store, token, monkeypatch)
    element(app.text_input, "عنوان المهمة").set_value("متابعة جهتين")
    element(app.multiselect, "الأشخاص وجهات التواصل").set_value(["s2", "s1"])
    element(app.button, "حفظ المهمة").click().run()
    healthy(app)
    saved = store.read(token)[0]["tasks"][0]
    assert saved["stakeholderIds"] == ["s2", "s1"] and saved["stakeholderId"] == "s2"


@pytest.mark.parametrize("selected", [None, "s1", {}, [None], [1], [["s1"]], [""], ["x" * 161], ["missing"]])
def test_invalid_or_deleted_contact_cannot_be_saved(contacts, selected):
    store, token = contacts
    store.put(token, "tasks", task("linked") | {"stakeholderIds": ["s1"]})
    before, revision = store.read(token)
    modified = before["tasks"][0] | {"stakeholderIds": selected, "title": "تعديل لا يُحفظ"}
    with pytest.raises(WorkspaceError):
        store.put(token, "tasks", modified, modified["version"])
    assert store.read(token) == (before, revision)


def test_deleting_a_contact_removes_only_its_links_and_protects_stale_forms(contacts):
    store, token = contacts
    store.put(token, "tasks", task("linked") | {"stakeholderIds": ["s1", "s2", "s3"]})
    frozen = store.read(token)[0]["tasks"][0]
    store.remove(token, "stakeholders", "s2", 1)
    saved = store.read(token)[0]["tasks"][0]
    assert saved["stakeholderIds"] == ["s1", "s3"] and saved["stakeholderId"] == "s1"
    with pytest.raises(Conflict): store.put(token, "tasks", frozen, frozen["version"])
    store.remove(token, "stakeholders", "s1", 1)
    saved = store.read(token)[0]["tasks"][0]
    assert saved["stakeholderIds"] == ["s3"] and saved["stakeholderId"] == "s3"
    store.remove(token, "stakeholders", "s3", 1)
    saved = store.read(token)[0]["tasks"][0]
    assert saved["stakeholderIds"] == [] and saved["stakeholderId"] == ""


def test_all_contacts_appear_in_search_table_export_and_assistant_context(contacts, monkeypatch):
    store, token = contacts
    store.put(token, "tasks", task("linked") | {"stakeholderIds": ["s1", "s2"], "title": "متابعة الاختبار"})
    state, _ = store.read(token)
    assert task_contact_names(state["tasks"][0], state["stakeholders"]) == "الجهة الأولى، الجهة الثانية"
    exported = load_workbook(io.BytesIO(tasks_excel(state)), read_only=True, data_only=True)
    assert exported.active.cell(2, 10).value == "الجهة الأولى، الجهة الثانية"
    context, _, _ = build_context(store, token, state, "p_general", [], "لخص المتابعة")
    assert context["tasks"][0]["stakeholderIds"] == ["s1", "s2"]
    assert context["tasks"][0]["stakeholderNames"] == "الجهة الأولى، الجهة الثانية"
    monkeypatch.setenv("DATABASE_URL", str(store.engine.url))
    monkeypatch.setenv("GDAY_LOCAL_MODE", "true")
    app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py"), default_timeout=20)
    app.session_state["token"] = token
    app.session_state["navigation"] = "المهام"
    app.run()
    healthy(app)
    element(app.text_input, "ابحث في المهام").set_value("الجهة الثانية").run()
    healthy(app)
    assert app.dataframe[0].value.iloc[0]["المهمة"] == "متابعة الاختبار"
    assert app.dataframe[0].value.iloc[0]["جهة التواصل"] == "الجهة الأولى، الجهة الثانية"


def test_backup_restore_and_additive_merge_keep_every_contact_link(contacts, tmp_path):
    store, token = contacts
    store.put(token, "tasks", task("linked") | {"stakeholderIds": ["s1", "s2", "s3"]})
    state, revision = store.read(token)
    raw = store.backup_bytes(state)
    assert prepare_import(raw)["data"]["tasks"][0]["stakeholderIds"] == ["s1", "s2", "s3"]
    store.restore(token, raw, revision)
    assert store.read(token)[0]["tasks"][0]["stakeholderIds"] == ["s1", "s2", "s3"]
    target = Store("sqlite:///" + str(tmp_path / "target.db"))
    target.bootstrap("owner", PASSWORD)
    owner = target.login("owner", PASSWORD)
    target.put(owner, "stakeholders", {"id": "already_here", "name": "الجهة الأولى", "org": "فريق المركز"})
    target.merge_workspace(owner, raw, "p_general", target.read(owner)[1])
    imported, revision = target.read(owner)
    linked = imported["tasks"][0]
    assert len(linked["stakeholderIds"]) == 3
    assert linked["stakeholderId"] == "already_here"
    assert task_contact_names(linked, imported["stakeholders"]) == "الجهة الأولى، الجهة الثانية، الجهة الثالثة"
    target.merge_workspace(owner, raw, "p_general", revision)
    assert len(target.read(owner)[0]["tasks"]) == 1


@pytest.mark.parametrize("role", ["viewer", "agent"])
def test_contact_picker_preserves_existing_edit_permissions(contacts, monkeypatch, role):
    store, owner = contacts
    store.put(owner, "tasks", task("linked") | {"stakeholderIds": ["s1", "s2"]})
    _, token = make_user(store, owner, role, edit=False)
    app = editor(store, token, monkeypatch)
    assert element(app.multiselect, "الأشخاص وجهات التواصل").disabled
    assert element(app.button, "حفظ المهمة").disabled
    saved = store.read(owner)[0]["tasks"][0]
    with pytest.raises(Forbidden): store.put(token, "tasks", saved | {"stakeholderIds": []}, saved["version"])
