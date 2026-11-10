"""G'day workspace: persistence, authorization, sessions, backups and migration.

No browser data is trusted as identity. Every read/write checks a database session.
SQLite is for local use; PostgreSQL is required for durable Cloud deployments.
"""
from __future__ import annotations

import base64
import copy
import hashlib
import hmac
import json
import re
import secrets
import time
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime
from zoneinfo import ZoneInfo
from task_schedule import ScheduleError, validate_schedule, is_overdue

from sqlalchemy import (Boolean, Column, Float, Integer, MetaData, String, Table,
                        Text, bindparam, case, create_engine, delete, event, insert, select, update)
from sqlalchemy.exc import DBAPIError, IntegrityError

ZONE = ZoneInfo("Asia/Riyadh")
STATUSES = {"todo": "جديدة", "in_progress": "قيد العمل", "waiting_stakeholder": "بانتظار رد", "done": "مكتملة"}
PRIORITIES = {"urgent": "عاجلة", "high": "مرتفعة", "medium": "عادية", "normal": "منخفضة"}
ROLES = {"admin": "مدير النظام", "manager": "مشرف الفريق", "member": "عضو", "file_manager": "عضو مع حذف الملفات", "viewer": "مشاهد", "agent": "مساعد ذكي"}
COLLECTIONS = ("members", "projects", "stakeholders", "tasks", "files", "messages")
MAX_BACKUP = 30 * 1024 * 1024


class WorkspaceError(Exception):
    pass


class Forbidden(WorkspaceError):
    pass


class Conflict(WorkspaceError):
    pass


def validate_task_schedule(task):
    try:
        validate_schedule(task)
    except ScheduleError as exc:
        raise WorkspaceError(str(exc)) from None


def now_iso():
    return datetime.now(ZONE).isoformat(timespec="microseconds")


def today_iso():
    return datetime.now(ZONE).date().isoformat()


def uid(prefix=""):
    return prefix + uuid.uuid4().hex


def dumps(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def clean_username(value):
    value = str(value).strip().lower()
    if not re.fullmatch(r"[a-z0-9][a-z0-9_.-]{2,39}", value):
        raise WorkspaceError("اسم المستخدم: من 3 إلى 40 حرفًا إنجليزيًا أو رقمًا، ويمكن استخدام _ . -")
    return value


def password_hash(password):
    if not isinstance(password, str) or not 12 <= len(password) <= 256:
        raise WorkspaceError("اختر كلمة مرور من 12 إلى 256 حرفًا.")
    salt = secrets.token_bytes(24)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 600_000)
    return "pbkdf2_sha256$600000$" + salt.hex() + "$" + digest.hex()


def verify_password(password, encoded):
    try:
        _, iterations, salt, expected = encoded.split("$")
        digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(iterations))
        return hmac.compare_digest(digest.hex(), expected)
    except (ValueError, AttributeError, TypeError):
        return False


def blank_state():
    return {"members": [], "projects": [{"id": "p_general", "name": "مساحة الفريق", "desc": "متابعة العمل والقرارات اليومية", "version": 1}],
            "stakeholders": [], "tasks": [], "files": [], "messages": [],
            "handover": {"summary": "", "next_step": "", "decisions": "", "updated_at": "", "version": 1}}


