"""Durable, per-account AI conversations and reviewed, atomic action proposals."""
from __future__ import annotations

import copy
import json
import time
from datetime import date

from sqlalchemy import (Column, Float, Integer, MetaData, String, Table, Text,
                        delete, func, insert, select, update)

from workspace import WorkspaceError, Forbidden, Conflict, STATUSES, PRIORITIES, now_iso, uid, dumps, validate_task_schedule

metadata = MetaData()
threads = Table("gday_ai_threads", metadata, Column("id", String(64), primary_key=True),
    Column("owner_id", String(64), nullable=False, index=True), Column("project_id", String(160), nullable=False),
    Column("title", String(160), nullable=False), Column("at", String(40), nullable=False))
messages = Table("gday_ai_messages", metadata, Column("id", String(64), primary_key=True),
    Column("thread_id", String(64), nullable=False, index=True), Column("role", String(20), nullable=False),
    Column("content", Text, nullable=False), Column("meta", Text, nullable=False), Column("at", String(40), nullable=False))
runs = Table("gday_ai_runs", metadata, Column("id", String(64), primary_key=True),
    Column("thread_id", String(64), nullable=False, index=True), Column("owner_id", String(64), nullable=False, index=True),
    Column("day", String(10), nullable=False, index=True), Column("started", Float, nullable=False),
    Column("status", String(20), nullable=False), Column("model", String(120), nullable=False),
    Column("guards", Text, nullable=False), Column("sources", Text, nullable=False),
    Column("proposal", Text, nullable=False), Column("decision", String(20), nullable=False))
usage_days = Table("gday_ai_usage", metadata, Column("owner_id", String(64), primary_key=True),
    Column("day", String(10), primary_key=True), Column("count", Integer, nullable=False))


def checked_text(value, label, maximum, required=False):
    if not isinstance(value, str) or len(value) > maximum or required and not value.strip():
        raise WorkspaceError("تحقق من " + label + ".")
    return value.strip()


def normalize_actions(raw, state, project_id, guards):
    if not isinstance(raw, list) or len(raw) > 8:
        raise WorkspaceError("المقترح أكبر من الحد المسموح.")
    members = {m["id"] for m in state["members"]}
    task_index = {t["id"]: t for t in state["tasks"] if t.get("projectId") == project_id}
    result, targets = [], set()
    for action in raw:
        if not isinstance(action, dict) or set(action) - {"kind", "target_id", "values"}:
            raise WorkspaceError("يتضمن المقترح حقولًا غير مسموحة.")
        kind, values = action.get("kind"), action.get("values")
        if not isinstance(kind, str) or not isinstance(action.get("target_id", ""), str):
            raise WorkspaceError("نوع الإجراء أو مرجعه غير صالح.")
        if not isinstance(values, dict) or not values:
            raise WorkspaceError("قيم المقترح غير صالحة.")
        values = copy.deepcopy(values)
        target, version = "", None
        if kind in ("task_create", "task_update"):
            allowed = {"title", "notes", "assigneeId", "status", "priority", "dueDate", "dueTime", "reminderEnabled", "reminderMinutes", "estimatedMinutes"}
            if set(values) - allowed:
                raise WorkspaceError("حقول المهمة المقترحة غير مسموحة.")
            if kind == "task_create":
                values = {"title": "", "notes": "", "assigneeId": "", "status": "todo", "priority": "medium",
                          "dueDate": "", "estimatedMinutes": 30} | values
                target = uid("t_")
            else:
                target = action.get("target_id", "")
                if target not in task_index or target not in guards.get("tasks", {}):
                    raise WorkspaceError("المهمة المقترحة خارج السياق الذي قرأه المساعد.")
                version = guards["tasks"][target]
            for key, limit in (("title", 500), ("notes", 12000)):
                if key in values:
                    values[key] = checked_text(values[key], "عنوان المهمة" if key == "title" else "الملاحظات", limit, key == "title")
            if "assigneeId" in values and (not isinstance(values["assigneeId"], str) or values["assigneeId"] not in members | {""}):
                raise WorkspaceError("المسؤول المقترح غير موجود.")
            if "status" in values and (not isinstance(values["status"], str) or values["status"] not in STATUSES):
                raise WorkspaceError("مرحلة المهمة المقترحة غير صالحة.")
            if "priority" in values and (not isinstance(values["priority"], str) or values["priority"] not in PRIORITIES):
                raise WorkspaceError("أولوية المهمة المقترحة غير صالحة.")
            if "dueDate" in values:
                due = values["dueDate"]
                try:
                    if not isinstance(due, str) or due and date.fromisoformat(due).isoformat() != due:
                        raise ValueError()
                except ValueError:
                    raise WorkspaceError("موعد المهمة المقترح غير صالح.") from None
            if "estimatedMinutes" in values and (type(values["estimatedMinutes"]) is not int or not 0 <= values["estimatedMinutes"] <= 100000):
                raise WorkspaceError("وقت المهمة المقترح غير صالح.")
            validate_task_schedule((task_index[target] if kind == "task_update" else {}) | values)
        elif kind == "document_create":
            if set(values) != {"title", "text"}:
                raise WorkspaceError("المستند المقترح يحتاج عنوانًا ونصًا فقط.")
            values["title"] = checked_text(values["title"], "عنوان المستند", 200, True)
            values["text"] = checked_text(values["text"], "نص المستند", 20000, True)
            target = uid("f_")
        elif kind == "handover_update":
            if set(values) - {"summary", "decisions", "next_step"} or guards.get("handover") is None:
                raise WorkspaceError("لا يمكن تحديث تسليم لم يقرأه المساعد.")
            for key in values:
                values[key] = checked_text(values[key], "تسليم اليوم", 6000)
            target, version = "handover", guards["handover"]
        else:
            raise WorkspaceError("نوع الإجراء المقترح غير مسموح.")
        if kind in ("task_update", "handover_update") and target in targets:
            raise WorkspaceError("يتضمن المقترح تحديثًا مكررًا للعنصر نفسه.")
        targets.add(target)
        result.append({"kind": kind, "id": target, "version": version, "values": values})
    return result


