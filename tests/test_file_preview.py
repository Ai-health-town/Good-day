import copy
import io
import zipfile
from datetime import datetime

import pytest
from docx import Document
from openpyxl import Workbook, load_workbook
from openpyxl.chart import BarChart, Reference
from openpyxl.styles import Alignment, Font, PatternFill
from pypdf import PdfReader

from filetools import parse_upload, sheet_bytes
from office_preview import office_available, render_office, safe_formula, safe_office_copy
from sheet_preview import display_value, edited_excel, open_excel, sheet_html, theme_colors, color_hex
from workspace import WorkspaceError


@pytest.fixture
def workbook_bytes():
    book = Workbook()
    sheet = book.active
    sheet.title = "التوثيق"
    sheet.sheet_view.rightToLeft = True
    sheet.merge_cells("A1:D1")
    sheet["A1"] = "نموذج متابعة المؤشرات"
    sheet["A1"].font = Font(name="DejaVu Sans",bold=True,size=18,color="FFFFFF")
    sheet["A1"].fill = PatternFill("solid",fgColor="173D51")
    sheet["A1"].alignment = Alignment(horizontal="center")
    sheet.append(["", "", "", ""])
    sheet.append(["المؤشر","الإجمالي","المكتمل","النسبة"])
    sheet.append(["اكتمال البيانات",10000,9750,"=C4/B4"])
    sheet["D4"].number_format = "0.00%"
    sheet["B4"].number_format = "#,##0"
    sheet["A5"] = datetime(2026,11,5)
    sheet["A5"].number_format = "dd/mm/yyyy"
    sheet["B5"] = 0
    sheet["C5"] = "<img src=x onerror=alert(1)>"
    sheet["D5"] = "=SUM(B4:C4)"
    for letter in "ABCD": sheet.column_dimensions[letter].width = 24
    sheet.row_dimensions[1].height = 35
    sheet.row_dimensions[6].hidden = True
    chart = BarChart()
    chart.add_data(Reference(sheet,min_col=2,max_col=3,min_row=3,max_row=4),titles_from_data=True)
    sheet.add_chart(chart,"F2")
    sheet.print_area = "A1:K16"
    sheet.sheet_properties.pageSetUpPr.fitToPage = True
    sheet.page_setup.orientation = "landscape"
    sheet.page_setup.paperSize = sheet.PAPERSIZE_A4
    sheet.page_setup.fitToWidth = 1
    sheet.page_setup.fitToHeight = 1
    other = book.create_sheet("الحسابات")
    other["A1"] = "='التوثيق'!B4-'التوثيق'!C4"
    other["B1"] = "ورقة ثانية"
    result = io.BytesIO()
    book.save(result)
    return result.getvalue()


def test_excel_import_keeps_formulas_and_formatted_source_bytes(workbook_bytes):
    record = parse_upload("تقرير.xlsx",workbook_bytes,"p_general")
    assert record["sheets"][0]["rows"][3][3] == "=C4/B4"
    assert record["sheets"][1]["rows"][0][0] == "='التوثيق'!B4-'التوثيق'!C4"
    assert record["size"] == len(workbook_bytes)
    assert parse_upload("تقرير.xlsm",workbook_bytes,"p_general")["type"] == "sheet"


@pytest.mark.parametrize("dimension", [None,"A1:A1","A1:XFD1048576"])
def test_excel_import_uses_actual_cells_when_sheet_bounds_are_missing_or_wrong(workbook_bytes,dimension):
    import re
    archive = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(workbook_bytes)) as source, zipfile.ZipFile(archive,"w",zipfile.ZIP_DEFLATED) as out:
        for item in source.infolist():
            raw = source.read(item.filename)
            if item.filename.startswith("xl/worksheets/") and item.filename.endswith(".xml"):
                replacement = b"" if dimension is None else ('<dimension ref="'+dimension+'"/>').encode()
                raw = re.sub(rb"<dimension\b[^>]*/>",replacement,raw)
            out.writestr(item,raw)
    raw = archive.getvalue()
    record = parse_upload("تقرير.xlsx",raw,"p_general")
    assert record["sheets"][0]["rows"][3] == ["اكتمال البيانات","10000","9750","=C4/B4"]
    assert record["sheets"][1]["rows"][0][0] == "='التوثيق'!B4-'التوثيق'!C4"
    import base64
    assert base64.b64decode(record["blob"]) == raw