def prepare_import(raw):
    """Validate all data before opening a write transaction. Never import accounts."""
    if len(raw) > MAX_BACKUP:
        raise WorkspaceError("حجم ملف بداية اليوم يتجاوز 30 ميجابايت.")
    try:
        payload = json.loads(raw.decode("utf-8-sig"))
    except (ValueError, UnicodeError, RecursionError):
        raise WorkspaceError("الملف ليس نسخة JSON صالحة.") from None
    if not isinstance(payload, dict):
        raise WorkspaceError("بنية النسخة غير صالحة.")
    modern = payload.get("format") == "gday.workspace"
    if modern and payload.get("schema_version") != 2:
        raise WorkspaceError("إصدار النسخة غير مدعوم؛ استخدم نسخة G'day بإصدار 2.")
    data = payload.get("data") if modern else payload
    if not isinstance(data, dict) or not isinstance(data.get("tasks"), list):
        raise WorkspaceError("لم أجد قائمة مهام في الملف. ارفع نسخة الحفظ JSON، وليس تقرير Excel.")
    data = copy.deepcopy(data)
    if not modern:
        # Both generations of the supplied HTML workspace are supported.
        if "messages" not in data and isinstance(data.get("chats"), list):
            data["messages"] = [m | {"authorId": m.get("senderId", "")} for m in data["chats"] if isinstance(m, dict)]
        for task in data["tasks"]:
            if not isinstance(task, dict):
                continue
            task["status"] = {"new": "todo", "doing": "in_progress", "waiting": "waiting_stakeholder"}.get(task.get("status"), task.get("status", "todo"))
            task["priority"] = {"med": "medium", "low": "normal"}.get(task.get("priority"), task.get("priority", "medium"))
            if "estimatedMinutes" not in task and "estHours" in task:
                hours = task["estHours"]
                if not isinstance(hours, (int, float)) or isinstance(hours, bool):
                    raise WorkspaceError("مدة مهمة غير صالحة في النسخة السابقة.")
                task["estimatedMinutes"] = hours * 60
            task.setdefault("attachedFileId", task.get("fileId", ""))
        for item in data.get("files", []):
            if isinstance(item, dict) and "grid" in item:
                item.setdefault("sheetData", item["grid"])
    result = blank_state()
    limits = {"members": 2000, "projects": 1000, "stakeholders": 5000, "tasks": 20000, "files": 1000, "messages": 50000}
    for name in COLLECTIONS:
        records = data.get(name, [])
        if not isinstance(records, list) or len(records) > limits[name]:
            raise WorkspaceError("قائمة غير صالحة أو أكبر من الحد المسموح: " + name)
        seen = set()
        for original in records:
            if not isinstance(original, dict):
                raise WorkspaceError("سجل غير صالح في " + name)
            record = copy.deepcopy(original)
            ident = record.get("id")
            if not isinstance(ident, str) or not ident or len(ident) > 160 or ident in seen:
                raise WorkspaceError("يوجد معرّف ناقص أو مكرر في " + name)
            seen.add(ident)
            record["version"] = 1
            if name == "tasks":
                if not isinstance(record.get("title"), str) or not record["title"].strip():
                    raise WorkspaceError("يوجد عنوان مهمة فارغ أو غير صالح.")
                if record.get("status", "todo") not in STATUSES or record.get("priority", "medium") not in PRIORITIES:
                    raise WorkspaceError("يوجد تصنيف مهمة غير معروف.")
                for nested in ("subtasks", "comments"):
                    if not isinstance(record.get(nested, []), list) or any(not isinstance(r, dict) for r in record.get(nested, [])):
                        raise WorkspaceError("تفاصيل مهمة غير صالحة.")
                validate_task_schedule(record)
            if name in ("members", "projects", "stakeholders") and (not isinstance(record.get("name"), str) or not record["name"].strip()):
                raise WorkspaceError("اسم غير صالح في " + name)
            if name == "messages" and not isinstance(record.get("text"), str):
                raise WorkspaceError("نص محادثة غير صالح.")
            if name == "members":
                # Legacy roles are display metadata, never authentication permissions.
                record = {k: record.get(k, "") for k in ("id", "name", "title", "color")} | {"version": 1}
            if name == "files":
                if "object" in record:
                    from cloud_storage import validate_object
                    validate_object(record["object"])
                if not isinstance(record.get("title"), str):
                    raise WorkspaceError("اسم ملف غير صالح.")
                if record.get("type") not in ("doc", "sheet", "pdf"):
                    raise WorkspaceError("نوع ملف غير معروف.")
                if "sheets" in record:
                    sheets = record["sheets"]
                    if not isinstance(sheets, list) or not sheets or len(sheets) > 20:
                        raise WorkspaceError("أوراق جدول غير صالحة.")
                    for sheet in sheets:
                        if not isinstance(sheet, dict) or not isinstance(sheet.get("name"), str) or not isinstance(sheet.get("rows"), list):
                            raise WorkspaceError("بنية ورقة عمل غير صالحة.")
                        if len(sheet["rows"]) > 5000 or any(not isinstance(row, list) or len(row) > 60 for row in sheet["rows"]):
                            raise WorkspaceError("جدول أكبر من الحدود المسموحة أو غير صالح.")
                for key in ("text", "content"):
                    if key in record and not isinstance(record[key], str):
                        raise WorkspaceError("محتوى مستند غير صالح.")
                if "pdfPages" in record and (not isinstance(record["pdfPages"], list) or any(not isinstance(p, dict) for p in record["pdfPages"])):
                    raise WorkspaceError("صفحات مستند قديم غير صالحة.")
                if "blob" in record:
                    try:
                        binary = base64.b64decode(record["blob"], validate=True)
                        if len(binary) > 8 * 1024 * 1024:
                            raise ValueError()
                    except (ValueError, TypeError):
                        raise WorkspaceError("يوجد مرفق تالف أو أكبر من 8 ميجابايت.") from None
                if "sheetData" in record and (not isinstance(record["sheetData"], list) or any(not isinstance(row, list) for row in record["sheetData"])):
                    raise WorkspaceError("بيانات جدول قديم غير صالحة.")
                record.setdefault("legacy", not modern)
            if name in ("tasks", "files"):
                comments = record.get("comments", [])
                if not isinstance(comments, list) or any(not isinstance(c, dict) or not isinstance(c.get("text"), str) for c in comments):
                    raise WorkspaceError("تعليقات غير صالحة.")
            if name == "tasks":
                minutes = record.get("estimatedMinutes", 30)
                if not isinstance(minutes, (int, float)) or isinstance(minutes, bool) or not 0 <= minutes <= 100000:
                    raise WorkspaceError("الوقت المتوقع للمهمة غير صالح.")
                if any(not isinstance(s.get("id"), str) or not isinstance(s.get("text"), str) for s in record.get("subtasks", [])):
                    raise WorkspaceError("خطوات فرعية غير صالحة.")
            result[name].append(record) if name != "projects" else None
        if name == "projects":
            result[name] = [copy.deepcopy(r) | {"version": 1} for r in records] or blank_state()["projects"]
    handover = data.get("handover", {})
    if not isinstance(handover, dict):
        raise WorkspaceError("بيانات تسليم اليوم غير صالحة.")
    for k in ("summary", "next_step", "decisions", "updated_at"):
        if not isinstance(handover.get(k, ""), str):
            raise WorkspaceError("بيانات تسليم اليوم غير صالحة.")
    result["handover"].update({k: handover.get(k, "") for k in ("summary", "next_step", "decisions", "updated_at")})
    return {"data": result, "source": "النسخة الجديدة" if modern else "النسخة السابقة (HTML)",
            "exported_at": str(payload.get("exported_at", "غير مسجل في النسخة السابقة"))}


