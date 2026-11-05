"""Private, bounded Office previews. Source bytes are never overwritten or shared."""
from __future__ import annotations

import io
import os
import re
import shutil
import signal
import subprocess
import tempfile
import threading
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from xml.etree import ElementTree as ET

from defusedxml.ElementTree import fromstring
from pypdf import PdfReader

from workspace import WorkspaceError

OFFICE_TYPES = {".docx", ".xlsx", ".xlsm", ".xls"}
MAX_INPUT = 8 * 1024 * 1024
MAX_OUTPUT = 20 * 1024 * 1024
MAX_PAGES = 120
_CONVERSION = threading.BoundedSemaphore(1)
_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_WORD = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_UNSAFE = re.compile(r"WEBSERVICE\s*\(|HYPERLINK\s*\(|RTD\s*\(|DDE\s*\(|SQL\.REQUEST|://|file:|\[(?:\d+|[^\]]+\.(?:xlsx?|xlsm|xlsb|ods))\]|\|", re.I)


class PreviewUnavailable(WorkspaceError):
    pass


@dataclass(frozen=True)
class OfficePreview:
    pdf: bytes = field(repr=False)
    workbook: bytes | None = field(default=None, repr=False)
    pages: int = 0
    external_content_disabled: bool = False


def office_available():
    return bool(shutil.which("libreoffice") or shutil.which("soffice"))


def safe_formula(value):
    """Allow ordinary local Excel formulas; never evaluate arbitrary Python."""
    return isinstance(value, str) and value.startswith("=") and not _UNSAFE.search(value)


def safe_office_copy(raw):
    """Disable active/external OOXML content in a disposable preview copy."""
    if not zipfile.is_zipfile(io.BytesIO(raw)):
        return raw, False  # Legacy XLS is controlled by the isolated Office profile.
    target = io.BytesIO()
    changed = False
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as source, zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as out:
            items = source.infolist()
            if len(items) > 5000 or sum(i.file_size for i in items) > 50 * 1024 * 1024:
                raise WorkspaceError("الملف أكبر من حد المعاينة الآمنة.")
            for item in items:
                data = source.read(item.filename)
                updated = False
                if item.filename.endswith(".rels"):
                    root = fromstring(data)
                    for rel in list(root):
                        if rel.get("TargetMode") == "External" and not rel.get("Type", "").endswith("/hyperlink"):
                            root.remove(rel)
                            updated = True
                elif item.filename.startswith("xl/") and item.filename.endswith(".xml"):
                    root = fromstring(data)
                    for cell in root.iter("{" + _NS + "}c"):
                        for formula in list(cell.findall("{" + _NS + "}f")):
                            if _UNSAFE.search(formula.text or ""):
                                cell.remove(formula)  # Preserve any saved result in <v>.
                                updated = True
                elif item.filename.startswith("word/") and item.filename.endswith(".xml"):
                    root = fromstring(data)
                    for paragraph in root.iter("{" + _WORD + "}p"):
                        instructions = list(paragraph.iter("{" + _WORD + "}instrText"))
                        command = "".join(t.text or "" for t in instructions)
                        if re.search(r"\b(INCLUDETEXT|INCLUDEPICTURE|DDEAUTO|DDE|LINK|DATABASE)\b", command, re.I):
                            for instruction in instructions:
                                instruction.text = ""
                            updated = True
                    for node in root.iter("{" + _WORD + "}fldSimple"):
                        key = "{" + _WORD + "}instr"
                        if re.search(r"\b(INCLUDETEXT|INCLUDEPICTURE|DDEAUTO|DDE|LINK|DATABASE)\b", node.get(key, ""), re.I):
                            node.set(key, "")
                            updated = True
                if updated:
                    data = ET.tostring(root, encoding="utf-8", xml_declaration=True)
                    changed = True
                out.writestr(item, data)
    except WorkspaceError:
        raise
    except Exception:
        raise PreviewUnavailable("تعذر تجهيز معاينة هذا الملف؛ الأصل ما زال متاحًا للتنزيل.") from None
    return (target.getvalue() if changed else raw), changed


