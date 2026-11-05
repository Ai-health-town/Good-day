"""Authenticated in-app document and spreadsheet previews."""
from __future__ import annotations

import math
from pathlib import Path

import pandas as pd
import streamlit as st
import streamlit.components.v1 as html_component

from filetools import file_sheets, file_text
from office_preview import OFFICE_TYPES, render_office
from sheet_preview import open_excel, sheet_html
from workspace import WorkspaceError


@st.cache_data(show_spinner=False, max_entries=3, ttl=1800)
def converted_original(raw, suffix, engine_generation):
    # Callers authenticate and obtain source bytes before consulting this RAM-only cache.
    return render_office(raw, suffix)


def excel_view(record, source, calculated=None):
    book, values = None, None
    try:
        book = open_excel(source)
        values = open_excel(calculated or source, values=True)
        names = [s.title for s in book.worksheets if s.sheet_state == "visible"]
        if not names:
            st.info("لا توجد أوراق ظاهرة في هذا الملف.")
            return
        selected = st.selectbox("ورقة Excel", names, key="preview_sheet_" + record["id"])
        sheet = book[selected]
        a, b = st.columns([1,2])
        page = a.number_input("صفحة الصفوف", min_value=1, max_value=max(1,math.ceil(sheet.max_row/100)),
                              step=1, key="preview_page_" + record["id"] + selected)
        formulas = b.checkbox("إظهار الصيغ بدل النتائج", key="preview_formulas_" + record["id"])
        first = (page-1)*100+1
        html, formula_rows, missing = sheet_html(book,values,selected,first,100,formulas)
        st.caption(f"الصفوف {first}–{min(sheet.max_row,first+99)} من {sheet.max_row} · {sheet.max_column} أعمدة. للتنسيق المشروط والرسوم وتوزيع الصفحات اختر «تخطيط الطباعة».")
        html_component.html(html,height=635,scrolling=False)
        if missing:
            st.warning(f"{missing} خلية بصيغة لا تحتوي نتيجة محفوظة في هذا النطاق. لم تُستبدل بصفر. راجع تخطيط الطباعة أو احفظ الحسابات في Excel ثم ارفع النسخة المحدّثة.")
        if formula_rows:
            with st.expander("الصيغ ونتائجها في الصفوف المعروضة"):
                st.dataframe(pd.DataFrame(formula_rows), hide_index=True, width="stretch")
    except WorkspaceError as exc:
        st.warning(str(exc))
    finally:
        if book is not None: book.close()
        if values is not None: values.close()


def original_preview(record, raw, working_copy=True):
    suffix = Path(record.get("originalName") or record["title"]).suffix.lower()
    if working_copy:
        st.caption("هذه معاينة الأصل كما رُفع. تعديلات المحتوى محفوظة بصورة مستقلة في «نسخة العمل».")
    if record.get("type") == "pdf":
        st.pdf(raw,height=650,key="original_pdf_" + record["id"])
        return
    if suffix in OFFICE_TYPES:
        preview = None
        try:
            with st.spinner("يجهّز صفحات الملف وتنسيقه…"):
                preview = converted_original(raw,suffix,id(render_office))
        except WorkspaceError as exc:
            st.warning(str(exc))
        if record.get("type") == "sheet":
            view = st.radio("عرض Excel",["أوراق Excel","تخطيط الطباعة"],horizontal=True,
                            key="excel_view_" + record["id"])
            if view == "أوراق Excel":
                source = preview.workbook if suffix == ".xls" and preview else raw
                if source and (suffix != ".xls" or preview and preview.workbook):
                    excel_view(record,source,preview.workbook if preview else None)
                else:
                    st.info("تحتاج معاينة XLS المنسّقة اكتمال تجهيز محرك Office. تتوفر البيانات المحفوظة في نسخة العمل والأصل للتنزيل.")
                return
        if preview:
            st.caption(f"معاينة الصفحات · {preview.pages} صفحة")
            st.pdf(preview.pdf,height=650,key="office_pdf_" + record["id"])
            st.download_button("تنزيل نسخة العرض — PDF",preview.pdf,Path(record["title"]).stem + ".pdf","application/pdf",
                               key="preview_download_" + record["id"],width="stretch")
            if preview.external_content_disabled:
                st.caption("تُعرض النسخة المحفوظة دون تحديث المصادر الخارجية المرتبطة بالملف.")
        return
    if record.get("type") == "sheet":
        sheets = file_sheets(record)
        index = st.selectbox("ورقة البيانات",range(len(sheets)),format_func=lambda i:sheets[i]["name"],key="text_sheet_"+record["id"])
        st.dataframe(pd.DataFrame(sheets[index]["rows"]),hide_index=True,width="stretch")
    else:
        st.text(file_text(record))


@st.cache_data(show_spinner=False)
def example_excel():
    """A small synthetic example for checking the viewer without saving team data."""
    import io
    from datetime import datetime
    from openpyxl import Workbook
    from openpyxl.styles import Alignment,Font,PatternFill
    book = Workbook()
    sheet = book.active
    sheet.title = "البيانات"
    sheet.sheet_view.rightToLeft = True
    sheet.merge_cells("A1:E1")
    sheet["A1"] = "مثال توضيحي لعرض Excel"
    sheet["A1"].font = Font(name="DejaVu Sans",bold=True,size=18,color="FFFFFF")
    sheet["A1"].fill = PatternFill("solid",fgColor="173D51")
    sheet["A1"].alignment = Alignment(horizontal="center")
    sheet.row_dimensions[1].height = 40
    sheet.append(["", "", "", "", ""])
    sheet.append(["البند","المطلوب","المنجز","نسبة الإنجاز","التاريخ"])
    for row,values in enumerate((("بند 1",10,8),("بند 2",20,15),("بند 3",30,24)),4):
        sheet.append([*values,f"=C{row}/B{row}",datetime(2025,1,15)])
        sheet[f"D{row}"].number_format = "0.00%"
        sheet[f"E{row}"].number_format = "dd/mm/yyyy"
        for cell in sheet[row]:
            cell.alignment = Alignment(horizontal="center",vertical="center")
            if row % 2 == 0: cell.fill = PatternFill("solid",fgColor="E8F4F1")
        sheet.row_dimensions[row].height = 30
    for cell in sheet[3]:
        cell.fill = PatternFill("solid",fgColor="1A5354")
        cell.font = Font(bold=True,color="FFFFFF")
    for column in "ABCDE": sheet.column_dimensions[column].width = 23
    summary = book.create_sheet("الملخص")
    summary.sheet_view.rightToLeft = True
    summary.append(["إجمالي الإنجاز","=SUM('البيانات'!C4:C6)/SUM('البيانات'!B4:B6)"])
    summary["B1"].number_format = "0.00%"
    for column in "AB": summary.column_dimensions[column].width = 26
    for item in book.worksheets:
        item.sheet_properties.pageSetUpPr.fitToPage = True
        item.page_setup.orientation = "landscape"
        item.page_setup.fitToWidth = 1
        item.page_setup.fitToHeight = 1
    out = io.BytesIO()
    book.save(out)
    return out.getvalue()


@st.dialog("تجربة عارض Excel",width="large")
def excel_example():
    from filetools import parse_upload
    raw = example_excel()
    record = parse_upload("مثال_Excel.xlsx",raw,"p_general")
    record["id"] = "example_excel"
    st.caption("مثال توضيحي للتنسيق والدمج والصيغ وأوراق العمل. لا يُضاف إلى مكتبة الفريق.")
    original_preview(record,raw,working_copy=False)