metadata = MetaData()
workspaces = Table("gday_workspace", metadata, Column("id", String(20), primary_key=True), Column("payload", Text, nullable=False), Column("revision", Integer, nullable=False))
users = Table("gday_users", metadata, Column("id", String(64), primary_key=True), Column("username", String(40), unique=True, nullable=False),
              Column("name", String(160), nullable=False), Column("member_id", String(160), nullable=False), Column("role", String(20), nullable=False),
              Column("active", Boolean, nullable=False), Column("agent_edit", Boolean, nullable=False), Column("password_hash", Text, nullable=False))
sessions = Table("gday_sessions", metadata, Column("token_hash", String(64), primary_key=True), Column("user_id", String(64), nullable=False), Column("expires", Float, nullable=False))
attempts = Table("gday_attempts", metadata, Column("username_hash", String(64), primary_key=True), Column("count", Integer, nullable=False), Column("locked_until", Float, nullable=False))
audit = Table("gday_audit", metadata, Column("id", String(64), primary_key=True), Column("at", String(40), nullable=False), Column("actor", String(160), nullable=False),
              Column("action", String(100), nullable=False), Column("detail", Text, nullable=False))
snapshots = Table("gday_snapshots", metadata, Column("id", String(64), primary_key=True), Column("at", String(40), nullable=False), Column("label", String(160), nullable=False), Column("payload", Text, nullable=False))


