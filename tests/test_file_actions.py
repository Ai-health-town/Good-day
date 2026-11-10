import json

import pytest
from sqlalchemy import select
from streamlit.testing.v1 import AppTest

from filetools import parse_upload
from tests.test_ui import element, healthy
from tests.test_workspace import workspace, make_user, task
from workspace import Forbidden, Store, snapshots


def seed(store, token):
    record = parse_upload("سابق.txt", "الأصل محفوظ".encode(), "p_general")
    record["id"] = "uploaded-before"
    store.add_files(token, [record])
    store.put(token, "tasks", task("linked-task") | {"attachedFileId": record["id"]})
    store.put(token, "messages", {"id": "linked-message", "text": "مرفق", "projectId": "p_general", "fileId": record["id"]})
    return store.read(token)[0]["files"][0]


def file_dialog(store, token, monkeypatch, mode="معاينة الأصل", frozen=None):
    monkeypatch.setenv("DATABASE_URL", str(store.engine.url))
    app = AppTest.from_string('''
import os
import streamlit as st
from workspace import Store
from components import edit_file
store = Store(os.environ['DATABASE_URL'])
token = st.session_state['test_token']
state, _, actor = store.context(token)
if state['files']:
    edit_file(store, token, state, actor, st.session_state.get('frozen', state['files'][0]))
else:
    st.info('المكتبة فارغة')
''', default_timeout=20)
    app.session_state["test_token"] = token
    app.session_state["file_mode_uploaded-before"] = mode
    if frozen is not None:
        app.session_state["frozen"] = frozen
    app.run()
    healthy(app)
    return app


@pytest.mark.parametrize("mode", ["معاينة الأصل", "نسخة العمل", "التعليقات"])
@pytest.mark.parametrize("role", ["manager", "file_manager"])
def test_manager_can_delete_an_existing_upload_from_every_file_mode(workspace, monkeypatch, mode, role):
    store, owner = workspace
    seed(store, owner)
    _, manager = make_user(store, owner, role)
    before = store.read(owner)[0]
    app = file_dialog(store, manager, monkeypatch, mode)
    assert element(app.button, "حذف الملف من المكتبة").disabled
    element(app.checkbox, "تأكيد حذف الملف").check().run()
    element(app.button, "حذف الملف من المكتبة").click().run()
    healthy(app)
    after = store.read(owner)[0]
    assert not after["files"]
    assert after["tasks"][0]["attachedFileId"] == ""
    assert after["messages"][0]["fileId"] == ""
    assert after["tasks"][0]["title"] == before["tasks"][0]["title"]
    with store.engine.connect() as conn:
        saved = conn.execute(select(snapshots.c.payload)).scalar_one()
    assert json.loads(saved) == before


@pytest.mark.parametrize("role,edit", [("member", False), ("viewer", False), ("agent", True)])
def test_file_delete_does_not_expand_unrelated_account_permissions(workspace, monkeypatch, role, edit):
    store, owner = workspace
    record = seed(store, owner)
    _, token = make_user(store, owner, role, edit)
    app = file_dialog(store, token, monkeypatch)
    assert not any(b.label == "حذف الملف من المكتبة" for b in app.button)
    with pytest.raises(Forbidden):
        store.remove(token, "files", record["id"], record["version"])
    assert len(store.read(owner)[0]["files"]) == 1
    assert not store.list_snapshots(owner)


def test_file_manager_has_member_editing_and_file_deletion_only(workspace):
    store, owner = workspace
    record = seed(store, owner)
    ident, token = make_user(store, owner, "file_manager")
    assert store.can_edit(store.actor(token))
    store.put(token, "tasks", task("member-task"))
    store.put(token, "messages", {"id": "own-message", "text": "رسالتي", "projectId": "p_general"})
    store.remove(token, "messages", "own-message", 1)
    for collection, target in [("tasks", "linked-task"), ("projects", "p_general"), ("messages", "linked-message")]:
        with pytest.raises(Forbidden): store.remove(token, collection, target, 1)
    for permission in ("manage", "admin"):
        with pytest.raises(Forbidden): store.require(store.actor(token), permission)
    with pytest.raises(Forbidden): store.activity(token)
    with pytest.raises(Forbidden): store.list_users(token)
    # A live permission check prevents deletion from an already-open dialog.
    from sqlalchemy import update
    from workspace import users
    with store.engine.begin() as conn:
        conn.execute(update(users).where(users.c.id == ident).values(role="member"))
    with pytest.raises(Forbidden): store.remove(token, "files", record["id"], record["version"])
    assert len(store.read(owner)[0]["files"]) == 1


def test_stale_file_deletion_keeps_the_latest_file_and_does_not_create_a_snapshot(workspace, monkeypatch):
    store, owner = workspace
    original = seed(store, owner)
    app = file_dialog(store, owner, monkeypatch, frozen=original)
    store.put(owner, "files", original | {"title": "تعديل أحدث"}, original["version"])
    element(app.checkbox, "تأكيد حذف الملف").check().run()
    element(app.button, "حذف الملف من المكتبة").click().run()
    assert any("السجل تغير" in e.value for e in app.error)
    assert store.read(owner)[0]["files"][0]["title"] == "تعديل أحدث"
    assert not store.list_snapshots(owner)


@pytest.mark.parametrize("mode", ["نسخة العمل", "التعليقات"])
def test_text_editing_and_comments_do_not_download_the_original(workspace, monkeypatch, mode):
    store, owner = workspace
    seed(store, owner)
    def fail(*args, **kwargs):
        raise AssertionError("Opening comments/text does not need the original bytes")
    monkeypatch.setattr(Store, "file_bytes", fail)
    app = file_dialog(store, owner, monkeypatch, mode)
    healthy(app)
    assert any(b.label == "تنزيل الملف الأصلي" for b in app.get("download_button"))
