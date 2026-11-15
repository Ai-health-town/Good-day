import base64
import copy
import io

import pytest
from openpyxl import Workbook, load_workbook
from streamlit.testing.v1 import AppTest

import preview_ui
import workspace as workspace_module
from filetools import parse_upload
from office_preview import OfficePreview
from workspace import Store, Forbidden
from tests.test_workspace import workspace, task
from tests.test_performance import capture_queries
from tests.test_file_preview import workbook_bytes
from tests.test_ui import healthy, element


def test_original_reads_and_reminders_do_not_copy_unrelated_library_data(workspace, monkeypatch):
    store, token = workspace
    store.add_files(token, [parse_upload("source.txt", b"original", "p_general")])
    store.put(token, "tasks", task("reminder"))
    snapshot, _, _ = store._context_snapshot(token)
    copied = []
    original_copy = copy.deepcopy
    def trace(value, *args, **kwargs):
        copied.append(value)
        return original_copy(value, *args, **kwargs)
    monkeypatch.setattr(workspace_module.copy, "deepcopy", trace)
    queries = capture_queries(store)
    ident = snapshot["files"][0]["id"]
    assert store.file_bytes(token, ident) == b"original"
    assert not copied
    state, _, actor = store.reminder_context(token)
    assert set(state) == {"tasks"} and state["tasks"] == snapshot["tasks"]
    assert len(copied) == 1 and copied[0] is snapshot["tasks"]
    assert len(queries) == 2
    state["tasks"][0]["title"] = "تعديل غير محفوظ"
    assert store.reminder_context(token)[0]["tasks"][0]["title"] == "متابعة العمل"


def test_optimized_reads_see_other_worker_changes_and_still_reject_logged_out_users(workspace):
    store, token = workspace
    store.add_files(token, [parse_upload("source.txt", b"before", "p_general")])
    record = store.read(token)[0]["files"][0]
    assert store.file_bytes(token, record["id"]) == b"before"
    other = Store(str(store.engine.url))
    changed = record | {"blob": base64.b64encode(b"after").decode()}
    other.put(token, "files", changed, record["version"])
    other.put(token, "tasks", task("new_reminder"))
    assert store.file_bytes(token, record["id"]) == b"after"
    assert store.reminder_context(token)[0]["tasks"][0]["id"] == "new_reminder"
    other.logout(token)
    with pytest.raises(Forbidden):
        store.file_bytes(token, record["id"])
    with pytest.raises(Forbidden):
        store.reminder_context(token)


def preview_app(raw):
    app = AppTest.from_string('''
import streamlit as st
from preview_ui import original_preview
original_preview({'id':'native','type':'sheet','title':'sample.xlsx','originalName':'sample.xlsx'},st.session_state['raw'])
''', default_timeout=20)
    app.session_state["raw"] = raw
    return app.run()


def test_excel_grid_uses_saved_values_without_starting_office_until_print_is_requested(monkeypatch):
    book = Workbook()
    book.active.append(["المطلوب", "المنجز"])
    book.active.append([10, 7])
    out = io.BytesIO()
    book.save(out)
    calls = []
    def convert(*args):
        calls.append(True)
        return OfficePreview(b"%PDF-1.4\n", pages=1)
    monkeypatch.setattr(preview_ui, "converted_original", convert)
    app = preview_app(out.getvalue())
    healthy(app)
    assert not calls
    assert "المنجز" in app.get("iframe")[0].proto.srcdoc
    element(app.radio, "عرض Excel").set_value("تخطيط الطباعة").run()
    healthy(app)
    assert len(calls) == 1
    assert any("معاينة الصفحات" in caption.value for caption in app.caption)


def test_excel_grid_still_calculates_missing_formula_results(workbook_bytes, monkeypatch):
    book = load_workbook(io.BytesIO(workbook_bytes))
    book["التوثيق"]["D4"] = .975
    output = io.BytesIO()
    book.save(output)
    book.close()
    calls = []
    def convert(*args):
        calls.append(True)
        return OfficePreview(b"%PDF-1.4\n", pages=1, workbook=output.getvalue())
    monkeypatch.setattr(preview_ui, "converted_original", convert)
    app = preview_app(workbook_bytes)
    healthy(app)
    assert len(calls) == 1
    assert "97.50%" in app.get("iframe")[0].proto.srcdoc
