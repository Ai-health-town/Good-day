"""Real file parsing and exports. Uploaded binary originals are kept unchanged."""
from __future__ import annotations

import base64
import csv
import io
import re
import zipfile
from datetime import date, datetime
from html.parser import HTMLParser
from pathlib import Path

from docx import Document
from docx.oxml import OxmlElement
from docx.table import Table
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill, Alignment

from workspace import WorkspaceError, STATUSES, PRIORITIES, now_iso, uid

MAX_FILE = 8 * 1024 * 1024


class PlainText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts, self.skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.skip += 1
        if not self.skip and tag in ("p", "div", "h1", "h2", "h3", "li", "br", "tr"):
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self.skip:
            self.skip -= 1
        if not self.skip and tag in ("p", "div", "li", "h1", "h2", "h3", "tr"):
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


def plain_text(content):
    parser = PlainText()
    parser.feed(str(content or ""))
    return re.sub(r"\n[ \t]*\n[ \t]*\n+", "\n\n", "".join(parser.parts)).strip()


def check_archive(raw):
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        if len(archive.infolist()) > 5000 or sum(x.file_size for x in archive.infolist()) > 50 * 1024 * 1024:
            raise WorkspaceError("الملف المضغوط داخليًا أكبر من حد المعالجة (50 ميجابايت).")


def cell_text(value):
    if value is None:
        return ""
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return str(value)


def parse_upload(filename, raw, project_id):
    if len(raw) > MAX_FILE:
        raise WorkspaceError("الحد الأقصى لكل ملف 8 ميجابايت.")
    suffix = Path(filename).suffix.lower()
    record = {"id": uid("f_"), "title": Path(filename).name, "projectId": project_id, "starred": False,
              "comments": [], "blob": base64.b64encode(raw).decode(), "originalName": Path(filename).name,
              "size": len(raw), "updatedAt": now_iso(), "legacy": False}
    try:
        if suffix in (".xlsx", ".xlsm"):
            check_archive(raw)
            book = load_workbook(io.BytesIO(raw), read_only=True, data_only=False, keep_links=False)
            if len(book.worksheets) > 20:
                raise WorkspaceError("الحد الأقصى 20 ورقة داخل ملف Excel.")
            sheets = []
            for sheet in book.worksheets:
                if sheet.max_row > 5000 or sheet.max_column > 60:
                    raise WorkspaceError("الحد الأقصى للتحرير 5000 صف و60 عمودًا لكل ورقة.")
                rows = [[cell_text(v) for v in r] for r in sheet.iter_rows(values_only=True)]
                sheets.append({"name": sheet.title, "rows": rows or [[""]]})
            book.close()
            record.update(type="sheet", sheets=sheets)
        elif suffix == ".xls":
            import xlrd
            book = xlrd.open_workbook(file_contents=raw, on_demand=True)
            try:
                if book.nsheets > 20:
                    raise WorkspaceError("الحد الأقصى 20 ورقة داخل ملف Excel.")
                sheets = []
                for sheet in book.sheets():
                    if sheet.nrows > 5000 or sheet.ncols > 60:
                        raise WorkspaceError("الحد الأقصى للتحرير 5000 صف و60 عمودًا لكل ورقة.")
                    rows = []
                    for r in range(sheet.nrows):
                        row = []
                        for c in range(sheet.ncols):
                            cell = sheet.cell(r,c)
                            value = xlrd.xldate_as_datetime(cell.value,book.datemode) if cell.ctype == xlrd.XL_CELL_DATE else cell.value
                            if isinstance(value,float) and value.is_integer(): value = int(value)
                            row.append(cell_text(value))
                        rows.append(row)
                    sheets.append({"name":sheet.name,"rows":rows or [[""]]})
                record.update(type="sheet",sheets=sheets)
            finally:
                book.release_resources()
        elif suffix in (".csv", ".tsv"):
            text = raw.decode("utf-16") if raw.startswith((b"\xff\xfe",b"\xfe\xff")) else raw.decode("utf-8-sig")
            try:
                dialect = csv.Sniffer().sniff(text[:8192],delimiters=",;\t")
            except csv.Error:
                dialect = csv.excel_tab if suffix == ".tsv" else csv.excel
            rows = list(csv.reader(io.StringIO(text),dialect))
            if len(rows) > 5000 or any(len(r) > 60 for r in rows):
                raise WorkspaceError("الحد الأقصى 5000 صف و60 عمودًا.")
            record.update(type="sheet", sheets=[{"name": "البيانات", "rows": rows or [[""]]}])
        elif suffix == ".docx":
            check_archive(raw)
            document = Document(io.BytesIO(raw))
            paragraphs = []
            for part in document.iter_inner_content():
                if isinstance(part,Table):
                    paragraphs.extend(" | ".join(c.text for c in row.cells) for row in part.rows)
                else:
                    paragraphs.append(part.text)
            record.update(type="doc", text="\n".join(paragraphs))
        elif suffix in (".txt", ".md", ".html", ".gdoc"):
            text = raw.decode("utf-8-sig")
            record.update(type="doc", text=plain_text(text) if suffix in (".html", ".gdoc") else text)
        elif suffix == ".pdf":
            if not raw.lstrip().startswith(b"%PDF-"):
                raise WorkspaceError("الملف ليس PDF صالحًا.")
            record.update(type="pdf", text="")
        else:
            raise WorkspaceError("الصيغ المدعومة: DOCX وXLSX وXLSM وXLS وCSV وTSV وPDF وTXT وMD وHTML. حوّل ملفات DOC القديمة إلى DOCX أولًا.")
    except WorkspaceError:
        raise
    except Exception:
        raise WorkspaceError("تعذّر قراءة الملف. تأكد من أنه سليم وغير محمي بكلمة مرور.") from None
    return record


