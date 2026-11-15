import base64
import copy

import pytest
from sqlalchemy import update

from filetools import parse_upload
from foldertools import prepare_uploads
from workspace import Forbidden, Store, users
from tests.test_workspace import workspace, task, PASSWORD, make_user
from tests.test_ui import element, healthy
from tests.test_file_actions import seed, file_dialog, make_abdullah
from tests.test_folders import dashboard
from tests.test_assistant_desk import desk
from tests.test_file_preview import workbook_bytes


def test_resource_reload_uses_current_store_class_and_preserves_resource_reuse(tmp_path, monkeypatch):
    import app as app_module
    import cloud_storage

    monkeypatch.setattr(cloud_storage, "storage_from_settings", lambda _: (None, ""))
    # Simulate an earlier imported class retained in a cached callable's globals.
    class EarlierStore:
        def __init__(self, url):
            raise AssertionError("The resource used a stale Store class")

    class CurrentStore(Store):
        pass

    class ReloadedStore(Store):
        pass

    monkeypatch.setattr(app_module, "Store", EarlierStore)
    url = "sqlite:///" + str(tmp_path / "resource_reload.db")
    first = app_module.open_store(url, id(CurrentStore), CurrentStore)
    assert isinstance(first, CurrentStore)
    assert app_module.open_store(url, id(CurrentStore), CurrentStore) is first
    reloaded = app_module.open_store(url, id(ReloadedStore), ReloadedStore)
    assert isinstance(reloaded, ReloadedStore) and reloaded is not first
    assert hasattr(reloaded, "can_manage_library")
    assert not reloaded.can_manage_library({"role": "manager", "username": "supervisor"})
    assert reloaded.can_manage_library({"role": "file_manager", "username": "abdullah"})


@pytest.mark.parametrize("field,value", [
    ("title", "اسم مختلف"), ("projectId", "another-project"), ("folderId", "another-folder"),
    ("starred", True), ("type", "pdf"), ("originalName", "replacement.pdf"),
    ("blob", base64.b64encode(b"replacement").decode()), ("object", {"key": "different-object"}),
    ("size", 999), ("imageInfo", {"width": 1}), ("customMetadata", "forged"),
])
def test_supervisor_cannot_change_original_or_library_metadata_on_server(workspace, field, value):
    store, owner = workspace
    original = seed(store, owner)
    _, supervisor = make_user(store, owner, "manager")
    before = store.read(owner)
    with pytest.raises(Forbidden):
        store.put(supervisor, "files", original | {field: value}, original["version"])
    assert store.read(owner) == before
    assert not store.list_snapshots(owner)


def test_supervisor_cannot_remove_original_even_while_saving_an_allowed_working_copy(workspace):
    store, owner = workspace
    original = seed(store, owner)
    _, supervisor = make_user(store, owner, "manager")
    changed = copy.deepcopy(original)
    changed.pop("blob")
    changed["text"] = "نسخة عمل جديدة"
    with pytest.raises(Forbidden):
        store.put(supervisor, "files", changed, original["version"])
    assert store.file_bytes(owner, original["id"]) == "الأصل محفوظ".encode()


@pytest.mark.parametrize("identity", ["admin", "abdullah"])
def test_admin_and_verified_abdullah_can_manage_originals_and_library_metadata(workspace, monkeypatch, identity):
    store, owner = workspace
    original = seed(store, owner)
    token = owner if identity == "admin" else make_abdullah(store, owner)[1]
    assert store.can_manage_library(store.actor(token))
    updated = original | {"title": "اسم معتمد", "starred": True, "blob": base64.b64encode(b"new original").decode()}
    store.put(token, "files", updated, original["version"])
    assert store.file_bytes(token, original["id"]) == b"new original"
    assert store.read(owner)[0]["files"][0]["title"] == "اسم معتمد"
    app = file_dialog(store, token, monkeypatch, mode="نسخة العمل")
    assert not element(app.text_input, "اسم الملف").disabled
    assert not element(app.selectbox, "مشروع الملف").disabled
    assert not element(app.selectbox, "المجلد").disabled


