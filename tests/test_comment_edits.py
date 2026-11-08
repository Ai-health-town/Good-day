import copy
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from tests.test_task_actions import seed_task
from tests.test_ui import element, healthy
from tests.test_workspace import workspace, make_user


def seed_comments(store, token, collection):
    seed_task(store, token)
    record = store.read(token)[0][collection][0]
    record["comments"] = [
        {"id": "first", "text": "التعليق الأول", "authorId": store.actor(token)["member_id"], "time": "2026-11-08T08:00:00+03:00"},
        {"text": "تعليق من نسخة قديمة", "authorId": "former_member", "time": "2026-11-05T09:00:00+03:00", "source": "legacy"},
    ]
    store.put(token, collection, record, record["version"])
    return store.read(token)[0][collection][0]


def comments_app(store, token, collection, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", str(store.engine.url))
    source = '''
import os
import streamlit as st
from workspace import Store
from components import edit_task, edit_file
store = Store(os.environ['DATABASE_URL'])
token = st.session_state['token']
state, _, actor = store.context(token)
collection = st.session_state['collection']
record = st.session_state.get('frozen_record', state[collection][0])
if collection == 'tasks':
    edit_task(store, token, state, actor, record)
else:
    edit_file(store, token, state, actor, record)
'''
    app = AppTest.from_string(source, default_timeout=20)
    app.session_state["token"] = token
    app.session_state["collection"] = collection
    if collection == "files":
        app.session_state["file_mode_attached"] = "التعليقات"
    app.run()
    healthy(app)
    return app


@pytest.mark.parametrize("collection", ["tasks", "files"])
def test_comment_edit_preserves_authorship_other_comments_and_content(workspace, monkeypatch, collection):
    store, owner = workspace
    before = seed_comments(store, owner, collection)
    app = comments_app(store, owner, collection, monkeypatch)
    # Older backups need not have a comment id; edit the selected comment only.
    [w for w in app.text_area if w.label == "نص التعليق"][1].set_value("تعليق قديم بعد التصحيح")
    [b for b in app.button if b.label == "حفظ تعديل التعليق"][1].click().run()
    healthy(app)
    changed = store.read(owner)[0][collection][0]
    assert changed["comments"][0] == before["comments"][0]
    assert changed["comments"][1] == before["comments"][1] | {
        "text": "تعليق قديم بعد التصحيح", "editedAt": changed["comments"][1]["editedAt"],
        "editedBy": store.actor(owner)["member_id"],
    }
    assert changed["comments"][1]["editedAt"]
    assert any("مُعدّل" in c.value for c in app.caption)
    for field in before.keys() - {"comments", "version", "updatedAt", "updatedBy"}:
        assert changed[field] == before[field]


@pytest.mark.parametrize("collection", ["tasks", "files"])
def test_blank_and_stale_comment_edits_cannot_overwrite_a_record(workspace, monkeypatch, collection):
    store, owner = workspace
    before = seed_comments(store, owner, collection)
    app = comments_app(store, owner, collection, monkeypatch)
    element(app.text_area, "نص التعليق").set_value("  ")
    element(app.button, "حفظ تعديل التعليق").click().run()
    assert [e.value for e in app.error] == ["اكتب نص التعليق قبل الحفظ."]
    assert store.read(owner)[0][collection][0] == before
    app.session_state["frozen_record"] = before
    latest = copy.deepcopy(before)
    latest["comments"][1]["text"] = "تعديل زميل أحدث"
    store.put(owner, collection, latest, before["version"])
    element(app.text_area, "نص التعليق").set_value("تصحيح من نسخة قديمة")
    element(app.button, "حفظ تعديل التعليق").click().run()
    assert any("عدّل شخص آخر" in e.value for e in app.error)
    assert store.read(owner)[0][collection][0]["comments"] == latest["comments"]


@pytest.mark.parametrize("role,edit", [("viewer", False), ("agent", False), ("member", False), ("agent", True)])
def test_comment_edit_controls_follow_record_edit_permissions(workspace, monkeypatch, role, edit):
    store, owner = workspace
    seed_comments(store, owner, "tasks")
    _, token = make_user(store, owner, role, edit)
    app = comments_app(store, token, "tasks", monkeypatch)
    assert any(b.label == "حفظ تعديل التعليق" for b in app.button) == (role == "member" or edit)


@pytest.mark.parametrize("collection", ["tasks", "files"])
def test_comment_edit_reopens_the_same_details_in_the_full_app(workspace, monkeypatch, collection):
    store, owner = workspace
    record = seed_comments(store, owner, collection)
    monkeypatch.setenv("DATABASE_URL", str(store.engine.url))
    monkeypatch.setenv("GDAY_LOCAL_MODE", "true")
    app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py"), default_timeout=20)
    app.session_state["token"] = owner
    app.session_state["navigation"] = "المهام" if collection == "tasks" else "الملفات"
    app.session_state["search_target"] = (collection, record["id"])
    if collection == "files":
        app.session_state["file_mode_attached"] = "التعليقات"
    app.run()
    healthy(app)
    # AppTest uses whole-script reruns instead of dialog-fragment reruns.
    app.session_state["search_target"] = (collection, record["id"])
    element(app.text_area, "نص التعليق").set_value("تعليق مصحح من المنصة")
    element(app.button, "حفظ تعديل التعليق").click().run()
    healthy(app)
    assert any(t.value == "تعليق مصحح من المنصة" for t in app.text)
    assert any(b.label == "حفظ تعديل التعليق" for b in app.button)
    if collection == "files":
        assert app.session_state["file_mode_attached"] == "التعليقات"
