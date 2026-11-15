import base64
import io
from pathlib import Path

import pytest
from PIL import Image
from streamlit.testing.v1 import AppTest

import image_tools
import preview_ui
from filetools import parse_upload
from foldertools import prepare_uploads
from workspace import Store, WorkspaceError, prepare_import
from tests.test_ui import healthy, element
from tests.test_workspace import workspace


def raster(format="PNG", mode="RGBA", size=(80, 40)):
    out = io.BytesIO()
    color = (20, 110, 80, 130) if mode == "RGBA" else (20, 110, 80)
    with Image.new(mode, size, color) as picture:
        picture.save(out, format)
    return out.getvalue()


@pytest.mark.parametrize("extension,format,mode", [("PNG", "PNG", "RGBA"), ("jpg", "JPEG", "RGB"), ("webp", "WEBP", "RGB"),
                                                   ("gif", "GIF", "RGB"), ("bmp", "BMP", "RGB"), ("tiff", "TIFF", "RGB")])
def test_supported_rasters_parse_preview_and_keep_the_original(extension, format, mode):
    raw = raster(format, mode)
    record = parse_upload("صورة." + extension, raw, "p_general")
    assert record["type"] == "image"
    assert record["imageInfo"] == {"width": 80, "height": 40, "format": format}
    assert base64.b64decode(record["blob"]) == raw
    preview = image_tools.prepare_image(raw)
    with Image.open(io.BytesIO(preview.data)) as picture:
        assert picture.size == (80, 40)
        if mode == "RGBA":
            assert picture.getpixel((0, 0)) == (20, 110, 80, 130)


def test_exif_rotation_is_applied_only_to_preview():
    source = io.BytesIO()
    with Image.new("RGB", (80, 40), "red") as picture:
        exif = Image.Exif()
        exif[274] = 6
        picture.save(source, "JPEG", exif=exif)
    raw = source.getvalue()
    preview = image_tools.prepare_image(raw)
    assert (preview.width, preview.height) == (40, 80)
    with Image.open(io.BytesIO(raw)) as original:
        assert original.size == (80, 40) and original.getexif()[274] == 6
    with Image.open(io.BytesIO(preview.data)) as rendered:
        assert not rendered.getexif().get(274)


def test_large_preview_is_bounded_and_preserves_aspect_ratio(monkeypatch):
    monkeypatch.setattr(image_tools, "MAX_PREVIEW_EDGE", 60)
    preview = image_tools.prepare_image(raster(size=(160, 80)))
    assert (preview.width, preview.height) == (60, 30)
    monkeypatch.setattr(image_tools, "MAX_IMAGE_PIXELS", 100)
    with pytest.raises(WorkspaceError, match="أبعاد"):
        image_tools.prepare_image(raster())


@pytest.mark.parametrize("raw", [b"", b"not an image", raster()[:20], b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'])
def test_corrupt_or_active_content_is_never_used_as_a_raster(raw):
    with pytest.raises(WorkspaceError):
        parse_upload("fake.png", raw, "p_general")


def test_directory_upload_backup_and_legacy_attachments_need_no_data_migration(workspace):
    store, token = workspace
    raw = raster()
    files, _ = prepare_uploads([("المشروع/المسارات/رسم.png", raw)], "p_general", directory=True)
    store.add_files(token, files)
    state, _ = store.read(token)
    assert state["files"][0]["folderId"] and state["files"][0]["type"] == "image"
    restored = prepare_import(Store.backup_bytes(state))["data"]
    assert restored["files"][0]["imageInfo"]["format"] == "PNG"
    assert store.file_bytes(token, state["files"][0]["id"]) == raw
    old = files[0] | {"type": "attachment", "title": "عنوان محدث", "originalName": "رسم.PNG"}
    assert image_tools.file_kind(old) == "image"
    assert image_tools.file_kind({"type": "attachment", "originalName": "active.svg"}) == "attachment"


def test_existing_uploaded_image_renders_in_file_dialog_and_keeps_annotations(workspace, monkeypatch):
    store, token = workspace
    raw = raster()
    record = parse_upload("صورة قديمة.png", raw, "p_general") | {"type": "attachment", "text": "ملاحظات محفوظة"}
    store.add_files(token, [record])
    monkeypatch.setenv("DATABASE_URL", str(store.engine.url))
    source = '''
import os
import streamlit as st
from components import edit_file
from workspace import Store
store=Store(os.environ['DATABASE_URL'])
state,_,actor=store.context(st.session_state['token'])
edit_file(store,st.session_state['token'],state,actor,state['files'][0])
'''
    app = AppTest.from_string(source, default_timeout=20)
    app.session_state["token"] = token
    app.run()
    healthy(app)
    assert app.get("image") and app.get("image")[0].proto.imgs[0].caption == "صورة قديمة.png"
    assert not any("بالتطبيق المناسب" in notice.value for notice in app.info)
    assert any("PNG" in caption.value for caption in app.caption)
    app.session_state["file_mode_" + record["id"]] = "نسخة العمل"
    app.run()
    healthy(app)
    assert element(app.text_area, "ملخص الملف وملاحظاته").value == "ملاحظات محفوظة"
    assert store.file_bytes(token, record["id"]) == raw


def test_old_corrupt_attachment_fails_gracefully_and_preview_cache_is_reused(monkeypatch):
    calls = []
    original = preview_ui.prepare_image
    def counted(raw):
        calls.append(True)
        return original(raw)
    monkeypatch.setattr(preview_ui, "prepare_image", counted)
    preview_ui.prepared_image.clear()
    first = preview_ui.prepared_image(raster(), "engine")
    assert preview_ui.prepared_image(raster(), "engine") == first
    assert len(calls) == 1
    app = AppTest.from_string('''
from preview_ui import original_preview
original_preview({'id':'old','title':'broken.png','type':'attachment'},b'broken')
''').run()
    healthy(app)
    assert app.warning


def test_image_filter_includes_old_and_new_images_without_other_attachments(workspace, monkeypatch):
    store, token = workspace
    raw = raster()
    records = [parse_upload("old.png", raw, "p_general") | {"type": "attachment"},
               parse_upload("new.png", raw, "p_general"),
               parse_upload("other.bin", b"attachment", "p_general", allow_attachment=True)]
    store.add_files(token, records)
    monkeypatch.setenv("DATABASE_URL", str(store.engine.url))
    monkeypatch.setenv("GDAY_LOCAL_MODE", "true")
    app = AppTest.from_file(str(Path(__file__).parents[1] / "app.py"), default_timeout=20)
    app.session_state["token"] = token
    app.session_state["navigation"] = "الملفات"
    app.run()
    element(app.selectbox, "نوع الملفات").set_value("صور").run()
    healthy(app)
    assert len([button for button in app.button if button.label == "فتح الملف"]) == 2
    assert next(metric for metric in app.metric if metric.label == "صور").value == "2"
