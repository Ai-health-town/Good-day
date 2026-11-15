"""Virtual library folders. Paths are metadata, never filesystem destinations."""
from __future__ import annotations

import base64
import hashlib
import re
import unicodedata

MAX_FOLDERS = 1000
MAX_DEPTH = 12
MAX_UPLOADS = 200
MAX_BATCH_BYTES = 64 * 1024 * 1024


def folder_name(value):
    if not isinstance(value, str):
        raise ValueError("اكتب اسم المجلد.")
    value = unicodedata.normalize("NFC", value).strip()
    if (not value or len(value) > 180 or value in (".", "..") or
            re.search(r"[\\/\x00-\x1f\x7f]", value)):
        raise ValueError("اسم المجلد من 1 إلى 180 حرفًا، دون شرطة مسار أو رموز تحكم.")
    return value


def upload_path(value):
    if not isinstance(value, str) or len(value) > 2048:
        raise ValueError("مسار الملف غير صالح أو طويل جدًا.")
    value = unicodedata.normalize("NFC", value.replace("\\", "/"))
    if value.startswith("/") or re.match(r"^[A-Za-z]:", value):
        raise ValueError("يجب أن يكون مسار الملف داخل المجلد المختار.")
    parts = value.split("/")
    if len(parts) > MAX_DEPTH + 1:
        raise ValueError(f"الحد الأقصى {MAX_DEPTH} مستوى من المجلدات.")
    for part in parts:
        folder_name(part)
    return parts


def folder_labels(folders, projects=()):
    index = {f["id"]: f for f in folders}
    projects = {p["id"]: p["name"] for p in projects}
    labels = {}
    for ident, record in index.items():
        names, current, seen = [], ident, set()
        while current in index and current not in seen:
            seen.add(current)
            item = index[current]
            names.append(item["name"])
            current = item.get("parentId", "")
        path = " / ".join(reversed(names))
        labels[ident] = (projects.get(record.get("projectId"), "") + " / " if projects else "") + path
    return labels


def validate_filing(state):
    folders = state.get("folders", [])
    if not isinstance(folders, list) or len(folders) > MAX_FOLDERS:
        raise ValueError("تجاوزت المكتبة الحد الأقصى للمجلدات.")
    projects = {p["id"] for p in state["projects"]}
    index, names = {}, set()
    for folder in folders:
        ident = folder.get("id")
        if not isinstance(ident, str) or not ident or len(ident) > 160 or ident in index:
            raise ValueError("معرّف مجلد ناقص أو مكرر.")
        name = folder_name(folder.get("name"))
        project, parent = folder.get("projectId"), folder.get("parentId", "")
        if not isinstance(project, str) or project not in projects or not isinstance(parent, str):
            raise ValueError("اختر مشروعًا ومجلدًا موجودين.")
        signature = project, parent, name.casefold()
        if signature in names:
            raise ValueError("يوجد مجلد بهذا الاسم في المكان نفسه.")
        names.add(signature)
        index[ident] = folder
    for ident, folder in index.items():
        current, seen = ident, set()
        while current:
            if current in seen or len(seen) >= MAX_DEPTH:
                raise ValueError("تسلسل المجلدات دائري أو أعمق من الحد المسموح.")
            parent = index.get(current)
            if not parent or parent.get("projectId") != folder["projectId"]:
                raise ValueError("المجلد الأب غير موجود أو يتبع مشروعًا آخر.")
            seen.add(current)
            current = parent.get("parentId", "")
    for record in state["files"]:
        ident = record.get("folderId", "")
        if not isinstance(ident, str):
            raise ValueError("مجلد الملف غير صالح.")
        if ident and (ident not in index or index[ident]["projectId"] != record.get("projectId")):
            raise ValueError("مجلد الملف لم يعد موجودًا أو يتبع مشروعًا آخر؛ حدّث الصفحة.")


def prepare_uploads(uploads, project_id, *, directory=False):
    """Bound the batch before parsing; retain supported previews and other originals."""
    from filetools import parse_upload
    from workspace import WorkspaceError
    records, total, ignored = [], 0, 0
    for number, (path, raw) in enumerate(uploads, 1):
        if number > MAX_UPLOADS:
            raise WorkspaceError(f"ارفع حتى {MAX_UPLOADS} ملف في الدفعة الواحدة.")
        try:
            parts = upload_path(path)
        except ValueError as exc:
            raise WorkspaceError(str(exc)) from None
        if not directory and len(parts) != 1:
            raise WorkspaceError("اختر «مجلد كامل» للحفاظ على مسارات المجلدات.")
        if parts[-1] in (".DS_Store", "Thumbs.db", "desktop.ini") or "__MACOSX" in parts or parts[-1].startswith("._"):
            ignored += 1
            continue
        total += len(raw)
        if total > MAX_BATCH_BYTES:
            raise WorkspaceError("حجم الدفعة يتجاوز 64 ميجابايت؛ قسّم المجلد إلى دفعات أصغر.")
        try:
            record = parse_upload(parts[-1], raw, project_id, allow_attachment=True)
        except WorkspaceError as exc:
            raise WorkspaceError(parts[-1] + ": " + str(exc)) from None
        record["uploadPath"] = "/".join(parts[:-1]) if directory else ""
        records.append(record)
    return records, ignored


def original_fingerprint(record):
    if record.get("object"):
        return record["object"]["sha256"]
    if record.get("blob"):
        return hashlib.sha256(base64.b64decode(record["blob"], validate=True)).hexdigest()
    from migration import file_fingerprint
    return file_fingerprint(record)


def upload_identity(record):
    return (record.get("projectId", ""), record.get("folderId", ""),
            record["title"].casefold(), original_fingerprint(record))


def rehome_folders(state, source_id, target_id):
    """Keep folder IDs and links when moving/deleting a project; avoid name collisions."""
    occupied = {f["name"].casefold() for f in state.get("folders", [])
                if f.get("projectId") == target_id and not f.get("parentId")}
    for folder in state.get("folders", []):
        if folder.get("projectId") == source_id and not folder.get("parentId"):
            original, number = folder["name"], 2
            while folder["name"].casefold() in occupied:
                folder["name"] = original[:165] + f" ({number})"
                number += 1
            occupied.add(folder["name"].casefold())