def file_text(record):
    if "text" in record:
        return str(record["text"])
    if record.get("content"):
        return plain_text(record["content"])
    return "\n\n".join(str(p.get("pageTitle", "")) + "\n" + str(p.get("body", "")) for p in record.get("pdfPages", []) if isinstance(p, dict))


def file_sheets(record):
    return record.get("sheets") or [{"name": "البيانات", "rows": record.get("sheetData") or [[""]]}]


def docx_bytes(title, text):
    document = Document()
    document.core_properties.title = title
    for index, line in enumerate([title] + str(text).splitlines()):
        p = document.add_paragraph(line)
        p.paragraph_format.space_after = __import__("docx").shared.Pt(8)
        bidi = OxmlElement("w:bidi")
        p._p.get_or_add_pPr().append(bidi)
        for run in p.runs:
            run.font.name = "Arial"
            run.font.size = __import__("docx").shared.Pt(18 if index == 0 else 11)
            run.bold = index == 0
    out = io.BytesIO()
    document.save(out)
    return out.getvalue()


def sheet_bytes(sheets):
    book = Workbook()
    book.remove(book.active)
    for item in sheets:
        sheet = book.create_sheet(re.sub(r"[\\/*?:\[\]]", "_", item["name"])[:31] or "Sheet")
        sheet.sheet_view.rightToLeft = True
        for row in item["rows"]:
            # Literal text avoids turning chat/imported content into spreadsheet formulas.
            sheet.append([str("" if value is None else value) for value in row])
            for cell in sheet[sheet.max_row]:
                cell.data_type = "s"
                cell.alignment = Alignment(horizontal="right", vertical="top", wrap_text=True)
        sheet.freeze_panes = "A2"
        if sheet.max_row:
            for cell in sheet[1]:
                cell.fill = PatternFill("solid", fgColor="173C44")
                cell.font = Font(color="FFFFFF", bold=True)
        for col in sheet.columns:
            sheet.column_dimensions[col[0].column_letter].width = min(60, max(18, max(len(str(c.value or "")) for c in col) + 3))
    out = io.BytesIO()
    book.save(out)
    return out.getvalue()


def tasks_excel(state):
    names = {x["id"]: x.get("name", "") for key in ("members", "projects", "stakeholders") for x in state[key]}
    rows = [["المهمة", "المشروع", "المسؤول", "الحالة", "الأولوية", "تاريخ الاستحقاق", "الوقت المتوقع (دقيقة)", "جهة التواصل", "الملاحظات"]]
    for task in state["tasks"]:
        rows.append([task.get("title", ""), names.get(task.get("projectId"), ""), names.get(task.get("assigneeId"), "غير معين"),
                     STATUSES.get(task.get("status"), ""), PRIORITIES.get(task.get("priority"), ""), task.get("dueDate", ""),
                     task.get("estimatedMinutes", 30), names.get(task.get("stakeholderId"), ""), task.get("notes", "")])
    return sheet_bytes([{"name": "المهام", "rows": rows}])
