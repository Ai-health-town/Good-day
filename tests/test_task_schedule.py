import copy
import hashlib
import io
import json
import re
import shutil
import subprocess
from html.parser import HTMLParser
from datetime import datetime, time, timezone
from pathlib import Path

import pytest
from openpyxl import load_workbook
from streamlit.testing.v1 import AppTest

from ai_store import normalize_actions
from filetools import tasks_excel
from migration import build_merge
from task_reminders import reminders_html
from task_schedule import RIYADH, ScheduleError, clock_parts, clock_value, due_at, due_label, is_overdue, reminder_items, validate_schedule
from tests.test_ui import healthy, element
from tests.test_workspace import workspace, task
from workspace import Conflict, WorkspaceError, prepare_import


def scheduled(**changes):
    return task("timed") | {"dueDate": "2026-11-08", "dueTime": "11:00", "reminderEnabled": True, "reminderMinutes": 15} | changes


@pytest.mark.parametrize("clock,period,stored", [("12:00", "صباحًا", "00:00"), ("12:00", "مساءً", "12:00"),
    ("07:00", "مساءً", "19:00"), ("٠٧:٣٠", "مساءً", "19:30"), ("۷:۳۰", "صباحًا", "07:30"), ("", "مساءً", "")])
def test_arabic_day_period_preserves_midnight_noon_and_optional_time(clock, period, stored):
    assert clock_value(clock, period) == stored
    if stored:
        displayed, selected = clock_parts(stored)
        assert clock_value(displayed, selected) == stored


@pytest.mark.parametrize("clock", ["00:30", "13:00", "07:60", "7:3", "not a time"])
def test_invalid_12_hour_times_are_rejected(clock):
    with pytest.raises(ScheduleError):
        clock_value(clock, "صباحًا")


def test_changing_only_arabic_period_saves_and_reopens_the_correct_task_time(workspace, monkeypatch):
    from tests.test_task_actions import dialog, seed_task
    store, owner = workspace
    seed_task(store, owner)
    original = store.read(owner)[0]["tasks"][0]
    app = dialog(store, owner, monkeypatch)
    assert element(app.text_input, "وقت الاستحقاق — بتوقيت الرياض").value == "02:30"
    assert element(app.selectbox, "صباح / مساء").value == "مساءً"
    element(app.selectbox, "صباح / مساء").set_value("صباحًا")
    element(app.button, "حفظ المهمة").click().run()
    healthy(app)
    saved = store.read(owner)[0]["tasks"][0]
    assert saved["dueTime"] == "02:30"
    for field in ("comments", "subtasks", "reminderEnabled", "reminderMinutes", "dueDate", "attachedFileId"):
        assert saved[field] == original[field]
    reopened = dialog(store, owner, monkeypatch)
    assert element(reopened.text_input, "وقت الاستحقاق — بتوقيت الرياض").value == "02:30"
    assert element(reopened.selectbox, "صباح / مساء").value == "صباحًا"


@pytest.mark.parametrize("changes", [{"dueTime": "25:00"}, {"dueTime": "9:00"}, {"dueTime": "13:67"},
    {"dueTime": 0}, {"dueDate": "2026-02-30"}, {"dueDate": "", "dueTime": "11:00"},
    {"dueTime": "", "reminderEnabled": True}, {"reminderEnabled": "true"}, {"reminderMinutes": True}, {"reminderMinutes": -5}])
def test_invalid_schedules_are_rejected(changes):
    with pytest.raises(ScheduleError): validate_schedule(scheduled(**changes))


def test_old_date_only_tasks_keep_their_day_based_deadline():
    old = task("old") | {"dueDate": "2026-11-08"}
    validate_schedule(old)
    assert due_at(old) is None and due_label(old) == "2026-11-08"
    assert not is_overdue(old, datetime(2026, 11, 8, 23, 59, tzinfo=RIYADH))
    assert is_overdue(old, datetime(2026, 11, 9, 0, 0, tzinfo=RIYADH))


def test_timed_deadline_uses_riyadh_and_changes_overdue_within_the_same_day():
    value = scheduled()
    assert due_at(value).astimezone(timezone.utc).hour == 8
    assert not is_overdue(value, datetime(2026, 11, 8, 10, 59, tzinfo=RIYADH))
    assert is_overdue(value, datetime(2026, 11, 8, 11, 1, tzinfo=RIYADH))
    assert not is_overdue(value | {"status": "done"}, datetime(2026, 11, 9, tzinfo=RIYADH))
    assert "11:00" in due_label(value) and "ص" in due_label(value)
    assert "07:00" in due_label(value | {"dueTime": "19:00"}) and "م" in due_label(value | {"dueTime": "19:00"})


