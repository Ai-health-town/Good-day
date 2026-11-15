import copy
import json
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from filetools import parse_upload
from foldertools import prepare_uploads, validate_filing, folder_labels
from workspace import Conflict, Forbidden, Store, WorkspaceError, prepare_import, uid
from tests.test_workspace import workspace
from tests.test_ui import element, healthy


def add_folder(store, token, ident="dir1", name="متابعة", parent="", project="p_general"):
    return store.put(token, "folders", {"id": ident, "name": name, "parentId": parent, "projectId": project})


def test_directory_upload_preserves_tree_originals_and_same_names_in_different_folders(workspace):
    store, token = workspace
    add_folder(store, token)
    records, ignored = prepare_uploads([
        ("مشروع/صباح/تقرير.txt", "بيانات صباحية".encode()),
        ("مشروع/مساء/تقرير.txt", "بيانات مسائية".encode()),
        ("مشروع/مرفق.png", b"synthetic-original-image-bytes"),
        ("مشروع/.DS_Store", b"operating-system-metadata"),
    ], "p_general", directory=True)
    assert ignored == 1
    report = store.add_files(token, records, folder_id="dir1", deduplicate=True)
    assert report == {"added": 3, "skipped": 0, "folders_added": 3}
    state, revision = store.read(token)
    validate_filing(state)
    paths = folder_labels(state["folders"])
    assert {paths[f["folderId"]] for f in state["files"]} == {"متابعة / مشروع / صباح", "متابعة / مشروع / مساء", "متابعة / مشروع"}
    assert sorted(f["title"] for f in state["files"]) == ["تقرير.txt", "تقرير.txt", "مرفق.png"]
    assert all("uploadPath" not in f for f in state["files"])
    for record, (_, raw) in zip(state["files"], [
        ("", "بيانات صباحية".encode()), ("", "بيانات مسائية".encode()), ("", b"synthetic-original-image-bytes")]):
        assert store.file_bytes(token, record["id"]) == raw
    assert state["files"][-1]["type"] == "attachment"
    again = store.add_files(token, [r | {"id": uid("f_")} for r in records], folder_id="dir1", deduplicate=True)
    assert again == {"added": 0, "skipped": 3, "folders_added": 0}
    assert store.read(token)[1] == revision
    changed, _ = prepare_uploads([("مشروع/صباح/تقرير.txt", b"updated-content")], "p_general", directory=True)
    assert store.add_files(token, changed, folder_id="dir1", deduplicate=True)["added"] == 1


@pytest.mark.parametrize("path", ["../secret.txt", "/absolute.txt", "C:\\secret.txt", "folder/../secret.txt", "folder//file.txt", "folder/\x00file.txt", "/".join(["deep"] * 13 + ["a.txt"])])
def test_untrusted_directory_paths_are_rejected(path):
    with pytest.raises(WorkspaceError):
        prepare_uploads([(path, b"sample")], "p_general", directory=True)


def test_folder_batch_failure_leaves_no_partial_files_folders_or_revision(workspace):
    store, token = workspace
    records, _ = prepare_uploads([("root/good.txt", b"ok")], "p_general", directory=True)
    records += [parse_upload("other.txt", b"bad project", "deleted-project")]
    before = store.read(token)
    with pytest.raises(WorkspaceError):
        store.add_files(token, records, deduplicate=True)
    assert store.read(token) == before
    with pytest.raises(WorkspaceError, match="200"):
        prepare_uploads(((f"f{i}.txt", b"x") for i in range(201)), "p_general")


def test_existing_file_can_move_and_rename_without_touching_original_or_links(workspace):
    store, token = workspace
    add_folder(store, token)
    source = parse_upload("تقرير.txt", b"unchanged original", "p_general")
    store.add_files(token, [source])
    record = store.read(token)[0]["files"][0]
    store.put(token, "files", record | {"folderId": "dir1"}, record["version"])
    assert store.file_bytes(token, record["id"]) == b"unchanged original"
    folder = store.read(token)[0]["folders"][0]
    store.put(token, "folders", folder | {"name": "تقارير المشروع"}, folder["version"])
    assert store.read(token)[0]["files"][0]["folderId"] == "dir1"
    with pytest.raises(Conflict):
        store.put(token, "folders", folder | {"name": "نسخة قديمة"}, folder["version"])
    with pytest.raises(WorkspaceError, match="الفارغ"):
        store.remove(token, "folders", "dir1", folder["version"] + 1)
    current = store.read(token)[0]["files"][0]
    store.put(token, "files", current | {"folderId": ""}, current["version"])
    store.remove(token, "folders", "dir1", folder["version"] + 1)
    assert store.file_bytes(token, record["id"]) == b"unchanged original"


