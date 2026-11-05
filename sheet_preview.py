"""Excel cell views and loss-aware working-copy exports; no formula execution in Python."""
from __future__ import annotations

import io
import math
import re
import zipfile
from datetime import date, datetime, time
from html import escape
from xml.etree import ElementTree as ET

from openpyxl import load_workbook
from openpyxl.styles.colors import COLOR_INDEX
from openpyxl.utils import get_column_letter

from filetools import cell_text, check_archive
from office_preview import safe_formula
from workspace import WorkspaceError

MAX_CELLS = 300000


def open_excel(raw, values=False):
    check_archive(raw)
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            cells = sum(len(re.findall(rb"<(?:\w+:)?c(?:\s|>)", archive.read(n))) for n in archive.namelist()
                        if n.startswith("xl/worksheets/") and n.endswith(".xml"))
            if cells > MAX_CELLS:
                raise WorkspaceError("هذا الجدول كبير للعرض المنسّق؛ استخدم معاينة الطباعة أو نزّل الأصل.")
        book = load_workbook(io.BytesIO(raw), data_only=values, keep_links=False)
        if len(book.worksheets) > 20 or sum(s.max_row * s.max_column for s in book.worksheets) > MAX_CELLS:
            book.close()
            raise WorkspaceError("هذا الجدول كبير للعرض المنسّق؛ استخدم معاينة الطباعة أو نزّل الأصل.")
        return book
    except WorkspaceError:
        raise
    except Exception:
        raise WorkspaceError("تعذر فتح أوراق Excel. تأكد من أن الملف سليم وغير مشفّر.") from None


def theme_colors(book):
    defaults = ["FFFFFF", "000000", "EEECE1", "1F497D", "4F81BD", "C0504D", "9BBB59", "8064A2", "4BACC6", "F79646"]
    try:
        root = ET.fromstring(book.loaded_theme)
        scheme = root.find(".//{http://schemas.openxmlformats.org/drawingml/2006/main}clrScheme")
        result = [next(iter(e)).get("lastClr") or next(iter(e)).get("val") for e in scheme]
        return [result[i] for i in (1,0,3,2,4,5,6,7,8,9,10,11)] if len(result) >= 12 else defaults
    except Exception:
        return defaults


def color_hex(color, palette, fallback):
    try:
        if color is None:
            return fallback
        if color.type == "rgb": value = color.rgb[-6:]
        elif color.type == "indexed": value = COLOR_INDEX[color.indexed][-6:]
        elif color.type == "theme": value = palette[color.theme]
        else: return fallback
        if not re.fullmatch(r"[0-9A-Fa-f]{6}", value): return fallback
        tint = float(color.tint or 0)
        channels = [int(value[i:i+2], 16) for i in (0, 2, 4)]
        channels = [round(v * (1 + tint) if tint < 0 else v + (255-v)*tint) for v in channels]
        return "#" + "".join(f"{max(0,min(255,v)):02x}" for v in channels)
    except (ValueError, IndexError, TypeError):
        return fallback


def display_value(value, fmt="General"):
    """Common Excel display formats; PDF preview uses the Office rendering engine."""
    if value is None: return ""
    if isinstance(value, bool): return "TRUE" if value else "FALSE"
    if isinstance(value, (datetime, date, time)):
        if isinstance(value, time): return value.strftime("%H:%M:%S")
        code = str(fmt).lower()
        if "h" in code or "s" in code:
            return value.strftime("%d/%m/%Y %H:%M") if isinstance(value, datetime) else value.isoformat()
        if code.startswith("yyyy"): return value.strftime("%Y-%m-%d")
        if code.startswith("mm") or code.startswith("m/"): return value.strftime("%m/%d/%Y")
        return value.strftime("%d/%m/%Y")
    if not isinstance(value, (int, float)) or not math.isfinite(value): return str(value)
    sections = str(fmt).split(";")
    code = sections[1] if value < 0 and len(sections) > 1 else sections[2] if value == 0 and len(sections) > 2 else sections[0]
    if code.lower() in ("general", "@"): return str(value) if isinstance(value, int) else f"{value:.12g}"
    literal = re.findall(r'"([^"]*)"', code)
    numeric = re.sub(r'"[^"]*"|\[[^\]]*\]|\\.|_.|\*.', "", code)
    if not re.search(r"[0#?]", numeric): return "".join(literal) or str(value)
    percent = "%" in numeric
    decimal = re.search(r"\.([0#?]+)", numeric)
    precision = min(12, len(decimal.group(1))) if decimal else 0
    number = abs(value) if value < 0 and len(sections) > 1 else value
    if percent: number *= 100
    if re.search(r"[Ee][+-]0", numeric): text = f"{number:.{precision}E}"
    else:
        text = format(number, ("," if "," in numeric else "") + f".{precision}f")
        if not decimal and re.fullmatch(r"0+", numeric): text = text.zfill(len(numeric))
    if percent: text += "%"
    if "(" in numeric and value < 0: text = "(" + text + ")"
    currency = re.search(r"[$€£¥₹﷼]", code)
    locale_currency = re.search(r"\[\$([^\]-]+)", code)
    prefix = (locale_currency.group(1) if locale_currency else currency.group(0) if currency else "")
    # Quoted units stay visible; values, formulas and source number formats stay untouched.
    unit = " ".join(literal)
    return (prefix + " " if prefix and prefix not in unit else "") + text + (" " + unit if unit else "")