class AIStore:
    def __init__(self, store):
        self.store = store
        metadata.create_all(store.engine)

    def _thread(self, conn, actor, thread_id):
        row = conn.execute(select(threads).where(threads.c.id == thread_id, threads.c.owner_id == actor["id"])).mappings().first()
        if not row:
            raise Forbidden("المحادثة غير موجودة أو ليست لحسابك.")
        return dict(row)

    def list_threads(self, token, project_id):
        with self.store.engine.connect() as conn:
            actor = self.store._actor(conn, token)
            return [dict(r) for r in conn.execute(select(threads).where(threads.c.owner_id == actor["id"],
                threads.c.project_id == project_id).order_by(threads.c.at.desc()).limit(100)).mappings()]

    def create_thread(self, token, project_id):
        with self.store.transaction() as conn:
            actor = self.store._actor(conn, token)
            state, _ = self.store._state(conn)
            if project_id not in {p["id"] for p in state["projects"]}:
                raise WorkspaceError("المشروع غير موجود.")
            count = conn.execute(select(func.count()).select_from(threads).where(threads.c.owner_id == actor["id"])).scalar_one()
            if count >= 100:
                raise WorkspaceError("لديك 100 محادثة؛ صدّر واحذف بعض المحادثات قبل إنشاء واحدة جديدة.")
            ident = uid("ai_")
            conn.execute(insert(threads).values(id=ident, owner_id=actor["id"], project_id=project_id, title="محادثة جديدة", at=now_iso()))
            return ident

    def history(self, token, thread_id):
        with self.store.engine.connect() as conn:
            actor = self.store._actor(conn, token)
            self._thread(conn, actor, thread_id)
            rows = conn.execute(select(messages).where(messages.c.thread_id == thread_id).order_by(messages.c.at, messages.c.id)).mappings()
            return [dict(r) | {"meta": json.loads(r["meta"])} for r in rows]

    def daily_count(self, token):
        with self.store.engine.connect() as conn:
            actor = self.store._actor(conn, token)
            return conn.execute(select(usage_days.c.count).where(usage_days.c.owner_id == actor["id"], usage_days.c.day == now_iso()[:10])).scalar_one_or_none() or 0

    def begin(self, token, thread_id, request_id, question, model, context, sources, expected_revision, daily_limit):
        question = checked_text(question, "السؤال (حتى 4000 حرف)", 4000, True)
        if not isinstance(request_id, str) or not 12 <= len(request_id) <= 64:
            raise WorkspaceError("معرف الطلب غير صالح.")
        with self.store.transaction() as conn:
            actor = self.store._actor(conn, token)
            thread = self._thread(conn, actor, thread_id)
            state, revision = self.store._state(conn)
            if revision != expected_revision:
                raise Conflict("تغير السياق قبل الإرسال؛ أعد المحاولة لقراءة أحدث بيانات.")
            if thread["project_id"] != context.get("project", {}).get("id"):
                raise Forbidden("سياق المحادثة لا يطابق مشروعها.")
            if conn.execute(select(runs.c.id).where(runs.c.id == request_id)).first():
                raise Conflict("هذا الطلب أُرسل مسبقًا؛ راجع الرد المحفوظ.")
            active = conn.execute(select(runs.c.id).where(runs.c.thread_id == thread_id, runs.c.status == "pending", runs.c.started > time.time()-120)).first()
            if active:
                raise Conflict("يوجد طلب قيد المعالجة في المحادثة؛ انتظر الرد قبل إرسال طلب آخر.")
            count = conn.execute(select(usage_days.c.count).where(usage_days.c.owner_id == actor["id"], usage_days.c.day == now_iso()[:10])).scalar_one_or_none() or 0
            if count >= daily_limit:
                raise WorkspaceError("وصل حسابك إلى الحد اليومي لطلبات المساعد. يبدأ اليوم الجديد بتوقيت الرياض.")
            message_count = conn.execute(select(func.count()).select_from(messages).where(messages.c.thread_id == thread_id)).scalar_one()
            if message_count >= 200:
                raise WorkspaceError("وصلت المحادثة إلى 200 رسالة؛ افتح محادثة جديدة.")
            if count:
                conn.execute(update(usage_days).where(usage_days.c.owner_id == actor["id"], usage_days.c.day == now_iso()[:10]).values(count=count+1))
            else:
                conn.execute(insert(usage_days).values(owner_id=actor["id"], day=now_iso()[:10], count=1))
            guards = {"tasks": {t["id"]: t["version"] for t in context.get("tasks", [])},
                      "handover": context.get("handover_version")}
            conn.execute(insert(runs).values(id=request_id, thread_id=thread_id, owner_id=actor["id"], day=now_iso()[:10],
                started=time.time(), status="pending", model=model, guards=dumps(guards), sources=dumps(sources), proposal="[]", decision="none"))
            conn.execute(insert(messages).values(id=uid(), thread_id=thread_id, role="user", content=question,
                meta=dumps({"run_id": request_id}), at=now_iso()))
            conn.execute(update(threads).where(threads.c.id == thread_id).values(title=question[:100], at=now_iso()))

    def finish(self, token, run_id, answer, raw_actions, usage, warnings=None):
        with self.store.transaction() as conn:
            actor = self.store._actor(conn, token)
            run = conn.execute(select(runs).where(runs.c.id == run_id, runs.c.owner_id == actor["id"])).mappings().first()
            if not run or run["status"] != "pending":
                raise Conflict("الطلب غير موجود أو حُفظ رده بالفعل.")
            thread = self._thread(conn, actor, run["thread_id"])
            state, _ = self.store._state(conn)
            proposal, proposal_error = [], ""
            try:
                if raw_actions:
                    self.store.require(actor, "edit")
                    proposal = normalize_actions(raw_actions, state, thread["project_id"], json.loads(run["guards"]))
            except WorkspaceError as exc:
                proposal_error = str(exc)
            decision = "pending" if proposal else "none"
            conn.execute(update(runs).where(runs.c.id == run_id).values(status="complete", proposal=dumps(proposal), decision=decision))
            meta = {"run_id": run_id, "model": run["model"], "usage": usage, "sources": json.loads(run["sources"]),
                    "warnings": warnings or [], "proposal_error": proposal_error, "proposal_count": len(proposal)}
            conn.execute(insert(messages).values(id=uid(), thread_id=run["thread_id"], role="assistant", content=answer,
                meta=dumps(meta), at=now_iso()))
            self.store._log(conn, actor, "استجابة مساعد AI", run["model"] + " · " + str(len(proposal)) + " اقتراح")

    def fail(self, token, run_id, message):
        with self.store.transaction() as conn:
            actor = self.store._actor(conn, token)
            run = conn.execute(select(runs).where(runs.c.id == run_id, runs.c.owner_id == actor["id"])).mappings().first()
            if run and run["status"] == "pending":
                conn.execute(update(runs).where(runs.c.id == run_id).values(status="failed"))
                conn.execute(insert(messages).values(id=uid(), thread_id=run["thread_id"], role="assistant", content=message[:1000],
                    meta=dumps({"run_id": run_id, "error": True}), at=now_iso()))

    def proposal(self, token, run_id):
        with self.store.engine.connect() as conn:
            actor = self.store._actor(conn, token)
            run = conn.execute(select(runs).where(runs.c.id == run_id, runs.c.owner_id == actor["id"])).mappings().first()
            if not run:
                raise Forbidden("المقترح غير متاح لحسابك.")
            return json.loads(run["proposal"]), run["decision"]

    def decide(self, token, run_id, apply=False):
        with self.store.transaction() as conn:
            actor = self.store._actor(conn, token)
            run = conn.execute(select(runs).where(runs.c.id == run_id, runs.c.owner_id == actor["id"])).mappings().first()
            if not run:
                raise Forbidden("المقترح غير متاح لحسابك.")
            if run["decision"] != "pending":
                return False
            if apply:
                self.store.require(actor, "edit")
                thread = self._thread(conn, actor, run["thread_id"])
                state, revision = self.store._state(conn)
                if thread["project_id"] not in {p["id"] for p in state["projects"]}:
                    raise Conflict("المشروع حُذف؛ اطلب اقتراحًا للمشروع الحالي.")
                proposal = json.loads(run["proposal"])
                for item in proposal:
                    kind = item["kind"]
                    if kind == "task_update":
                        record = next((t for t in state["tasks"] if t["id"] == item["id"] and t.get("projectId") == thread["project_id"]), None)
                        if not record or record.get("version", 1) != item["version"]:
                            raise Conflict("تغيرت مهمة منذ الاقتراح؛ اطلب مقترحًا جديدًا حتى لا تُستبدل تعديلات الفريق.")
                    elif kind == "handover_update" and state["handover"].get("version", 1) != item["version"]:
                        raise Conflict("تغير تسليم اليوم منذ الاقتراح؛ اطلب مقترحًا محدثًا.")
                    if item["values"].get("assigneeId") and item["values"]["assigneeId"] not in {m["id"] for m in state["members"]}:
                        raise Conflict("المسؤول لم يعد موجودًا؛ اطلب مقترحًا محدثًا.")
                self.store._snapshot(conn, state, "قبل تطبيق مقترح AI")
                for item in proposal:
                    kind, values = item["kind"], item["values"]
                    common = {"updatedAt": now_iso(), "updatedBy": actor["member_id"], "aiRunId": run_id}
                    if kind == "task_create":
                        record = values | common | {"id": item["id"], "projectId": thread["project_id"], "version": 1,
                            "createdBy": actor["member_id"], "comments": [], "subtasks": []}
                        if record["status"] == "done": record["completedAt"] = now_iso()
                        state["tasks"].append(record)
                    elif kind == "task_update":
                        record = next(t for t in state["tasks"] if t["id"] == item["id"])
                        was_done = record.get("status") == "done"
                        record.update(values | common | {"version": item["version"]+1})
                        if record.get("status") == "done" and not was_done: record["completedAt"] = now_iso()
                        elif record.get("status") != "done": record.pop("completedAt", None)
                    elif kind == "document_create":
                        state["files"].append(values | common | {"id": item["id"], "projectId": thread["project_id"],
                            "type": "doc", "version": 1, "comments": [], "starred": False, "legacy": False})
                    elif kind == "handover_update":
                        state["handover"].update(values | {"updated_at": now_iso(), "updated_by": actor["member_id"],
                            "version": item["version"]+1, "aiRunId": run_id})
                self.store._save(conn, state, revision)
                self.store._log(conn, actor, "تطبيق مقترح AI بعد المراجعة", run_id)
            conn.execute(update(runs).where(runs.c.id == run_id).values(decision="applied" if apply else "dismissed"))
            return True

    def delete_thread(self, token, thread_id):
        with self.store.transaction() as conn:
            actor = self.store._actor(conn, token)
            self._thread(conn, actor, thread_id)
            if conn.execute(select(runs.c.id).where(runs.c.thread_id == thread_id, runs.c.status == "pending", runs.c.started > time.time()-120)).first():
                raise Conflict("انتظر انتهاء الطلب الجاري قبل حذف المحادثة.")
            conn.execute(delete(messages).where(messages.c.thread_id == thread_id))
            conn.execute(delete(runs).where(runs.c.thread_id == thread_id))
            conn.execute(delete(threads).where(threads.c.id == thread_id))
            self.store._log(conn, actor, "حذف محادثة AI الخاصة", thread_id)

    def export_thread(self, token, thread_id):
        return dumps({"format": "gday.ai.conversation", "exported_at": now_iso(), "messages": self.history(token, thread_id)}).encode()