def test_folder_validation_rejects_cycles_duplicate_names_and_cross_project_filing(workspace):
    store, token = workspace
    add_folder(store, token)
    add_folder(store, token, "child", "فرعي", "dir1")
    with pytest.raises(WorkspaceError):
        add_folder(store, token, "duplicate", " متابعة ")
    parent = store.read(token)[0]["folders"][0]
    with pytest.raises(WorkspaceError):
        store.put(token, "folders", parent | {"parentId": "child"}, parent["version"])
    store.put(token, "projects", {"id": "p2", "name": "آخر"})
    with pytest.raises(WorkspaceError):
        add_folder(store, token, "foreign", "فرعي", "dir1", "p2")
    record = parse_upload("wrong.txt", b"raw", "p2") | {"folderId": "dir1"}
    with pytest.raises(WorkspaceError):
        store.put(token, "files", record)


def test_folder_permissions_are_live_and_do_not_expand_member_access(workspace):
    store, owner = workspace
    ident = store.create_user(owner, "folder_reader", "قارئ", "Folder-reader-password-123!", "viewer")
    reader = store.login("folder_reader", "Folder-reader-password-123!")
    with pytest.raises(Forbidden):
        add_folder(store, reader)
    with pytest.raises(Forbidden):
        store.add_files(reader, [parse_upload("a.txt", b"sample", "p_general")])
    store.update_user(owner, ident, "member", True, False)
    reader = store.login("folder_reader", "Folder-reader-password-123!")
    add_folder(store, reader)
    store.add_files(reader, [parse_upload("a.txt", b"sample", "p_general")], folder_id="dir1")
    with pytest.raises(Forbidden):
        store.remove(reader, "folders", "dir1", 1)
    store.update_user(owner, ident, "viewer", True, False)
    with pytest.raises(Forbidden):
        add_folder(store, reader, "another")


def test_folder_backup_restore_additive_merge_and_legacy_backup_compatibility(workspace):
    store, token = workspace
    add_folder(store, token)
    records, _ = prepare_uploads([("المشروع/فرعي/a.txt", b"original"),
                                  ("المشروع/فرعي/b.txt", b"original")], "p_general", directory=True)
    store.add_files(token, records, folder_id="dir1")
    state, _ = store.read(token)
    backup = Store.backup_bytes(state)
    assert prepare_import(backup)["data"]["folders"]
    # Folder order in a JSON backup need not put parents first.
    content = json.loads(backup)
    content["data"]["folders"].reverse()
    reverse = json.dumps(content, ensure_ascii=False).encode()
    from migration import build_merge
    additions, report = build_merge(reverse, state, "p_general")
    assert not any(additions.values())
    empty = copy.deepcopy(state)
    empty["files"], empty["folders"] = [], []
    additions, _ = build_merge(reverse, empty, "p_general")
    for collection, records in additions.items():
        empty[collection].extend(records)
    validate_filing(empty)
    assert len(empty["folders"]) == len(state["folders"])
    assert len(empty["files"]) == 2  # Distinct filenames survive even with identical bytes.
    assert empty["files"][0]["folderId"] != state["files"][0]["folderId"]
    store.restore(token, reverse, store.read(token)[1])
    restored = store.read(token)[0]
    validate_filing(restored)
    assert store.file_bytes(token, restored["files"][0]["id"]) == b"original"
    legacy = json.loads(Store.backup_bytes(empty))
    legacy["data"].pop("folders")
    legacy["data"]["files"] = []
    assert prepare_import(json.dumps(legacy).encode())["data"]["folders"] == []
    legacy["data"]["folders"] = [{"id": "bad", "name": "broken", "projectId": "p_general", "parentId": "missing"}]
    with pytest.raises(WorkspaceError):
        prepare_import(json.dumps(legacy).encode())


def test_project_move_and_delete_keep_folder_links_and_avoid_name_collisions(workspace):
    store, token = workspace
    store.put(token, "projects", {"id": "p2", "name": "آخر"})
    add_folder(store, token)
    add_folder(store, token, "other", "متابعة", project="p2")
    records, _ = prepare_uploads([("sub/a.txt", b"original")], "p_general", directory=True)
    store.add_files(token, records, folder_id="dir1")
    file_id = store.read(token)[0]["files"][0]["id"]
    store.move_project_contents(token, "p_general", "p2", store.read(token)[1])
    state = store.read(token)[0]
    validate_filing(state)
    assert {f["projectId"] for f in state["folders"]} == {"p2"}
    assert len({f["name"] for f in state["folders"] if not f.get("parentId")}) == 2
    store.remove(token, "projects", "p2", 1)
    validate_filing(store.read(token)[0])
    assert store.file_bytes(token, file_id) == b"original"


def test_upload_network_work_does_not_lock_workspace_or_lose_concurrent_changes(workspace):
    store, token = workspace
    other = Store(str(store.engine.url))

    class UploadWhileAnotherMemberWorks:
        def externalize(self, record):
            # Would fail with SQLite's database lock if network work occurred
            # inside Store.transaction(), just as other users' saves would wait.
            other.put(token, "stakeholders", {"id": "during_upload", "name": "تحديث أثناء الرفع"})
            return record

    store.storage = UploadWhileAnotherMemberWorks()
    store.add_files(token, [parse_upload("a.txt", b"content", "p_general")])
    state = store.read(token)[0]
    assert state["stakeholders"][0]["id"] == "during_upload"
    assert len(state["files"]) == 1