def column_dimension(sheet, column):
    for dimension in sheet.column_dimensions.values():
        if dimension.min and dimension.max and dimension.min <= column <= dimension.max:
            return dimension
    return sheet.column_dimensions.get(get_column_letter(column))


def sheet_html(book, values, sheet_name, start=1, count=100, formulas=False):
    sheet, cached = book[sheet_name], values[sheet_name]
    if count > 200 or start < 1:
        raise WorkspaceError("نطاق العرض غير صالح.")
    end, columns = min(sheet.max_row, start + count - 1), min(60, sheet.max_column)
    palette = theme_colors(book)
    visible_columns = [c for c in range(1, columns+1) if not (column_dimension(sheet,c) and column_dimension(sheet,c).hidden)]
    visible_rows = [r for r in range(start, end+1) if not sheet.row_dimensions[r].hidden]
    merged, covered = {}, set()
    for area in sheet.merged_cells.ranges:
        rs = [r for r in visible_rows if area.min_row <= r <= area.max_row]
        cs = [c for c in visible_columns if area.min_col <= c <= area.max_col]
        if rs and cs:
            merged[(rs[0], cs[0])] = (len(rs), len(cs), sheet.cell(area.min_row, area.min_col))
            covered.update((r,c) for r in rs for c in cs if (r,c) != (rs[0],cs[0]))
    rtl = bool(sheet.sheet_view.rightToLeft)
    widths = []
    for col in visible_columns:
        dimension = column_dimension(sheet,col)
        width = (dimension.width if dimension else None) or sheet.sheet_format.defaultColWidth or 13
        widths.append(max(28,min(500,round(width*7+5))))
    html = ['<!doctype html><html><head><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'">',
        '<style>body{margin:0;background:#fff;font-family:Arial,sans-serif;color:#17232e}.scroll{overflow:auto;max-height:610px;border:1px solid #dbe2e8;border-radius:10px}table{border-collapse:collapse;table-layout:fixed}th{font:12px Arial;background:#f2f5f7;color:#5d6a76;border:1px solid #d9dfe4;position:sticky;top:0;z-index:2;height:25px}th.row{position:sticky;inset-inline-start:0;z-index:1;width:40px;min-width:40px}td{padding:4px 7px;overflow:hidden;overflow-wrap:break-word;box-sizing:border-box;unicode-bidi:plaintext}td.missing{color:#97651a;background:#fff8e9}td.error{color:#a32432}</style></head><body>',
        '<div class="scroll" dir="' + ('rtl' if rtl else 'ltr') + f'"><table style="width:{sum(widths)+40}px"><colgroup><col style="width:40px">']
    for width in widths:
        html.append(f'<col style="width:{width}px">')
    html.append('</colgroup><thead><tr><th></th>')
    html.extend('<th>' + get_column_letter(c) + '</th>' for c in visible_columns)
    html.append('</tr></thead><tbody>')
    formula_rows, missing = [], 0
    for row in visible_rows:
        height = sheet.row_dimensions[row].height or sheet.sheet_format.defaultRowHeight or 15
        html.append(f'<tr style="height:{max(22,min(500,height*4/3)):.0f}px"><th class="row">{row}</th>')
        for column in visible_columns:
            if (row,column) in covered: continue
            rowspan, colspan, cell = merged.get((row,column), (1,1,sheet.cell(row,column)))
            formula = cell.value if cell.data_type == "f" else None
            value = cached[cell.coordinate].value if formula else cell.value
            unavailable = bool(formula and value is None and cached[cell.coordinate].data_type != "str")
            if formula:
                missing += unavailable
                formula_rows.append({"الخلية": cell.coordinate, "الصيغة": str(formula), "النتيجة": "غير محسوبة" if unavailable else display_value(value, cell.number_format)})
            text = str(formula) if formulas and formula else "غير محسوبة" if unavailable else display_value(value, cell.number_format)
            align = cell.alignment
            horizontal = align.horizontal if align.horizontal in ("left","right","center","justify") else "right" if isinstance(value,(int,float)) or rtl else "left"
            font = re.sub(r"[^\w .,-]", "", str(cell.font.name or "Arial"))
            css = [f"font-family:'{font}',Arial,sans-serif", f"font-size:{max(8,min(48,cell.font.sz or 11))}pt",
                   "color:" + color_hex(cell.font.color, palette, "#17232e"), "text-align:" + horizontal,
                   "vertical-align:" + {"top":"top","center":"middle","bottom":"bottom"}.get(align.vertical,"bottom"),
                   "white-space:" + ("pre-wrap" if align.wrap_text else "pre"), "font-weight:" + ("700" if cell.font.bold else "400")]
            if cell.font.italic: css.append("font-style:italic")
            if cell.font.underline: css.append("text-decoration:underline")
            if cell.fill.patternType == "solid": css.append("background:" + color_hex(cell.fill.fgColor,palette,"#ffffff"))
            for side in ("top","right","bottom","left"):
                edge = getattr(cell.border,side)
                weight = 2 if edge and edge.style in ("medium","thick","double") else 1
                border_color = color_hex(edge.color,palette,"#aeb9c2") if edge and edge.style else "#e3e8ec" if sheet.sheet_view.showGridLines is not False else "transparent"
                css.append(f"border-{side}:{weight}px solid {border_color}")
            kind = "missing" if unavailable else "error" if isinstance(value,str) and value.startswith(("#REF!","#DIV/0!","#VALUE!","#NAME?","#N/A","#NUM!")) else ""
            direction = ' dir="ltr"' if formulas and formula or isinstance(value,(int,float,date,datetime,time)) else ' dir="auto"'
            tooltip = str(formula) if formula else cell.coordinate + " · " + text
            html.append(f'<td rowspan="{rowspan}" colspan="{colspan}" class="{kind}" title="{escape(tooltip,quote=True)}" style="{escape(";".join(css),quote=True)}"{direction}>{escape(text)}</td>')
        html.append('</tr>')
    html.append('</tbody></table></div></body></html>')
    return "".join(html), formula_rows, missing