def test_reminder_selection_is_private_and_cancels_completed_disabled_and_stale_tasks():
    now = datetime(2026, 11, 8, 10, 50, tzinfo=RIYADH)
    mine = scheduled(assigneeId="me")
    state = {"tasks": [mine, scheduled(id="other", assigneeId="other"),
        scheduled(id="completed", assigneeId="me", status="done"), scheduled(id="off", assigneeId="me", reminderEnabled=False),
        scheduled(id="old", assigneeId="me", dueTime="09:00"), scheduled(id="creator", assigneeId="", createdBy="me")]}
    items = reminder_items(state, {"member_id": "me"}, now)
    assert {i["id"] for i in items} == {"timed", "creator"}
    assert items[0]["due"] - items[0]["notifyAt"] == 15 * 60000
    assert reminder_items({"tasks": [mine | {"assigneeId": "other"}]}, {"member_id": "me"}, now) == []
    assert reminder_items({"tasks": [mine]}, {"member_id": "me"}, datetime(2026, 11, 8, 11, 2, tzinfo=RIYADH)) == []


def test_schedule_persists_in_storage_backups_and_excel_and_batch_edits_roll_back(workspace):
    store, owner = workspace
    store.put(owner, "tasks", scheduled())
    saved = store.read(owner)[0]["tasks"][0]
    restored = prepare_import(store.backup_bytes(store.read(owner)[0]))["data"]["tasks"][0]
    assert restored["dueTime"] == "11:00" and restored["reminderEnabled"] and restored["reminderMinutes"] == 15
    sheet = load_workbook(io.BytesIO(tasks_excel(store.read(owner)[0]))).active
    row = dict(zip([c.value for c in sheet[1]], [c.value for c in sheet[2]]))
    assert row["وقت الاستحقاق (الرياض)"] == "11:00" and str(row["التنبيه قبل (دقيقة)"]) == "15"
    store.patch_tasks(owner, [{"id": saved["id"], "version": saved["version"], "changes": {"dueTime": "19:00", "reminderMinutes": 5}}])
    current = store.read(owner)[0]["tasks"][0]
    assert current["dueTime"] == "19:00" and current["reminderMinutes"] == 5
    before = store.read(owner)
    with pytest.raises(WorkspaceError):
        store.patch_tasks(owner, [{"id": current["id"], "version": current["version"], "changes": {"dueDate": ""}}])
    assert store.read(owner) == before
    with pytest.raises(Conflict):
        store.patch_tasks(owner, [{"id": saved["id"], "version": saved["version"], "changes": {"dueTime": "12:00"}}])
    with pytest.raises(WorkspaceError): store.put(owner, "tasks", scheduled(id="bad", dueTime="24:00"))


def test_import_does_not_merge_distinct_times_on_the_same_date(workspace):
    store, owner = workspace
    store.put(owner, "tasks", scheduled(reminderEnabled=False))
    state = store.read(owner)[0]
    incoming = copy.deepcopy(state)
    incoming["tasks"] = [incoming["tasks"][0] | {"dueTime": "19:00"}]
    additions, report = build_merge(store.backup_bytes(incoming), state, "p_general")
    assert report["tasks_added"] == 1 and additions["tasks"][0]["dueTime"] == "19:00"


def test_ai_edits_validate_time_against_the_existing_task_date():
    state = {"tasks": [scheduled()], "members": []}
    guards = {"tasks": {"timed": 1}}
    result = normalize_actions([{"kind": "task_update", "target_id": "timed", "values": {"dueTime": "19:00"}}], state, "p_general", guards)
    assert result[0]["values"]["dueTime"] == "19:00"
    with pytest.raises(WorkspaceError):
        normalize_actions([{"kind": "task_update", "target_id": "timed", "values": {"dueDate": ""}}], state, "p_general", guards)