@pytest.mark.parametrize("address", ["A5001","BI1"])
def test_excel_import_checks_actual_limits_without_truncating_data(address):
    book = Workbook()
    book.active[address] = "خارج الحد"
    buffer = io.BytesIO()
    book.save(buffer)
    with pytest.raises(WorkspaceError,match="5000 صف و60 عمودًا"):
        parse_upload("حدود.xlsx",buffer.getvalue(),"p_general")


def test_excel_working_copy_preserves_styles_formulas_and_other_sheets(workbook_bytes):
    record = parse_upload("تقرير.xlsx",workbook_bytes,"p_general")
    sheets = copy.deepcopy(record["sheets"])
    sheets[0]["rows"][3][1] = "11000"
    sheets[0]["rows"][4][3] = "=SUM(B4:C4)+1"
    exported = edited_excel(workbook_bytes,sheets)
    updated = load_workbook(io.BytesIO(exported))
    original = load_workbook(io.BytesIO(workbook_bytes))
    assert updated["التوثيق"]["B4"].value == 11000
    assert updated["التوثيق"]["D4"].value == "=C4/B4"
    assert updated["التوثيق"]["D5"].value == "=SUM(B4:C4)+1"
    assert updated["الحسابات"]["A1"].value == original["الحسابات"]["A1"].value
    assert copy.copy(updated["التوثيق"]["A1"].font) == copy.copy(original["التوثيق"]["A1"].font)
    assert updated["التوثيق"]["D4"].number_format == "0.00%"
    assert list(updated["التوثيق"].merged_cells.ranges) == list(original["التوثيق"].merged_cells.ranges)
    assert updated["التوثيق"].column_dimensions["A"].width == 24
    assert len(updated["التوثيق"]._charts) == 1
    assert updated["التوثيق"]["B5"].value == 0


def test_excel_preview_keeps_merges_theme_colors_and_escapes_cell_content(workbook_bytes):
    book, values = open_excel(workbook_bytes), open_excel(workbook_bytes,True)
    html, formulas, missing = sheet_html(book,values,"التوثيق")
    assert 'colspan="4"' in html and 'dir="rtl"' in html
    assert "#173d51" in html and "#ffffff" in html
    assert "10,000" in html and "05/11/2026" in html
    assert "&lt;img" in html and "<img" not in html and "<script" not in html
    assert "default-src 'none'" in html
    assert missing == 2 and "غير محسوبة" in html
    assert formulas[0]["الصيغة"] == "=C4/B4"
    assert color_hex(book["التوثيق"]["B4"].font.color,theme_colors(book),"fallback") == "#000000"
    formula_html, _, _ = sheet_html(book,values,"التوثيق",formulas=True)
    assert "=C4/B4" in formula_html


def test_excel_formats_and_zero_export_are_correct():
    assert display_value(.975,"0.00%") == "97.50%"
    assert display_value(10000,"#,##0") == "10,000"
    assert display_value(0,"0.00") == "0.00"
    assert display_value(-2.5,"0.00;(0.00)") == "(2.50)"
    assert display_value(12,"00000") == "00012"
    raw = sheet_bytes([{"name":"النتائج","rows":[[0,False,None]]}])
    row = list(load_workbook(io.BytesIO(raw)).active.values)[0]
    assert row[:2] == ("0","False")


def test_preview_and_edited_formulas_never_enable_external_data(workbook_bytes):
    for formula in ("=SUM(B2:B8)","=SUM(Table1[Amount])","='ورقة ثانية'!A1*2"):
        assert safe_formula(formula)
    for formula in ('=WEBSERVICE("https://example.test")',"=cmd|' /C calc'!A0","=[Book.xlsx]Sheet1!A1"):
        assert not safe_formula(formula)
    record = parse_upload("تقرير.xlsx",workbook_bytes,"p_general")
    record["sheets"][0]["rows"][3][3] = '=WEBSERVICE("https://example.test")'
    with pytest.raises(WorkspaceError,match="اتصالًا خارجيًا"):
        edited_excel(workbook_bytes,record["sheets"])
    book = load_workbook(io.BytesIO(workbook_bytes))
    book["التوثيق"]["D4"] = '=WEBSERVICE("https://example.test")'
    unsafe = io.BytesIO()
    book.save(unsafe)
    prepared, changed = safe_office_copy(unsafe.getvalue())
    assert changed
    with zipfile.ZipFile(io.BytesIO(prepared)) as archive:
        assert b"WEBSERVICE" not in archive.read("xl/worksheets/sheet1.xml")
    assert b"WEBSERVICE" in zipfile.ZipFile(io.BytesIO(unsafe.getvalue())).read("xl/worksheets/sheet1.xml")