def test_display_name_or_generic_file_manager_role_never_impersonates_abdullah(workspace):
    store, owner = workspace
    original = seed(store, owner)
    store.create_user(owner, "another_person", "Abdullah", PASSWORD, "file_manager")
    token = store.login("another_person", PASSWORD)
    assert not store.can_manage_library(store.actor(token))
    with pytest.raises(Forbidden):
        store.put(token, "files", original | {"title": "غير مسموح"}, original["version"])
    with pytest.raises(Forbidden):
        store.remove(token, "files", original["id"], original["version"])


def test_supervisor_keeps_task_controls_uploads_folder_creation_and_working_copy_edits(workspace):
    store, owner = workspace
    original = seed(store, owner)
    _, supervisor = make_user(store, owner, "manager")
    store.put(supervisor, "tasks", task("my_task"))
    store.put(supervisor, "tasks", task("my_task") | {"title": "مهمة معدلة"}, 1)
    store.remove(supervisor, "tasks", "my_task", 2)
    store.put(supervisor, "folders", {"id": "new_folder", "name": "مجلد جديد", "parentId": "", "projectId": "p_general"})
    records, _ = prepare_uploads([("دفعة/ملف.txt", b"new source")], "p_general", directory=True)
    assert store.add_files(supervisor, records, folder_id="new_folder")["added"] == 1
    store.put(supervisor, "files", original | {"text": "تعديل محتوى نسخة العمل", "comments": [{"id": "c1", "text": "تعليق"}]}, original["version"])
    current = store.read(owner)[0]["files"][0]
    assert current["text"] == "تعديل محتوى نسخة العمل"
    assert current["title"] == original["title"]
    assert store.file_bytes(supervisor, original["id"]) == "الأصل محفوظ".encode()
    with pytest.raises(Forbidden):
        store.put(supervisor, "folders", {"id": "new_folder", "name": "تغيير الاسم", "parentId": "", "projectId": "p_general"}, 1)
    with pytest.raises(Forbidden):
        store.remove(supervisor, "folders", "new_folder", 1)


@pytest.mark.parametrize("old_metadata_missing", [False, True])
def test_supervisor_ui_locks_original_fields_but_saves_working_copy(workspace, monkeypatch, old_metadata_missing):
    store, owner = workspace
    original = seed(store, owner)
    if old_metadata_missing:
        original.pop("folderId", None)
        original.pop("starred", None)
        store.put(owner, "files", original, original["version"])
    _, supervisor = make_user(store, owner, "manager")
    app = file_dialog(store, supervisor, monkeypatch, mode="نسخة العمل")
    assert element(app.text_input, "اسم الملف").disabled
    assert element(app.selectbox, "مشروع الملف").disabled
    assert element(app.selectbox, "المجلد").disabled
    assert element(app.checkbox, "تمييز الملف").disabled
    assert not element(app.text_area, "محتوى المستند").disabled
    assert not any(b.label == "حذف الملف من المكتبة" for b in app.button)
    element(app.text_area, "محتوى المستند").set_value("تعديل نسخة العمل من الواجهة")
    element(app.button, "حفظ تعديلات الملف").click().run()
    healthy(app)
    after = store.read(owner)[0]["files"][0]
    assert after["text"] == "تعديل نسخة العمل من الواجهة"
    assert after["title"] == original["title"]
    if old_metadata_missing:
        assert "folderId" not in after and "starred" not in after
    assert store.file_bytes(owner, after["id"]) == "الأصل محفوظ".encode()


def test_folder_ui_offers_supervisor_creation_but_not_existing_folder_management(workspace, monkeypatch):
    store, owner = workspace
    store.put(owner, "folders", {"id": "folder", "name": "مجلد حالي", "projectId": "p_general", "parentId": ""})
    _, supervisor = make_user(store, owner, "manager")
    app = dashboard(store, supervisor, monkeypatch)
    assert not element(app.button, "↑ رفع ملفات").disabled
    assert not element(app.button, "مجلد جديد").disabled
    element(app.button, "مجلد حالي").click().run()
    healthy(app)
    assert not any("إدارة المجلد" in item.label for item in app.expander)
    assert not any(b.label == "حذف المجلد الفارغ" for b in app.button)