def test_task_editor_and_table_store_time_and_reminder_settings(workspace, monkeypatch):
    store, owner = workspace
    monkeypatch.setenv("DATABASE_URL", str(store.engine.url))
    monkeypatch.setenv("GDAY_LOCAL_MODE", "true")
    source = '''
import os
import streamlit as st
from workspace import Store
from components import edit_task
store=Store(os.environ['DATABASE_URL'])
token=st.session_state['token']
state,_,actor=store.context(token)
edit_task(store,token,state,actor)
'''
    app = AppTest.from_string(source, default_timeout=20)
    app.session_state["token"] = owner
    app.run()
    element(app.text_input, "عنوان المهمة").set_value("موعد اجتماع")
    element(app.text_input, "وقت الاستحقاق — بتوقيت الرياض").set_value("02:30")
    element(app.selectbox, "صباح / مساء").set_value("مساءً")
    element(app.checkbox, "تنبيه صوتي للمهمة").check()
    element(app.selectbox, "التنبيه قبل").set_value(5)
    element(app.button, "حفظ المهمة").click().run()
    healthy(app)
    saved = store.read(owner)[0]["tasks"][0]
    assert saved["dueTime"] == "14:30" and saved["reminderEnabled"] and saved["reminderMinutes"] == 5
    full = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py"), default_timeout=20)
    full.session_state["token"] = owner
    full.run(); full.radio(key="navigation").set_value("المهام").run()
    healthy(full)
    assert any("وقت الاستحقاق" in list(grid.value.columns) for grid in full.dataframe)
    view = hashlib.sha256(json.dumps([[saved["id"]], "", "", "كل المهام"]).encode()).hexdigest()[:14]
    full.session_state["grid_" + view] = {"edited_rows": {0: {"وقت الاستحقاق": "04:45", "صباح / مساء": "مساءً", "قبل (دقيقة)": 30}}, "added_rows": [], "deleted_rows": []}
    element(full.button, "حفظ تعديلات الجدول").click().run()
    healthy(full)
    edited = store.read(owner)[0]["tasks"][0]
    assert edited["dueTime"] == "16:45" and edited["reminderMinutes"] == 30 and edited["reminderEnabled"]


def test_reminder_titles_are_escaped_before_becoming_client_data():
    from datetime import timedelta
    now = datetime.now(RIYADH) + timedelta(hours=1)
    value = scheduled(title='</script><img src=x onerror="alert(1)">', dueDate=now.date().isoformat(), dueTime=now.strftime("%H:%M"), assigneeId="me")
    html = reminders_html({"tasks": [value]}, {"id": "user", "member_id": "me"})
    assert '<img src=x' not in html and "\\u003c/script\\u003e" in html
    assert html.count("</script>") == 1


def test_clock_and_audio_share_a_single_top_level_initializer(monkeypatch):
    import workspace_clock
    captured = []
    monkeypatch.setattr(workspace_clock.st, "html", lambda body, **kw: captured.append(body))
    workspace_clock.render_clock(reminders_html({"tasks": []}, {"id": "me", "member_id": "me"}))
    class Scripts(HTMLParser):
        def __init__(self): super().__init__(); self.stack = []; self.depths = []
        def handle_starttag(self, tag, attrs):
            if tag == "script": self.depths.append(len(self.stack))
            self.stack.append(tag)
        def handle_endtag(self, tag):
            if tag in self.stack:
                self.stack = self.stack[:len(self.stack)-1-self.stack[::-1].index(tag)]
    parser = Scripts()
    parser.feed(captured[0])
    assert parser.depths == [0]
    assert "gdayTaskReminders" in captured[0] and "gdayTimer" in captured[0]


def test_component_sends_reminder_data_without_embedding_titles_in_code(monkeypatch):
    import task_reminders
    from datetime import timedelta
    captures = []
    monkeypatch.setattr(task_reminders, "_task_header", lambda **kwargs: captures.append(kwargs))
    monkeypatch.setattr(task_reminders.st, "fragment", lambda **kwargs: lambda fn: fn)
    now = datetime.now(RIYADH) + timedelta(hours=1)
    title = '</script><img src=x onerror="alert(1)">'
    value = scheduled(title=title, assigneeId="me", dueDate=now.date().isoformat(), dueTime=now.strftime("%H:%M"))
    actor = {"id": "account", "member_id": "me"}
    # The initial render uses the already authenticated snapshot, without a query.
    task_reminders.render_task_header(None, "unused", {"tasks": [value]}, actor)
    assert captures[0]["data"]["items"][0]["title"] == title
    assert captures[0]["data"]["account"] == "account"


def test_client_requires_a_gesture_and_rings_once_then_cancels_on_completion(tmp_path):
    node = shutil.which("node")
    if not node: pytest.skip("Node is unavailable for the browser-independent audio contract")
    from task_reminders import REMINDERS
    data = {"account": "me", "items": [{"id": "t", "title": "موعد تجريبي", "due": 100000, "notifyAt": 90000, "key": "t|100000|0"}]}
    script = re.search(r"<script>([\s\S]*)</script>", REMINDERS).group(1).replace("__REMINDER_DATA__", json.dumps(data))
    harness = Path(__file__).with_name("reminder_contract.cjs")
    result = subprocess.run([node, str(harness)], input=json.dumps({"script": script}), text=True, capture_output=True, timeout=15)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["checks"] == "passed"