def test_word_index_keeps_paragraphs_and_tables_in_document_order():
    document = Document()
    document.add_paragraph("قبل الجدول")
    document.add_table(rows=1,cols=1).cell(0,0).text = "الجدول في مكانه"
    document.add_paragraph("بعد الجدول")
    raw = io.BytesIO()
    document.save(raw)
    text = parse_upload("تقرير.docx",raw.getvalue(),"p_general")["text"]
    assert text.index("قبل الجدول") < text.index("الجدول في مكانه") < text.index("بعد الجدول")


def test_csv_and_tsv_accept_excel_utf16_and_semicolon_delimiters():
    raw = "الاسم;النسبة\nالمركز;97.50%".encode("utf-16")
    assert parse_upload("نتائج.csv",raw,"p_general")["sheets"][0]["rows"][1] == ["المركز","97.50%"]
    assert parse_upload("نتائج.tsv",b"one\ttwo\n1\t0","p_general")["sheets"][0]["rows"][1] == ["1","0"]


def test_built_in_example_has_real_formulas_and_styles():
    from preview_ui import example_excel
    book = open_excel(example_excel())
    assert book.sheetnames == ["البيانات","الملخص"]
    assert book["البيانات"]["D4"].value == "=C4/B4"
    assert "SUM" in book["الملخص"]["B1"].value
    assert book["البيانات"]["D4"].number_format == "0.00%"
    assert "A1:E1" in str(book["البيانات"].merged_cells)


def test_uploaded_file_opens_on_original_and_working_edits_preserve_its_bytes(tmp_path,monkeypatch):
    from pathlib import Path
    from pypdf import PdfWriter
    from streamlit.testing.v1 import AppTest
    import preview_ui
    from office_preview import OfficePreview
    from workspace import Store
    from tests.test_ui import element,healthy
    document = Document()
    document.add_paragraph("مستند تجريبي")
    document.add_table(rows=1,cols=1).cell(0,0).text = "جدول تجريبي"
    source = io.BytesIO()
    document.save(source)
    writer = PdfWriter()
    writer.add_blank_page(width=595,height=842)
    pdf = io.BytesIO()
    writer.write(pdf)
    monkeypatch.setattr(preview_ui,"converted_original",lambda *args:OfficePreview(pdf.getvalue(),pages=1))
    url = "sqlite:///" + str(tmp_path/"preview_ui.db")
    monkeypatch.setenv("DATABASE_URL",url)
    store = Store(url)
    store.bootstrap("owner","Preview-test-password-879!")
    token = store.login("owner","Preview-test-password-879!")
    record = parse_upload("تجربة.docx",source.getvalue(),"p_general")
    store.add_files(token,[record])
    app = AppTest.from_string('''
import os
import streamlit as st
from components import edit_file
from workspace import Store
store = Store(os.environ['DATABASE_URL'])
token = st.session_state['test_token']
state, _ = store.read(token)
edit_file(store, token, state, store.actor(token), state['files'][0])
''',default_timeout=20)
    app.session_state["test_token"] = token
    app.run()
    healthy(app)
    assert not any(x.label == "محتوى المستند" for x in app.text_area)
    assert any("معاينة الصفحات" in x.value for x in app.caption)
    app.session_state["file_mode_"+record["id"]] = "نسخة العمل"
    app.run()
    healthy(app)
    element(app.text_area,"محتوى المستند").set_value("تعديل نسخة العمل")
    element(app.button,"حفظ تعديلات الملف").click().run()
    healthy(app)
    assert store.read(token)[0]["files"][0]["text"] == "تعديل نسخة العمل"
    assert store.file_bytes(token,record["id"]) == source.getvalue()


@pytest.mark.skipif(not office_available(),reason="LibreOffice is not installed in this test environment")
def test_real_office_engine_renders_pages_and_calculates_excel_formulas(workbook_bytes):
    result = render_office(workbook_bytes,".xlsx")
    assert result.pdf.startswith(b"%PDF-") and result.pages >= 2
    assert result.workbook
    values = load_workbook(io.BytesIO(result.workbook),data_only=True)
    assert values["التوثيق"]["D4"].value == pytest.approx(9750/10000)
    assert values["الحسابات"]["A1"].value == 250
    book = open_excel(workbook_bytes)
    html, _, missing = sheet_html(book,values,"التوثيق")
    assert "97.50%" in html and missing == 0
    assert len(PdfReader(io.BytesIO(result.pdf)).pages) == result.pages