def test_upload_rechecks_session_after_network_transfer(workspace):
    store, owner = workspace
    ident = store.create_user(owner, "uploader", "عضو", "Upload-password-123!", "member")
    token = store.login("uploader", "Upload-password-123!")

    class RevokedDuringUpload:
        def externalize(self, record):
            store.update_user(owner, ident, "viewer", True, False)
            return record

    store.storage = RevokedDuringUpload()
    with pytest.raises(Forbidden):
        store.add_files(token, [parse_upload("a.txt", b"content", "p_general")])
    assert not store.read(owner)[0]["files"]


def dashboard(store, token, monkeypatch, page="الملفات"):
    monkeypatch.setenv("DATABASE_URL", str(store.engine.url))
    monkeypatch.setenv("GDAY_LOCAL_MODE", "true")
    app = AppTest.from_file(str(Path(__file__).parents[1] / "app.py"), default_timeout=25)
    app.session_state["token"] = token
    app.session_state["navigation"] = page
    app.run()
    healthy(app)
    return app


def test_folder_ui_create_navigate_rename_and_native_directory_upload(workspace, monkeypatch):
    store, token = workspace
    app = dashboard(store, token, monkeypatch)
    element(app.button, "مجلد جديد").click().run()
    healthy(app)
    assert element(app.text_input, "اسم المجلد")
    # AppTest simulates full script events, so keep native dialog fragments
    # mounted in a small harness while exercising their submit handlers.
    source = '''
import os
import streamlit as st
from app import new_folder_dialog, upload_dialog
from workspace import Store
store = Store(os.environ['DATABASE_URL'])
token = st.session_state['token']
state, _ = store.read(token)
if st.session_state.get('upload'):
    upload_dialog(store, token, state, state['folders'][0]['id'])
else:
    new_folder_dialog(store, token, state)
'''
    app = AppTest.from_string(source, default_timeout=20)
    app.session_state["token"] = token
    app.run()
    element(app.text_input, "اسم المجلد").set_value("مستندات المشروع")
    element(app.button, "إنشاء المجلد").click().run()
    healthy(app)
    folder = store.read(token)[0]["folders"][0]
    app = dashboard(store, token, monkeypatch)
    element(app.button, "مستندات المشروع").click().run()
    assert app.session_state["library_folder"] == folder["id"]
    element(app.text_input, "اسم المجلد").set_value("ملفات المتابعة")
    element(app.button, "حفظ اسم المجلد").click().run()
    healthy(app)
    assert store.read(token)[0]["folders"][0]["name"] == "ملفات المتابعة"
    element(app.button, "↑ رفع ملفات").click().run()
    healthy(app)
    app = AppTest.from_string(source, default_timeout=20)
    app.session_state["token"] = token
    app.session_state["upload"] = True
    app.run()
    element(app.radio, "طريقة الرفع").set_value("مجلد كامل").run()
    healthy(app)
    assert app.get("file_uploader")[0].proto.accept_directory
    assert app.get("file_uploader")[0].proto.max_upload_size_mb == 8
    assert element(app.selectbox, "المجلد").value == folder["id"]


def test_library_and_contacts_paging_reaches_all_results_and_resets_filtered_page(workspace, monkeypatch):
    store, token = workspace
    with store.transaction() as conn:
        state, revision = store._state(conn)
        state["files"] = [{"id": f"f{i}", "title": f"ملف {i:02d}", "type": "doc", "text": "sample", "projectId": "p_general"} for i in range(29)]
        state["stakeholders"] = [{"id": f"s{i}", "name": f"جهة {i:02d}", "projectId": "p_general"} for i in range(29)]
        store._save(conn, state, revision)
    app = dashboard(store, token, monkeypatch)
    assert len([b for b in app.button if b.label == "فتح الملف"]) == 12
    element(app.number_input, "الصفحة").set_value(3).run()
    assert len([b for b in app.button if b.label == "فتح الملف"]) == 5
    element(app.text_input, "بحث في الملفات").set_value("ملف 00").run()
    healthy(app)
    assert len([b for b in app.button if b.label == "فتح الملف"]) == 1
    app = dashboard(store, token, monkeypatch, "الجهات")
    assert len([b for b in app.button if b.label == "عرض وتعديل"]) == 12
    element(app.number_input, "الصفحة").set_value(3).run()
    assert len([b for b in app.button if b.label == "عرض وتعديل"]) == 5
    element(app.text_input, "بحث في دليل الجهات والأشخاص").set_value("جهة 00").run()
    healthy(app)
    assert len([b for b in app.button if b.label == "عرض وتعديل"]) == 1
