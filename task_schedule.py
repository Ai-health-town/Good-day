"""Task deadlines and reminder selection, all interpreted in Riyadh time."""
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

RIYADH = ZoneInfo("Asia/Riyadh")
DAY_PERIODS = ("صباحًا", "مساءً")
REMINDER_OPTIONS = {0: "عند الموعد", 5: "قبل ٥ دقائق", 10: "قبل ١٠ دقائق", 15: "قبل ربع ساعة",
                    30: "قبل نصف ساعة", 60: "قبل ساعة", 120: "قبل ساعتين", 1440: "قبل يوم"}


class ScheduleError(ValueError):
    pass


def clock_parts(value):
    """Display a stored 24-hour time as a 12-hour clock and Arabic period."""
    if not value:
        return "", DAY_PERIODS[0]
    hour, minute = map(int, value.split(":"))
    return f"{hour % 12 or 12:02d}:{minute:02d}", DAY_PERIODS[hour >= 12]


def clock_value(clock, period):
    """Convert the explicit clock/period controls without changing stored times."""
    clock = str(clock or "").strip().translate(str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789"))
    if not clock:
        return ""
    if period not in DAY_PERIODS or not re.fullmatch(r"(?:0?[1-9]|1[0-2]):[0-5][0-9]", clock):
        raise ScheduleError("اكتب الوقت بنظام ١٢ ساعة مثل 07:30، ثم اختر صباحًا أو مساءً.")
    hour, minute = map(int, clock.split(":"))
    return f"{hour % 12 + (12 if period == DAY_PERIODS[1] else 0):02d}:{minute:02d}"


def validate_schedule(task):
    day, clock = task.get("dueDate", ""), task.get("dueTime", "")
    day = "" if day is None else day
    clock = "" if clock is None else clock
    try:
        if not isinstance(day, str) or day and (not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day) or datetime.strptime(day, "%Y-%m-%d").strftime("%Y-%m-%d") != day):
            raise ValueError()
    except (ValueError, TypeError):
        raise ScheduleError("تاريخ استحقاق المهمة غير صالح.") from None
    if not isinstance(clock, str) or clock and not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", clock):
        raise ScheduleError("وقت الاستحقاق غير صالح؛ استخدم ساعة ودقيقة مثل 14:30.")
    if clock and not day:
        raise ScheduleError("حدد تاريخ الاستحقاق قبل إضافة الوقت.")
    enabled, lead = task.get("reminderEnabled", False), task.get("reminderMinutes", 15)
    if type(enabled) is not bool or type(lead) is not int or lead not in REMINDER_OPTIONS:
        raise ScheduleError("إعداد التنبيه غير صالح.")
    if enabled and not (day and clock):
        raise ScheduleError("لتفعيل التنبيه الصوتي، حدد تاريخ المهمة ووقت استحقاقها.")


def due_at(task):
    if not task.get("dueDate") or not task.get("dueTime"):
        return None
    try:
        return datetime.strptime(task["dueDate"] + " " + task["dueTime"], "%Y-%m-%d %H:%M").replace(tzinfo=RIYADH)
    except (ValueError, TypeError):
        return None


def is_overdue(task, now=None):
    now = now or datetime.now(RIYADH)
    if task.get("status") == "done" or not task.get("dueDate"):
        return False
    exact = due_at(task)
    return exact < now if exact else task["dueDate"] < now.date().isoformat()


def due_label(task):
    day = task.get("dueDate") or "دون موعد"
    exact = due_at(task)
    if exact:
        period = "ص" if exact.hour < 12 else "م"
        return f"{day} · \u2066{exact.hour % 12 or 12:02d}:{exact.minute:02d}\u2069 {period}"
    return day


def reminder_items(state, actor, now=None):
    """Only the signed-in member's enabled, unfinished, near-future tasks."""
    now = now or datetime.now(RIYADH)
    result = []
    for task in state["tasks"]:
        if task.get("status") == "done" or task.get("reminderEnabled") is not True:
            continue
        if (task.get("assigneeId") or task.get("createdBy")) != actor["member_id"]:
            continue
        try:
            validate_schedule(task)
        except ScheduleError:
            continue
        due = due_at(task)
        if due is None or not now - timedelta(minutes=1) <= due <= now + timedelta(days=7):
            continue
        epoch = int(due.timestamp() * 1000)
        lead = task.get("reminderMinutes", 15)
        result.append({"id": task["id"], "title": str(task.get("title", ""))[:180], "due": epoch,
                       "notifyAt": epoch - lead * 60000, "key": f"{task['id']}|{epoch}|{lead}"})
    return sorted(result, key=lambda r: r["due"])[:200]