class Store:
    def __init__(self, database_url, storage=None):
        self.storage = storage
        self.storage_error = ""
        self._cache_lock = threading.RLock()
        self._cached_revision = None
        self._cached_state = None
        self._initialized = False
        if database_url.startswith("postgres://"):
            database_url = "postgresql+psycopg://" + database_url[len("postgres://"):]
        elif database_url.startswith("postgresql://"):
            database_url = "postgresql+psycopg://" + database_url[len("postgresql://"):]
        self.remote = database_url.startswith("postgresql+")
        if not self.remote and not database_url.startswith("sqlite:///"):
            raise WorkspaceError("استخدم PostgreSQL للسحابة أو SQLite للتشغيل المحلي.")
        self.engine = create_engine(database_url, pool_pre_ping=True, hide_parameters=True, skip_autocommit_rollback=self.remote,
                                    connect_args={"timeout": 30, "check_same_thread": False} if not self.remote else {"connect_timeout": 10, "prepare_threshold": None})
        # A separate, bounded pool makes single SELECTs one network round trip.
        # Writes retain their pre-ping and transactional pool unchanged.
        self._read_engine = create_engine(
            database_url, isolation_level="AUTOCOMMIT", pool_pre_ping=False,
            skip_autocommit_rollback=True, hide_parameters=True,
            pool_size=2, max_overflow=2, pool_use_lifo=True,
            connect_args={"connect_timeout": 10, "prepare_threshold": None},
        ) if self.remote else self.engine
        if not self.remote:
            @event.listens_for(self.engine, "connect")
            def sqlite_options(conn, _):
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA busy_timeout=30000")
        metadata.create_all(self.engine)
        try:
            with self.engine.begin() as conn:
                if conn.execute(select(workspaces.c.id)).first() is None:
                    conn.execute(insert(workspaces).values(id="main", payload=dumps(blank_state()), revision=0))
        except IntegrityError:
            pass  # Another worker initialized the same workspace.

    @contextmanager
    def transaction(self):
        with self.engine.connect() as conn:
            conn.info.pop("gday_pending_snapshot", None)
            if not self.remote:
                conn.exec_driver_sql("BEGIN IMMEDIATE")
            else:
                conn.begin()
                conn.execute(select(workspaces.c.id).where(workspaces.c.id == "main").with_for_update())
            try:
                yield conn
                conn.commit()
                snapshot = conn.info.pop("gday_pending_snapshot", None)
                if snapshot is not None:
                    state, revision = snapshot
                    with self._cache_lock:
                        if self._cached_revision is None or revision >= self._cached_revision:
                            self._cached_state, self._cached_revision = state, revision
            except Exception:
                conn.info.pop("gday_pending_snapshot", None)
                conn.rollback()
                raise

    @contextmanager
    def _read_connection(self):
        # Single-statement reads still authenticate against the live database.
        # PostgreSQL need not exchange BEGIN/ROLLBACK around each page read.
        # The dedicated remote pool is already in native autocommit mode.
        with self._read_engine.connect() as conn:
            if self.remote and self._read_engine is self.engine:
                conn = conn.execution_options(isolation_level="AUTOCOMMIT")
            yield conn

    def _read_one(self, statement):
        if not statement.is_select:
            raise ValueError("Only SELECT statements may use the read retry path.")
        for attempt in range(2):
            try:
                with self._read_connection() as conn:
                    return conn.execute(statement).mappings().first()
            except DBAPIError as exc:
                # SQLAlchemy invalidates disconnected pooled connections. Only
                # retry a single side-effect-free read, never a write/transaction.
                if not self.remote or not exc.connection_invalidated or attempt:
                    raise

    def _state(self, conn):
        row = conn.execute(select(workspaces).where(workspaces.c.id == "main")).mappings().one()
        return json.loads(row["payload"]), row["revision"]

    def _save(self, conn, state, revision):
        encoded = dumps(state)
        if len(encoded.encode()) > MAX_BACKUP - 1024:
            raise WorkspaceError("مساحة العمل تجاوزت 30 ميجابايت؛ احذف بعض المرفقات أو أرشفها قبل الإضافة.")
        changed = conn.execute(update(workspaces).where(workspaces.c.id == "main", workspaces.c.revision == revision).values(payload=encoded, revision=revision + 1))
        if changed.rowcount != 1:
            raise Conflict("تغيرت البيانات أثناء الحفظ؛ حدّث الصفحة ثم أعد المحاولة.")
        # Publish only after COMMIT. The next authenticated read can reuse
        # these exact bytes' state instead of downloading the workspace again.
        conn.info["gday_pending_snapshot"] = (copy.deepcopy(state), revision + 1)
        with self._cache_lock:
            self._cached_revision = None
            self._cached_state = None

    def context(self, token):
        # Keep a local reference to an immutable snapshot. Other readers can
        # refresh/invalidate the shared cache while this query is in flight.
        with self._cache_lock:
            cached_state, cached_revision = self._cached_state, self._cached_revision
        payload = workspaces.c.payload if cached_revision is None else case(
            (workspaces.c.revision != cached_revision, workspaces.c.payload), else_=None)
        statement = self._actor_statement(token).add_columns(
            workspaces.c.revision.label("workspace_revision"), payload.label("workspace_payload")
        ).join(workspaces, workspaces.c.id == "main")
        row = self._read_one(statement)
        if not row:
            raise Forbidden("انتهت الجلسة أو أُوقف الحساب؛ سجّل الدخول من جديد.")
        revision = row["workspace_revision"]
        state = json.loads(row["workspace_payload"]) if row["workspace_payload"] is not None else cached_state
        if row["workspace_payload"] is not None:
            with self._cache_lock:
                if self._cached_revision is None or revision >= self._cached_revision:
                    self._cached_state, self._cached_revision = state, revision
        actor = {column.name: row[column.name] for column in users.c if column.name != "password_hash"}
        return copy.deepcopy(state), revision, actor

    def _log(self, conn, actor, action, detail=""):
        conn.execute(insert(audit).values(id=uid(), at=now_iso(), actor=actor["name"], action=action, detail=detail[:1000]))

    def initialized(self):
        # Bootstrap status is stable once accounts exist. Authentication and
        # permissions are still checked against the database on every read.
        if self._initialized:
            return True
        ready = self._read_one(select(users.c.id).limit(1)) is not None
        self._initialized = ready
        return ready

    def bootstrap(self, username, password, name="مدير المنصة"):
        if self.initialized():
            return
        username = clean_username(username)
        hashed = password_hash(password)
        with self.transaction() as conn:
            if conn.execute(select(users.c.id).limit(1)).first():
                return
            user_id, member_id = uid("usr_"), uid("u_")
            conn.execute(insert(users).values(id=user_id, username=username, name=name, member_id=member_id, role="admin", active=True, agent_edit=False, password_hash=hashed))
            state, revision = self._state(conn)
            state["members"].append({"id": member_id, "name": name, "title": "مدير المنصة", "version": 1})
            self._save(conn, state, revision)
        self._initialized = True

    def login(self, username, password, days=30):
        try:
            username = clean_username(username)
        except WorkspaceError:
            return None
        if not isinstance(password, str) or len(password) > 256:
            return None
        key = hashlib.sha256(username.encode()).hexdigest()
        # A durable per-account lock also covers nonexistent usernames.
        with self.transaction() as conn:
            attempt = conn.execute(select(attempts).where(attempts.c.username_hash == key)).mappings().first()
            if attempt and attempt["locked_until"] > time.time():
                return None
            user = conn.execute(select(users).where(users.c.username == username)).mappings().first()
            dummy = "pbkdf2_sha256$600000$" + "00" * 24 + "$" + "00" * 32
            valid = verify_password(password, user["password_hash"] if user else dummy)
            if not user or not user["active"] or not valid:
                count = (attempt["count"] if attempt else 0) + 1
                values = {"count": count if count < 5 else 0, "locked_until": time.time() + 900 if count >= 5 else 0}
                if attempt:
                    conn.execute(update(attempts).where(attempts.c.username_hash == key).values(**values))
                else:
                    conn.execute(insert(attempts).values(username_hash=key, **values))
                return None
            conn.execute(delete(attempts).where(attempts.c.username_hash == key))
            conn.execute(delete(sessions).where(sessions.c.expires < time.time()))
            token = secrets.token_urlsafe(48)
            conn.execute(insert(sessions).values(token_hash=hashlib.sha256(token.encode()).hexdigest(), user_id=user["id"], expires=time.time() + min(max(days, 1), 90) * 86400))
            self._log(conn, user, "تسجيل دخول")
            return token

    @staticmethod
    def _actor_statement(token):
        if not isinstance(token, str) or not 20 <= len(token) <= 200:
            raise Forbidden("سجّل الدخول أولًا.")
        return select(*[column for column in users.c if column.name != "password_hash"]).select_from(
            users.join(sessions, users.c.id == sessions.c.user_id)).where(
            sessions.c.token_hash == hashlib.sha256(token.encode()).hexdigest(),
            sessions.c.expires > bindparam("session_now", callable_=time.time), users.c.active.is_(True))

    def _actor(self, conn, token):
        row = conn.execute(self._actor_statement(token)).mappings().first()
        if not row:
            raise Forbidden("انتهت الجلسة أو أُوقف الحساب؛ سجّل الدخول من جديد.")
        return dict(row)

    def actor(self, token):
        row = self._read_one(self._actor_statement(token))
        if not row:
            raise Forbidden("انتهت الجلسة أو أُوقف الحساب؛ سجّل الدخول من جديد.")
        return dict(row)

    @staticmethod
    def can_edit(actor):
        return actor["role"] in ("admin", "manager", "member", "file_manager") or actor["role"] == "agent" and actor["agent_edit"]

    @staticmethod
    def can_delete_files(actor):
        return actor["role"] in ("admin", "manager", "file_manager")

    @staticmethod
    def require(actor, permission):
        if permission == "edit":
            okay = Store.can_edit(actor)
        elif permission == "delete_files":
            okay = Store.can_delete_files(actor)
        elif permission == "manage":
            okay = actor["role"] in ("admin", "manager")
        else:
            okay = actor["role"] == "admin"
        if not okay:
            raise Forbidden("حسابك لا يملك صلاحية تنفيذ هذا الإجراء.")

    def read(self, token):
        state, revision, _ = self.context(token)
        return state, revision

    def logout(self, token, all_sessions=False):
        with self.transaction() as conn:
            actor = self._actor(conn, token)
            condition = sessions.c.user_id == actor["id"] if all_sessions else sessions.c.token_hash == hashlib.sha256(token.encode()).hexdigest()
            conn.execute(delete(sessions).where(condition))
            self._log(conn, actor, "إنهاء جميع جلساتي" if all_sessions else "تسجيل خروج")

    def put(self, token, collection, record, expected_version=None):
        if collection not in COLLECTIONS:
            raise WorkspaceError("نوع سجل غير معروف.")
        with self.transaction() as conn:
            actor = self._actor(conn, token)
            self.require(actor, "manage" if collection in ("members", "projects") else "edit")
            state, revision = self._state(conn)
            record = copy.deepcopy(record)
            record.setdefault("id", uid())
            old = next((x for x in state[collection] if x["id"] == record["id"]), None)
            if old:
                if expected_version is None or old.get("version", 1) != expected_version:
                    raise Conflict("عدّل شخص آخر هذا السجل. حدّث الصفحة لعرض آخر تعديل قبل الحفظ.")
                if collection == "messages" and old.get("authorId") != actor["member_id"]:
                    raise Forbidden("لا يمكن تعديل رسالة عضو آخر.")
            elif expected_version is not None:
                raise Conflict("السجل حُذف منذ فتحه. حدّث الصفحة.")
            if collection in ("projects", "members", "stakeholders"):
                if not str(record.get("name", "")).strip():
                    raise WorkspaceError("الاسم مطلوب.")
            if collection == "stakeholders" and record.get("projectId") and not any(p["id"] == record["projectId"] for p in state["projects"]):
                raise WorkspaceError("اختر مشروعًا موجودًا لجهة الاتصال.")
            if collection == "tasks":
                if not str(record.get("title", "")).strip():
                    raise WorkspaceError("اكتب عنوان المهمة.")
                if record.get("status") not in STATUSES or record.get("priority") not in PRIORITIES:
                    raise WorkspaceError("اختر حالة وأولوية صحيحتين.")
                validate_task_schedule(record)
                record.setdefault("createdBy", old.get("createdBy", actor["member_id"]) if old else actor["member_id"])
                if record.get("status") == "done" and (not old or old.get("status") != "done"):
                    record["completedAt"] = now_iso()
                elif record.get("status") != "done":
                    record.pop("completedAt", None)
            if collection == "messages":
                if not str(record.get("text", "")).strip() or len(str(record.get("text"))) > 20000:
                    raise WorkspaceError("نص الرسالة مطلوب، وبحد أقصى 20 ألف حرف.")
                record["authorId"] = old.get("authorId") if old else actor["member_id"]
                record["time"] = old.get("time", now_iso()) if old else now_iso()
            if collection == "files" and self.storage and record.get("blob"):
                record = self.storage.externalize(record)
            record["version"] = old.get("version", 1) + 1 if old else 1
            record["updatedAt"] = now_iso()
            record["updatedBy"] = actor["member_id"]
            if old:
                state[collection] = [record if x["id"] == record["id"] else x for x in state[collection]]
            else:
                state[collection].append(record)
            self._save(conn, state, revision)
            self._log(conn, actor, ("تعديل " if old else "إضافة ") + collection, str(record.get("title", record.get("name", record["id"]))))
            return record["id"]

    def move_project_contents(self, token, source_id, target_id, expected_revision):
        """Reassign existing records atomically, retaining originals and references."""
        with self.transaction() as conn:
            actor = self._actor(conn, token)
            self.require(actor, "edit")
            state, revision = self._state(conn)
            if revision != expected_revision:
                raise Conflict("تغيرت البيانات؛ حدّثها ثم أعد النقل.")
            projects = {p["id"]: p for p in state["projects"]}
            if source_id == target_id or source_id not in projects or target_id not in projects:
                raise WorkspaceError("اختر مشروعين موجودين ومختلفين للنقل.")
            selected = {name: [r for r in state[name] if r.get("projectId") == source_id or
                        (name == "stakeholders" and source_id == "p_general" and not r.get("projectId"))]
                        for name in ("tasks", "files", "stakeholders")}
            counts = {name: len(records) for name, records in selected.items()}
            if any(counts.values()):
                self._snapshot(conn, state, "قبل نقل محتوى المشروع: " + projects[source_id]["name"])
                at = now_iso()
                for records in selected.values():
                    for record in records:
                        record.update(projectId=target_id, version=record.get("version", 1) + 1,
                                      updatedAt=at, updatedBy=actor["member_id"])
                self._save(conn, state, revision)
                self._log(conn, actor, "نقل محتوى مشروع", dumps({"from": source_id, "to": target_id, **counts}))
            return counts

    def remove(self, token, collection, ident, expected_version):
        if collection not in COLLECTIONS:
            raise WorkspaceError("نوع سجل غير معروف.")
        with self.transaction() as conn:
            actor = self._actor(conn, token)
            if collection == "messages":
                self.require(actor, "edit")
                if actor["role"] == "agent":
                    raise Forbidden("حساب المساعد لا يحذف الدردشات.")
            elif collection == "files":
                self.require(actor, "delete_files")
            else:
                self.require(actor, "manage")
            state, revision = self._state(conn)
            old = next((x for x in state[collection] if x["id"] == ident), None)
            if not old or old.get("version", 1) != expected_version:
                raise Conflict("السجل تغير أو حُذف؛ حدّث الصفحة أولًا.")
            if collection == "messages" and actor["role"] not in ("admin", "manager") and old.get("authorId") != actor["member_id"]:
                raise Forbidden("يمكنك حذف رسائلك فقط.")
            if collection == "members" and conn.execute(select(users.c.id).where(users.c.member_id == ident)).first():
                raise WorkspaceError("هذا الملف مرتبط بحساب. أوقف الحساب من إدارة الأعضاء بدل حذفه.")
            if collection == "projects" and len(state["projects"]) == 1:
                raise WorkspaceError("احتفظ بمشروع واحد على الأقل.")
            if collection == "files":
                self._snapshot(conn, state, "قبل حذف ملف: " + str(old.get("title") or ident))
            state[collection] = [x for x in state[collection] if x["id"] != ident]
            # Never cascade-delete tasks, files, or conversations by removing a project.
            if collection == "projects":
                fallback = state["projects"][0]["id"]
                for name in ("tasks", "files", "messages", "stakeholders"):
                    for item in state[name]:
                        if item.get("projectId") == ident:
                            item.update(projectId=fallback, version=item.get("version", 1) + 1)
            reference = {"members": "assigneeId", "stakeholders": "stakeholderId", "files": "attachedFileId"}.get(collection)
            if reference:
                for item in state["tasks"]:
                    if item.get(reference) == ident:
                        item.update({reference: "", "version": item.get("version", 1) + 1})
            if collection == "files":
                for item in state["messages"]:
                    if item.get("fileId") == ident:
                        item.update(fileId="", version=item.get("version", 1) + 1)
            self._save(conn, state, revision)
            self._log(conn, actor, "حذف " + collection, ident)  # Deleted chat content is not retained in audit.

    def add_files(self, token, records):
        """A whole upload batch is committed once or rolled back completely."""
        with self.transaction() as conn:
            actor = self._actor(conn, token)
            self.require(actor, "edit")
            state, revision = self._state(conn)
            seen = {f["id"] for f in state["files"]}
            for record in copy.deepcopy(records):
                if record.get("id") in seen or not record.get("id") or not record.get("title"):
                    raise WorkspaceError("يوجد ملف ناقص البيانات أو مكرر.")
                seen.add(record["id"])
                if self.storage:
                    record = self.storage.externalize(record)
                record.update(version=1, updatedAt=now_iso(), updatedBy=actor["member_id"])
                state["files"].append(record)
                self._log(conn, actor, "رفع ملف", record["title"])
            self._save(conn, state, revision)

    def patch_tasks(self, token, patches):
        """Commit a table edit atomically; detect stale individual rows."""
        allowed = {"title", "assigneeId", "status", "priority", "dueDate", "dueTime", "reminderEnabled", "reminderMinutes", "estimatedMinutes"}
        with self.transaction() as conn:
            actor = self._actor(conn, token)
            self.require(actor, "edit")
            state, revision = self._state(conn)
            index = {t["id"]: t for t in state["tasks"]}
            for patch in patches:
                task = index.get(patch.get("id"))
                if not task or task.get("version", 1) != patch.get("version"):
                    raise Conflict("أحد صفوف الجدول تغير لدى عضو آخر. حدّث العرض قبل حفظ التعديلات.")
                values = patch.get("changes", {})
                if set(values) - allowed:
                    raise Forbidden("هذا الحقل لا يُعدّل من الجدول.")
                changed = task | values
                validate_task_schedule(changed)
                if not isinstance(changed.get("title"), str) or not changed["title"].strip():
                    raise WorkspaceError("عنوان المهمة مطلوب.")
                if changed.get("status") not in STATUSES or changed.get("priority") not in PRIORITIES:
                    raise WorkspaceError("الحالة أو الأولوية غير صالحة.")
                if changed.get("assigneeId") and not any(m["id"] == changed["assigneeId"] for m in state["members"]):
                    raise WorkspaceError("المسؤول المحدد غير موجود.")
                due = changed.get("dueDate")
                if due:
                    try:
                        datetime.strptime(due, "%Y-%m-%d")
                    except (ValueError, TypeError):
                        raise WorkspaceError("التاريخ غير صالح.") from None
                minutes = changed.get("estimatedMinutes", 30)
                if not isinstance(minutes, (int, float)) or not 0 <= minutes <= 100000:
                    raise WorkspaceError("مدة المهمة غير صالحة.")
                if changed["status"] == "done" and task.get("status") != "done":
                    changed["completedAt"] = now_iso()
                elif changed["status"] != "done":
                    changed.pop("completedAt", None)
                task.clear()
                task.update(changed, version=patch["version"] + 1, updatedAt=now_iso(), updatedBy=actor["member_id"])
                self._log(conn, actor, "تعديل من جدول المهام", changed["title"])
            if patches:
                self._save(conn, state, revision)

    def merge_workspace(self, token, raw, project_id, expected_revision):
        from migration import build_merge
        with self.transaction() as conn:
            actor = self._actor(conn, token)
            self.require(actor, "edit")
            state, revision = self._state(conn)
            if revision != expected_revision:
                raise Conflict("تغيرت مساحة العمل منذ المعاينة. حدّث المعاينة قبل الاستيراد.")
            additions, summary = build_merge(raw, state, project_id)
            if any(additions.values()):
                self._snapshot(conn, state, "قبل الاستيراد الإضافي")
                for collection, records in additions.items():
                    for record in records:
                        if collection == "files" and self.storage:
                            record = self.storage.externalize(record)
                        record.update(version=1, updatedAt=now_iso(), updatedBy=actor["member_id"])
                        state[collection].append(record)
                self._save(conn, state, revision)
            self._log(conn, actor, "استيراد إضافي دون استبدال", dumps(summary))
            return summary

    def clear_chat(self, token, project_id=None, expected_revision=None):
        with self.transaction() as conn:
            actor = self._actor(conn, token)
            self.require(actor, "manage")
            state, revision = self._state(conn)
            if expected_revision != revision:
                raise Conflict("وصلت تحديثات جديدة؛ حدّث الصفحة وراجع الرسائل قبل الحذف.")
            original = len(state["messages"])
            state["messages"] = [m for m in state["messages"] if project_id and m.get("projectId") != project_id]
            self._save(conn, state, revision)
            self._log(conn, actor, "حذف دردشات القناة" if project_id else "حذف جميع الدردشات", str(original - len(state["messages"])))

    def save_handover(self, token, values, expected_version):
        with self.transaction() as conn:
            actor = self._actor(conn, token)
            self.require(actor, "edit")
            state, revision = self._state(conn)
            if state["handover"].get("version", 1) != expected_version:
                raise Conflict("تسليم اليوم تغير؛ حدّث الصفحة ثم راجع آخر نسخة.")
            state["handover"] = {k: str(values.get(k, ""))[:20000] for k in ("summary", "next_step", "decisions")}
            state["handover"].update(updated_at=now_iso(), version=expected_version + 1, updated_by=actor["member_id"])
            self._save(conn, state, revision)
            self._log(conn, actor, "تحديث تسليم اليوم")

    @staticmethod
    def backup_bytes(state):
        return dumps({"format": "gday.workspace", "schema_version": 2, "exported_at": now_iso(), "data": state}).encode("utf-8")

    def file_bytes(self, token, file_id):
        """Only a live, authenticated workspace record can name a downloadable object."""
        state, _ = self.read(token)
        record = next((f for f in state["files"] if f["id"] == file_id), None)
        if record is None:
            raise WorkspaceError("الملف غير موجود.")
        return self._original_bytes(record)

    def _original_bytes(self, record):
        if record.get("blob"):
            return base64.b64decode(record["blob"], validate=True)
        if record.get("object"):
            if not self.storage:
                raise WorkspaceError("أعد إعداد مخزن Neon للوصول إلى هذا الأصل؛ المحتوى المحرر ما زال محفوظًا.")
            return self.storage.download(record["object"])
        return b""

    def export_with_originals(self, token):
        state, _ = self.read(token)
        total = len(dumps(state).encode())
        for record in state["files"]:
            if record.get("object"):
                total += (record["object"]["size"] + 2) // 3 * 4
        if total > MAX_BACKUP - 4096:
            raise WorkspaceError("النسخة بالأصول تتجاوز 30 ميجابايت. استخدم النسخة الخفيفة، ونزّل الأصول المطلوبة من المكتبة.")
        for record in state["files"]:
            if record.get("object"):
                record["blob"] = base64.b64encode(self._original_bytes(record)).decode()
                record.pop("object", None)
        return self.backup_bytes(state)

    def migrate_originals(self, token, expected_revision):
        """Move originals without changing IDs or text. No storage object is deleted."""
        with self.transaction() as conn:
            actor = self._actor(conn, token)
            self.require(actor, "admin")
            state, revision = self._state(conn)
            if revision != expected_revision:
                raise Conflict("تغيرت البيانات؛ حدّث عرض التخزين ثم أعد النقل.")
            if not self.storage:
                raise WorkspaceError("أكمل ربط Object Storage أولًا.")
            originals = [f for f in state["files"] if f.get("blob")]
            if originals:
                self._snapshot(conn, state, "قبل نقل أصول الملفات إلى Neon Storage")
                for record in originals:
                    result = self.storage.externalize(record)
                    result.update(version=record.get("version", 1) + 1, updatedAt=now_iso(), updatedBy=actor["member_id"])
                    record.clear(); record.update(result)
                self._save(conn, state, revision)
                self._log(conn, actor, "نقل أصول الملفات إلى Neon Storage", str(len(originals)))
            return len(originals)

    def _snapshot(self, conn, state, label):
        ident = uid("snap_")
        conn.execute(insert(snapshots).values(id=ident, at=now_iso(), label=label[:160], payload=dumps(state)))
        keep = select(snapshots.c.id).order_by(snapshots.c.at.desc(), snapshots.c.id.desc()).limit(14)
        conn.execute(delete(snapshots).where(snapshots.c.id.not_in(keep)))
        return ident

    def save_snapshot(self, token, label):
        with self.transaction() as conn:
            actor = self._actor(conn, token)
            self.require(actor, "manage")
            state, _ = self._state(conn)
            ident = self._snapshot(conn, state, label)
            self._log(conn, actor, "حفظ نسخة يومية", label)
            return ident

    def list_snapshots(self, token):
        with self.engine.connect() as conn:
            actor = self._actor(conn, token)
            self.require(actor, "manage")
            return [dict(x) for x in conn.execute(select(snapshots.c.id, snapshots.c.at, snapshots.c.label).order_by(snapshots.c.at.desc(), snapshots.c.id.desc())).mappings()]

    def snapshot_bytes(self, token, ident):
        with self.engine.connect() as conn:
            actor = self._actor(conn, token)
            self.require(actor, "manage")
            row = conn.execute(select(snapshots.c.payload).where(snapshots.c.id == ident)).scalar_one_or_none()
            if row is None:
                raise WorkspaceError("النسخة غير موجودة.")
            return self.backup_bytes(json.loads(row))

    def restore(self, token, raw, expected_revision):
        imported = prepare_import(raw)
        with self.transaction() as conn:
            actor = self._actor(conn, token)
            self.require(actor, "manage")
            current, revision = self._state(conn)
            if revision != expected_revision:
                raise Conflict("تغيرت البيانات منذ عرض المعاينة. أعد رفع الملف وراجع المعاينة.")
            self._snapshot(conn, current, "قبل استعادة ملف بداية اليوم")
            incoming = imported["data"]
            # Keep actual login accounts and their linked profiles intact.
            for profile in conn.execute(select(users.c.member_id, users.c.name)).mappings():
                if not any(m["id"] == profile["member_id"] for m in incoming["members"]):
                    incoming["members"].append({"id": profile["member_id"], "name": profile["name"], "title": "عضو الفريق", "version": 1})
            # Do not let an old form's version coincide with restored records.
            for name in COLLECTIONS:
                old_versions = {r["id"]: r.get("version", 1) for r in current[name]}
                for record in incoming[name]:
                    record["version"] = max(old_versions.get(record["id"], 0), revision) + 1
            incoming["handover"]["version"] = max(current["handover"].get("version", 1), revision) + 1
            self._save(conn, incoming, revision)
            self._log(conn, actor, "استعادة ملف بداية اليوم", imported["source"])

    def list_users(self, token):
        with self.engine.connect() as conn:
            self.require(self._actor(conn, token), "admin")
            return [dict(r) for r in conn.execute(select(*[c for c in users.c if c.name != "password_hash"])).mappings()]

    def create_user(self, token, username, name, password, role, member_id="", agent_edit=False):
        username, hashed = clean_username(username), password_hash(password)
        if role not in ROLES or not name.strip() or len(name) > 160:
            raise WorkspaceError("تحقق من الاسم والدور.")
        try:
            with self.transaction() as conn:
                actor = self._actor(conn, token)
                self.require(actor, "admin")
                state, revision = self._state(conn)
                if member_id:
                    if not any(m["id"] == member_id for m in state["members"]):
                        raise WorkspaceError("العضو المحدد غير موجود.")
                    if conn.execute(select(users.c.id).where(users.c.member_id == member_id)).first():
                        raise WorkspaceError("هذا الملف مرتبط بحساب مسبقًا.")
                else:
                    member_id = uid("u_")
                    state["members"].append({"id": member_id, "name": name.strip(), "title": ROLES[role], "version": 1})
                    self._save(conn, state, revision)
                ident = uid("usr_")
                conn.execute(insert(users).values(id=ident, username=username, name=name.strip(), member_id=member_id, role=role, active=True, agent_edit=agent_edit if role == "agent" else False, password_hash=hashed))
                self._log(conn, actor, "إنشاء حساب", username + " / " + ROLES[role])
                return ident
        except IntegrityError:
            raise WorkspaceError("اسم المستخدم مستخدم بالفعل.") from None

    def update_user(self, token, user_id, role, active, agent_edit=False, new_password=""):
        if role not in ROLES:
            raise WorkspaceError("دور غير صالح.")
        hashed = password_hash(new_password) if new_password else None
        with self.transaction() as conn:
            actor = self._actor(conn, token)
            self.require(actor, "admin")
            target = conn.execute(select(users).where(users.c.id == user_id)).mappings().first()
            if not target:
                raise WorkspaceError("الحساب غير موجود.")
            if target["role"] == "admin" and target["active"] and (role != "admin" or not active):
                admins = list(conn.execute(select(users.c.id).where(users.c.role == "admin", users.c.active.is_(True))))
                if len(admins) <= 1:
                    raise WorkspaceError("لا يمكن إيقاف آخر مدير نظام أو تخفيض صلاحياته.")
            values = {"role": role, "active": active, "agent_edit": agent_edit if role == "agent" else False}
            if hashed:
                values["password_hash"] = hashed
            conn.execute(update(users).where(users.c.id == user_id).values(**values))
            # Any access change invalidates existing sessions, including a remembered browser.
            conn.execute(delete(sessions).where(sessions.c.user_id == user_id))
            self._log(conn, actor, "تحديث حساب وإلغاء جلساته", target["username"])

    def change_password(self, token, current_password, new_password):
        hashed = password_hash(new_password)
        with self.transaction() as conn:
            actor = self._actor(conn, token)
            encoded = conn.execute(select(users.c.password_hash).where(users.c.id == actor["id"])).scalar_one()
            if not verify_password(current_password, encoded):
                raise WorkspaceError("كلمة المرور الحالية غير صحيحة.")
            conn.execute(update(users).where(users.c.id == actor["id"]).values(password_hash=hashed))
            conn.execute(delete(sessions).where(sessions.c.user_id == actor["id"]))
            self._log(conn, actor, "تغيير كلمة المرور وإلغاء الجلسات")

    def activity(self, token, limit=150):
        with self.engine.connect() as conn:
            self.require(self._actor(conn, token), "admin")
            return [dict(x) for x in conn.execute(select(audit).order_by(audit.c.at.desc()).limit(limit)).mappings()]


def morning_brief(state):
    today = today_iso()
    pending = [t for t in state["tasks"] if t.get("status") != "done"]
    overdue = [t for t in pending if is_overdue(t)]
    due = [t for t in pending if t.get("dueDate") == today]
    waiting = [t for t in pending if t.get("status") == "waiting_stakeholder"]
    focus = sorted(pending, key=lambda t: (0 if t.get("dueDate") and t["dueDate"] <= today else 1, list(PRIORITIES).index(t.get("priority", "medium")), t.get("dueDate") or "9999", t.get("dueTime") or "23:59"))[:3]
    return {"pending": pending, "overdue": overdue, "today": due, "waiting": waiting, "focus": focus}
