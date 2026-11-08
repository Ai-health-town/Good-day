import io

import pytest
from openpyxl import load_workbook

import preview_ui
from sheet_preview import open_excel, sheet_html
from tests.test_file_preview import workbook_bytes


@pytest.fixture(autouse=True)
def clear_preview_caches():
    preview_ui.prepared_excel.clear()
    preview_ui.cached_excel_page.clear()
    yield
    preview_ui.prepared_excel.clear()
    preview_ui.cached_excel_page.clear()


def test_cached_preview_preserves_the_existing_render_and_skips_reparsing(workbook_bytes, monkeypatch):
    book = open_excel(workbook_bytes)
    values = open_excel(workbook_bytes, values=True)
    try:
        expected = sheet_html(book, values, "التوثيق", 1, 100, False)
    finally:
        book.close(); values.close()
    opened = []
    def tracked(*args, **kwargs):
        opened.append(True)
        return open_excel(*args, **kwargs)
    monkeypatch.setattr(preview_ui, "open_excel", tracked)
    sheets, selected, rendered = preview_ui.prepared_excel(workbook_bytes, None, "test-engine")
    assert list(sheets) == ["التوثيق", "الحسابات"]
    assert selected == "التوثيق" and rendered == expected
    assert len(opened) == 2
    assert preview_ui.prepared_excel(workbook_bytes, None, "test-engine") == (sheets, selected, expected)
    assert len(opened) == 2
    page = preview_ui.cached_excel_page(workbook_bytes, None, "الحسابات", 1, False, "test-engine")
    assert len(opened) == 4
    assert preview_ui.cached_excel_page(workbook_bytes, None, "الحسابات", 1, False, "test-engine") == page
    assert len(opened) == 4
    preview_ui.cached_excel_page(workbook_bytes, None, "الحسابات", 1, True, "test-engine")
    assert len(opened) == 6


def test_cache_tracks_changed_source_bytes_and_does_not_share_mutable_results(workbook_bytes):
    original = preview_ui.prepared_excel(workbook_bytes, None, "engine")
    original[0].clear()
    assert preview_ui.prepared_excel(workbook_bytes, None, "engine")[0]
    book = load_workbook(io.BytesIO(workbook_bytes))
    book["التوثيق"]["A4"] = "قيمة جديدة"
    output = io.BytesIO()
    book.save(output); book.close()
    changed = preview_ui.prepared_excel(output.getvalue(), None, "engine")
    assert "قيمة جديدة" in changed[2][0]
    assert changed[2] != original[2]


def test_cached_preview_uses_the_selected_calculated_workbook(workbook_bytes):
    book = load_workbook(io.BytesIO(workbook_bytes))
    book["التوثيق"]["D4"] = .975
    output = io.BytesIO()
    book.save(output); book.close()
    missing = preview_ui.prepared_excel(workbook_bytes, None, "engine")[2]
    calculated = preview_ui.prepared_excel(workbook_bytes, output.getvalue(), "engine")[2]
    assert "97.50%" in calculated[0]
    assert calculated[2] < missing[2]