def edited_excel(raw, sheets):
    """Apply cell changes to a full workbook, retaining styles, formulas and other sheets."""
    book = open_excel(raw)
    try:
        for item in sheets:
            if item["name"] not in book.sheetnames:
                continue
            sheet = book[item["name"]]
            for r, row in enumerate(item["rows"], 1):
                for c, value in enumerate(row, 1):
                    value = str(value if value is not None else "")
                    cell = sheet.cell(r,c)
                    if cell.__class__.__name__ == "MergedCell" or cell_text(cell.value) == value:
                        continue
                    if value.startswith("="):
                        if not safe_formula(value):
                            raise WorkspaceError(f"الصيغة في {sheet.title}!{cell.coordinate} تستخدم اتصالًا خارجيًا غير مدعوم. استخدم صيغة محلية.")
                        cell.value = value
                    elif not value:
                        cell.value = None
                    elif isinstance(cell.value,(datetime,date)):
                        try: cell.value = datetime.fromisoformat(value)
                        except ValueError: cell.value, cell.data_type = value, "s"
                    elif re.fullmatch(r"-?(?:0|[1-9]\d*)(?:\.\d+)?", value) or isinstance(cell.value,(int,float)) and re.fullmatch(r"-?[\d,]+(?:\.\d+)?",value):
                        numeric = value.replace(",", "")
                        cell.value = float(numeric) if "." in numeric else int(numeric)
                    else:
                        cell.value, cell.data_type = value, "s"
        out = io.BytesIO()
        book.save(out)
        return out.getvalue()
    finally:
        book.close()
