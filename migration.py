"""Additive migration. Login accounts, roles and existing records stay untouched."""
import base64
import copy
import hashlib
import json
import re
import unicodedata

from workspace import WorkspaceError, prepare_import, uid
from filetools import file_text, file_sheets


def label(value):
    value = unicodedata.normalize("NFKC", str(value or "")).strip().casefold()
    value = re.sub(r"^(?:د\.|دكتور\s+|أ\.|ا\.|أستاذ\s+)", "", value)
    value = value.translate(str.maketrans("أإآى", "اااي"))
    return re.sub(r"[\W_]+", "", value)


def file_fingerprint(record):
    if record.get("type") == "sheet":
        return hashlib.sha256(json.dumps(file_sheets(record), ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    if record.get("object"):
        return record["object"]["sha256"]
    if record.get("blob"):
        return hashlib.sha256(base64.b64decode(record["blob"])).hexdigest()
    if record.get("content"):
        return hashlib.sha256(record["content"].encode()).hexdigest()
    return hashlib.sha256(file_text(record).encode()).hexdigest()


def build_merge(raw, state, project_id):
    incoming = prepare_import(raw)["data"]
    if project_id not in {p["id"] for p in state["projects"]}:
        raise WorkspaceError("اختر مشروعًا موجودًا لاستقبال المحتوى.")
    additions = {"tasks": [], "files": [], "stakeholders": []}
    summary = {"tasks_added": 0, "tasks_skipped": 0, "files_added": 0, "files_skipped": 0,
               "contacts_added": 0, "contacts_skipped": 0, "unassigned": 0, "messages_archived": 0}
    source_members = {m["id"]: m["name"] for m in incoming["members"]}
    def member_id(source_id):
        exact = [m for m in state["members"] if m["id"] == source_id]
        if exact:
            return exact[0]["id"]
        matches = [m for m in state["members"] if label(m["name"]) == label(source_members.get(source_id, ""))]
        return matches[0]["id"] if len(matches) == 1 else ""
    project_map = {}
    for project in incoming["projects"]:
        matches = [p for p in state["projects"] if p["id"] == project["id"] or label(p["name"]) == label(project["name"])]
        project_map[project["id"]] = matches[0]["id"] if len(matches) == 1 else project_id
    source_projects = {p["id"]: p["name"] for p in incoming["projects"]}
    contacts = {(label(c["name"]), label(c.get("org"))): c["id"] for c in state["stakeholders"]}
    contact_map = {}
    for source in incoming["stakeholders"]:
        signature = label(source["name"]), label(source.get("org"))
        if signature in contacts:
            contact_map[source["id"]] = contacts[signature]
            summary["contacts_skipped"] += 1
        else:
            record = copy.deepcopy(source) | {"id": uid("stk_"), "source_id": source["id"]}
            additions["stakeholders"].append(record)
            contacts[signature] = record["id"]
            contact_map[source["id"]] = record["id"]
            summary["contacts_added"] += 1
    hashes = {file_fingerprint(f): f["id"] for f in state["files"]}
    file_map = {}
    for source in incoming["files"]:
        fingerprint = file_fingerprint(source)
        if fingerprint in hashes:
            file_map[source["id"]] = hashes[fingerprint]
            summary["files_skipped"] += 1
            continue
        record = copy.deepcopy(source) | {"id": uid("f_"), "source_id": source["id"], "projectId": project_map.get(source.get("projectId"), project_id)}
        if record.get("content") and not record.get("blob"):
            record.update(blob=base64.b64encode(record["content"].encode()).decode(), originalName=record["title"].rsplit(".", 1)[0] + ".html")
        record["text"] = file_text(record)
        for comment in record.get("comments", []):
            comment["authorId"] = member_id(comment.get("authorId"))
        additions["files"].append(record)
        file_map[source["id"]] = record["id"]
        hashes[fingerprint] = record["id"]
        summary["files_added"] += 1
    known_tasks = {(label(t["title"]), t.get("dueDate", ""), t.get("projectId", "")) for t in state["tasks"]}
    for source in incoming["tasks"]:
        target = project_map.get(source.get("projectId"), project_id)
        signature = label(source["title"]), source.get("dueDate", ""), target
        if signature in known_tasks:
            summary["tasks_skipped"] += 1
            continue
        record = copy.deepcopy(source) | {"id": uid("t_"), "source_id": source["id"], "projectId": target,
            "assigneeId": member_id(source.get("assigneeId")), "stakeholderId": contact_map.get(source.get("stakeholderId"), ""),
            "attachedFileId": file_map.get(source.get("attachedFileId"), "")}
        notes = record.get("notes", "")
        source_project = source_projects.get(source.get("projectId"), "")
        if source_project and target == project_id:
            notes += "\nالمشروع في الملف الأصلي: " + source_project
        if not record["assigneeId"] and source.get("assigneeId"):
            summary["unassigned"] += 1
            notes += "\nالمسؤول في الملف الأصلي: " + source_members.get(source["assigneeId"], source["assigneeId"])
        record["notes"] = notes.strip()
        for comment in record.get("comments", []):
            comment["authorId"] = member_id(comment.get("authorId"))
        additions["tasks"].append(record)
        known_tasks.add(signature)
        summary["tasks_added"] += 1
    # Preserve history as an archive, without impersonating past authors in chat.
    messages = incoming["messages"]
    message_texts = [m["text"] for m in messages]
    archived_already = messages and any(all(text in file_text(f) for text in message_texts) for f in state["files"] if f.get("type") == "doc")
    if messages and not archived_already:
        body = "\n\n".join(source_members.get(m.get("authorId"), "عضو سابق") + " | " + str(m.get("time", "")) + "\n" + m["text"] for m in messages)
        additions["files"].append({"id": uid("f_"), "title": "أرشيف المحادثات المستوردة", "type": "doc", "projectId": project_id,
                                   "text": body, "comments": [], "legacy": True})
        summary["files_added"] += 1
        summary["messages_archived"] = len(messages)
    return additions, summary