def test_supervisor_excel_working_copy_stays_editable_and_original_stays_unchanged(workspace, monkeypatch, workbook_bytes):
    store, owner = workspace
    record = parse_upload("ملف أصلي.xlsx", workbook_bytes, "p_general") | {"id": "uploaded-before"}
    store.add_files(owner, [record])
    _, supervisor = make_user(store, owner, "manager")
    current = store.read(owner)[0]["files"][0]
    changed = copy.deepcopy(current)
    changed["sheets"][0]["rows"][0][0] = "تعديل نسخة العمل فقط"
    store.put(supervisor, "files", changed, current["version"])
    assert store.file_bytes(supervisor, current["id"]) == workbook_bytes
    app = file_dialog(store, supervisor, monkeypatch, mode="نسخة العمل")
    assert app.dataframe and app.dataframe[0].proto.editing_mode != 0
    assert element(app.text_input, "اسم الملف").disabled
    assert not element(app.button, "حفظ تعديلات الملف").disabled


def test_stale_admin_dialog_cannot_delete_after_role_changes(workspace, monkeypatch):
    store, owner = workspace
    original = seed(store, owner)
    app = file_dialog(store, owner, monkeypatch)
    ident = store.actor(owner)["id"]
    with store.engine.begin() as conn:
        conn.execute(update(users).where(users.c.id == ident).values(role="manager"))
    with pytest.raises(Forbidden):
        store.remove(owner, "files", original["id"], original["version"])
    with pytest.raises(Forbidden):
        store.put(owner, "files", original | {"title": "من نموذج قديم"}, original["version"])
    assert len(store.read(owner)[0]["files"]) == 1


def test_project_moves_and_backup_restore_cannot_bypass_original_permissions(workspace):
    store, owner = workspace
    original = seed(store, owner)
    store.put(owner, "projects", {"id": "other", "name": "مشروع آخر"})
    _, supervisor = make_user(store, owner, "manager")
    before = store.read(owner)
    with pytest.raises(Forbidden):
        store.move_project_contents(supervisor, "p_general", "other", before[1])
    with pytest.raises(Forbidden):
        store.remove(supervisor, "projects", "p_general", 1)
    missing = copy.deepcopy(before[0])
    missing["files"] = []
    with pytest.raises(Forbidden):
        store.restore(supervisor, Store.backup_bytes(missing), before[1])
    renamed = copy.deepcopy(before[0])
    renamed["files"][0]["title"] = "عنوان مختلف"
    with pytest.raises(Forbidden):
        store.restore(supervisor, Store.backup_bytes(renamed), before[1])
    assert store.read(owner) == before
    assert not store.list_snapshots(owner)
    working = copy.deepcopy(before[0])
    working["files"][0]["text"] = "تحديث نسخة العمل عبر الاستعادة"
    store.restore(supervisor, Store.backup_bytes(working), before[1])
    assert store.read(owner)[0]["files"][0]["text"] == "تحديث نسخة العمل عبر الاستعادة"
    assert store.file_bytes(owner, original["id"]) == "الأصل محفوظ".encode()


@pytest.mark.parametrize("rename", [False, True])
def test_assistant_respects_requesting_supervisor_original_permissions(desk, rename):
    store, owner, _, repo = desk
    original = parse_upload("وثيقة متابعة.txt", "محتوى أصلي".encode(), "p_work")
    original["id"] = "protected-doc"
    store.add_files(owner, [original])
    _, supervisor = make_user(store, owner, "manager")
    repo.submit(supervisor, "p_work", "عدّل محتوى وثيقة متابعة", "desk_permission_request_001")
    job = repo.claim()
    data, sources, warnings, guards = repo.prepare(job)
    assert data["library_permissions"] == {"manage_originals": False}
    before = store.read(owner)
    values = {"text": "تحديث نسخة العمل"}
    if rename:
        values["title"] = "عنوان أصل مختلف"
    actions = [{"kind": "document_update", "target_id": "protected-doc", "values": values}]
    def finish():
        repo.finish(job["id"], job["details"]["lease"], "تم تحديث نسخة العمل", actions, {}, sources, warnings, guards, "test-model")
    if rename:
        with pytest.raises(Forbidden):
            finish()
        assert store.read(owner) == before
    else:
        finish()
        updated = store.read(owner)[0]["files"][0]
        assert updated["text"] == "تحديث نسخة العمل" and updated["title"] == original["title"]
    assert store.file_bytes(owner, original["id"]) == "محتوى أصلي".encode()