def _profile(folder):
    user = folder / "user"
    user.mkdir(parents=True)
    # No trusted directories or credentials in this temporary profile.
    (user / "registrymodifications.xcu").write_text('''<?xml version="1.0" encoding="UTF-8"?>
<oor:items xmlns:oor="http://openoffice.org/2001/registry">
 <item oor:path="/org.openoffice.Office.Common/Security/Scripting">
  <prop oor:name="MacroSecurityLevel" oor:op="fuse"><value>3</value></prop>
  <prop oor:name="DisableMacrosExecution" oor:op="fuse"><value>true</value></prop>
 </item>
 <item oor:path="/org.openoffice.Office.Calc/Content/Update">
  <prop oor:name="Link" oor:op="fuse"><value>1</value></prop>
 </item>
 <item oor:path="/org.openoffice.Office.Writer/Content/Update">
  <prop oor:name="Link" oor:op="fuse"><value>1</value></prop>
 </item>
</oor:items>''', encoding="utf-8")


def _convert(binary, profile, source, output, export_filter):
    # Do not pass database URLs, API keys, proxy credentials or app secrets to Office.
    allowed = ("PATH", "LANG", "LC_ALL", "TZ", "TMPDIR", "FONTCONFIG_FILE", "FONTCONFIG_PATH", "LD_LIBRARY_PATH")
    env = {k: os.environ[k] for k in allowed if k in os.environ}
    env["SAL_USE_VCLPLUGIN"] = "svp"
    command = [binary, "-env:UserInstallation=" + profile.as_uri(), "--headless", "--nologo",
               "--nodefault", "--norestore", "--convert-to", export_filter, "--outdir", str(output), str(source)]
    try:
        process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL, env=env, start_new_session=True)
        try:
            process.communicate(timeout=55)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.communicate()
            raise PreviewUnavailable("استغرق تجهيز المعاينة وقتًا طويلًا. نزّل الأصل أو جرّب ملفًا أصغر.") from None
        if process.returncode:
            raise PreviewUnavailable("تعذر تحويل هذا الملف للعرض. تأكد من أنه سليم وغير محمي بكلمة مرور.")
    except OSError:
        raise PreviewUnavailable("محرك معاينة Office غير متاح مؤقتًا؛ يمكنك تنزيل الأصل.") from None


def render_office(raw, suffix):
    suffix = str(suffix).lower()
    if suffix not in OFFICE_TYPES or not isinstance(raw, bytes) or not raw or len(raw) > MAX_INPUT:
        raise PreviewUnavailable("صيغة الملف أو حجمه غير مناسبين لمعاينة Office.")
    binary = shutil.which("libreoffice") or shutil.which("soffice")
    if not binary:
        raise PreviewUnavailable("محرك عرض الصفحات قيد التجهيز على الاستضافة. يمكنك تنزيل الأصل أو فتح نسخة المحتوى حاليًا.")
    if not _CONVERSION.acquire(timeout=2):
        raise PreviewUnavailable("يجري تجهيز معاينة ملف آخر. أعد فتح الملف بعد قليل.")
    try:
        with tempfile.TemporaryDirectory(prefix="gday-office-") as folder:
            root = Path(folder)
            profile, output = root / "profile", root / "output"
            _profile(profile)
            output.mkdir()
            prepared, disabled = safe_office_copy(raw)
            source = root / ("document" + suffix)
            source.write_bytes(prepared)
            _convert(binary, profile, source, output, "pdf")
            pdf_path = output / "document.pdf"
            if not pdf_path.is_file() or not 0 < pdf_path.stat().st_size <= MAX_OUTPUT:
                raise PreviewUnavailable("لم ينتج المحرك معاينة صالحة ضمن حد الحجم؛ الملف الأصلي محفوظ.")
            pdf = pdf_path.read_bytes()
            try:
                pages = len(PdfReader(io.BytesIO(pdf)).pages)
            except Exception:
                raise PreviewUnavailable("تعذر التحقق من صفحات المعاينة.") from None
            if pages > MAX_PAGES:
                raise PreviewUnavailable(f"المعاينة تتجاوز {MAX_PAGES} صفحة. استخدم عرض الأوراق أو نزّل الأصل.")
            workbook = None
            if suffix in (".xlsx", ".xlsm", ".xls"):
                # A derivative with calculated values; original formulas/styles/bytes remain intact.
                _convert(binary, profile, source, output, "xlsx:Calc MS Excel 2007 XML")
                book_path = output / "document.xlsx"
                if book_path.is_file() and 0 < book_path.stat().st_size <= MAX_OUTPUT:
                    workbook = book_path.read_bytes()
            return OfficePreview(pdf, workbook, pages, disabled)
    finally:
        _CONVERSION.release()
