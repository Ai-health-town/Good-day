import time
import copy
import io
from pathlib import Path

import pytest
from sqlalchemy import event, update
from sqlalchemy.engine import Engine
from streamlit.testing.v1 import AppTest

from workspace import Forbidden, Store, WorkspaceError, sessions, users
from tests.test_workspace import workspace, task
from tests.test_file_preview import workbook_bytes
from tests.test_ui import element, healthy


def capture_queries(store):
    queries = []

    def capture(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            queries.append((statement, parameters))

    event.listen(store.engine, "before_cursor_execute", capture)
    return queries


def test_warm_page_uses_one_query_without_retransferring_workspace(workspace):
    store, token = workspace
    initial, revision, actor = store.context(token)
    assert store.initialized()
    queries = capture_queries(store)
    assert store.initialized()
    state, current_revision, current_actor = store.context(token)
    assert (state, current_revision, current_actor) == (initial, revision, actor)
    assert len(queries) == 1
    sql, parameters = queries[0]
    assert "password_hash" not in sql
    with store.engine.connect() as conn:
        row = conn.exec_driver_sql(sql, parameters).mappings().one()
    assert row["workspace_payload"] is None
    assert row["workspace_revision"] == revision


def test_another_worker_update_is_returned_in_the_same_single_query(workspace):
    store, token = workspace
    old, revision, _ = store.context(token)
    other = Store(str(store.engine.url))
    other.put(token, "tasks", task("from_other_worker"))
    queries = capture_queries(store)
    state, current_revision, _ = store.context(token)
    assert len(queries) == 1
    assert current_revision == revision + 1
    assert state["tasks"][0]["id"] == "from_other_worker"
    assert old["tasks"] == []
    sql, parameters = queries[0]
    with store.engine.connect() as conn:
        row = conn.exec_driver_sql(sql, parameters).mappings().one()
    assert row["workspace_payload"] is not None
    state["tasks"][0]["title"] = "غير محفوظ"
    assert store.read(token)[0]["tasks"][0]["title"] == "متابعة العمل"


@pytest.mark.parametrize("change", ["logout", "expiry", "disabled"])
def test_cached_workspace_never_bypasses_live_session_validation(workspace, change):
    store, token = workspace
    ident = store.create_user(token, "live_reader", "عضو اختبار", "Test-only-password-739!", "member")
    member = store.login("live_reader", "Test-only-password-739!")
    store.context(member)
    other = Store(str(store.engine.url))
    if change == "logout":
        other.logout(member)
    elif change == "disabled":
        other.update_user(token, ident, "member", False, False)
    else:
        with other.transaction() as conn:
            conn.execute(update(sessions).values(expires=time.time()-1))
    for read in (store.context, store.read, store.actor):
        with pytest.raises(Forbidden):
            read(member)


def test_cold_reads_use_one_query_and_never_return_password_hash(workspace):
    store, token = workspace
    fresh = Store(str(store.engine.url))
    queries = capture_queries(fresh)
    _, _, actor = fresh.context(token)
    assert len(queries) == 1
    assert "password_hash" not in queries[0][0]
    assert "password_hash" not in actor


def test_bootstrap_detection_waits_for_accounts_then_stays_cached(tmp_path):
    url = "sqlite:///" + str(tmp_path/"bootstrap.db")
    first, second = Store(url), Store(url)
    assert not first.initialized()
    second.bootstrap("owner", "Test-only-password-739!")
    queries = capture_queries(first)
    assert first.initialized()
    assert first.initialized()
    assert len(queries) == 1


def test_inflight_read_keeps_its_snapshot_when_a_write_invalidates_the_cache(workspace):
    store, token = workspace
    _, revision, _ = store.context(token)
    armed = True

    def update_during_read(conn, cursor, statement, parameters, context, executemany):
        nonlocal armed
        if armed and statement.lstrip().upper().startswith("SELECT") and "gday_workspace" in statement:
            armed = False
            store.put(token, "tasks", task("during_read"))

    event.listen(store.engine, "after_cursor_execute", update_during_read)
    state, read_revision, _ = store.context(token)
    assert read_revision == revision
    assert state["tasks"] == []
    fresh, fresh_revision, _ = store.context(token)
    assert fresh_revision == revision + 1
    assert fresh["tasks"][0]["id"] == "during_read"


def test_shared_payload_cache_does_not_share_or_cache_account_permissions(workspace):
    store, owner = workspace
    ident = store.create_user(owner, "permission_reader", "قارئ الاختبار", "Test-only-password-739!", "viewer")
    reader = store.login("permission_reader", "Test-only-password-739!")
    _, revision, owner_actor = store.context(owner)
    _, reader_revision, reader_actor = store.context(reader)
    assert revision == reader_revision
    assert owner_actor["role"] == "admin"
    assert reader_actor["role"] == "viewer"
    assert owner_actor["id"] != reader_actor["id"]
    with store.engine.begin() as conn:
        conn.execute(update(users).where(users.c.id == ident).values(role="member"))
    _, same_revision, changed_actor = store.context(reader)
    assert same_revision == revision
    assert changed_actor["role"] == "member"


def test_successful_save_reuses_its_committed_snapshot_without_downloading_it_again(workspace):
    store, token = workspace
    original = task("committed")
    store.put(token, "tasks", original)
    original["title"] = "تعديل غير محفوظ"
    queries = capture_queries(store)
    state, revision, _ = store.context(token)
    assert state["tasks"][0]["title"] == "متابعة العمل"
    assert len(queries) == 1
    with store.engine.connect() as conn:
        row = conn.exec_driver_sql(*queries[0]).mappings().one()
    assert row["workspace_payload"] is None
    assert row["workspace_revision"] == revision


def test_rolled_back_snapshot_is_never_published_or_reused_by_the_next_transaction(workspace):
    store, token = workspace
    before, revision = store.read(token)
    with pytest.raises(RuntimeError):
        with store.transaction() as conn:
            changed = copy.deepcopy(before)
            changed["tasks"].append(task("rolled_back"))
            store._save(conn, changed, revision)
            raise RuntimeError("test rollback")
    with store.transaction() as conn:
        store._actor(conn, token)
    assert store.read(token) == (before, revision)


def test_original_cache_is_bounded_and_does_not_bypass_live_access(workspace):
    from filetools import parse_upload
    from tests.test_neon_ai import attach_storage
    store, owner = workspace
    client = attach_storage(store)
    store.add_files(owner, [parse_upload(f"file{i}.txt", f"original{i}".encode(), "p_general") for i in range(5)])
    records = store.read(owner)[0]["files"]
    for record in records:
        assert store.file_bytes(owner, record["id"]).startswith(b"original")
    assert len(client.gets) == 5
    assert store.file_bytes(owner, records[-1]["id"]) == b"original4"
    assert len(client.gets) == 5
    assert store.file_bytes(owner, records[0]["id"]) == b"original0"
    assert len(client.gets) == 6  # Four-entry RAM cache evicts the oldest original.
    foreign = records[0]["object"] | {"bucket": "another-private"}
    with pytest.raises(WorkspaceError): store.storage.download(foreign)
    assert len(client.gets) == 6
    store.remove(owner, "files", records[0]["id"], records[0]["version"])
    with pytest.raises(WorkspaceError, match="غير موجود"): store.file_bytes(owner, records[0]["id"])
    store.logout(owner)
    with pytest.raises(Forbidden): store.file_bytes(owner, records[-1]["id"])
    assert len(client.gets) == 6


def test_deferred_download_checks_the_session_before_generating_any_bytes(workspace):
    from components import download_data
    from filetools import docx_bytes
    from docx import Document
    store, token = workspace
    calls = []
    def build():
        calls.append(True)
        return docx_bytes("تقرير", "النص المحرر")
    deferred = download_data(store, token, build)
    assert calls == []
    assert any(p.text == "النص المحرر" for p in Document(io.BytesIO(deferred())).paragraphs)
    assert len(calls) == 1
    store.logout(token)
    with pytest.raises(Forbidden): deferred()
    assert len(calls) == 1


def platform(store, token, monkeypatch, page):
    monkeypatch.setenv("DATABASE_URL", str(store.engine.url))
    monkeypatch.setenv("GDAY_LOCAL_MODE", "true")
    app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py"), default_timeout=20)
    app.session_state["token"] = token
    app.session_state["navigation"] = page
    app.run()
    healthy(app)
    return app


@pytest.mark.parametrize("page", ["المهام", "التقارير"])
def test_page_render_does_not_generate_downloads_until_the_user_requests_them(workspace, monkeypatch, page):
    import filetools
    store, token = workspace
    store.put(token, "tasks", task("export"))
    def fail(*args, **kwargs):
        raise AssertionError("Download generation should not block page rendering")
    monkeypatch.setattr(filetools, "tasks_excel", fail)
    monkeypatch.setattr(filetools, "docx_bytes", fail)
    app = platform(store, token, monkeypatch, page)
    assert len(app.get("download_button")) >= (2 if page == "التقارير" else 1)


@pytest.mark.parametrize("page,button", [("نظرة اليوم", "تحديث"), ("المهام", "تحديث الجدول"), ("الدردشات", None)])
def test_refresh_and_initial_chat_use_a_single_live_workspace_query(workspace, monkeypatch, page, button):
    store, token = workspace
    store.put(token, "tasks", task("fresh"))
    app = platform(store, token, monkeypatch, page)
    other = Store(str(store.engine.url))
    current = other.read(token)[0]["tasks"][0]
    other.put(token, "tasks", current | {"title": "آخر تعديل من زميل"}, current["version"])
    queries = []
    def capture(conn, cursor, statement, parameters, context, many):
        if statement.lstrip().upper().startswith("SELECT") and "gday_" in statement:
            queries.append(statement)
    event.listen(Engine, "before_cursor_execute", capture)
    try:
        element(app.button, button).click().run() if button else app.run()
    finally:
        event.remove(Engine, "before_cursor_execute", capture)
    healthy(app)
    assert len(queries) == 1
    if page == "المهام":
        assert app.dataframe[0].value.iloc[0]["المهمة"] == "آخر تعديل من زميل"


def test_remote_reads_use_autocommit_without_leaking_it_into_writes(workspace):
    store, token = workspace
    store.remote = True  # Exercise the remote read path against the local fixture.
    try:
        with store._read_connection() as conn:
            assert conn.get_execution_options()["isolation_level"] == "AUTOCOMMIT"
        with store.transaction() as conn:
            assert conn.get_execution_options().get("isolation_level") != "AUTOCOMMIT"
        store.put(token, "tasks", task("transactional"))
        before, revision = store.read(token)
        with pytest.raises(RuntimeError):
            with store.transaction() as conn:
                changed = copy.deepcopy(before)
                changed["tasks"][0]["title"] = "لا يُحفظ"
                store._save(conn, changed, revision)
                raise RuntimeError("rollback")
        assert store.read(token) == (before, revision)
    finally:
        store.remote = False


def test_remote_read_path_still_checks_live_sessions_and_latest_data(workspace):
    store, token = workspace
    store.remote = True
    try:
        store.context(token)
        other = Store(str(store.engine.url))
        other.put(token, "tasks", task("another_worker"))
        assert store.context(token)[0]["tasks"][0]["id"] == "another_worker"
        other.logout(token)
        for read in (store.context, store.actor, store.read):
            with pytest.raises(Forbidden): read(token)
    finally:
        store.remote = False


def test_postgres_driver_skips_only_autocommit_rollbacks():
    from types import SimpleNamespace
    from unittest.mock import Mock
    from sqlalchemy.dialects.postgresql.psycopg import PGDialect_psycopg
    dialect = PGDialect_psycopg(skip_autocommit_rollback=True)
    connection = SimpleNamespace(autocommit=True, rollback=Mock())
    dialect.do_rollback(connection)
    connection.rollback.assert_not_called()
    connection.autocommit = False
    dialect.do_rollback(connection)
    connection.rollback.assert_called_once()


def test_authenticated_navigation_does_not_wait_for_the_cookie_component(workspace, monkeypatch):
    import extra_streamlit_components as stx
    store, token = workspace
    def fail(*args, **kwargs):
        raise AssertionError("An authenticated session does not need a cookie component")
    monkeypatch.setattr(stx, "CookieManager", fail)
    app = platform(store, token, monkeypatch, "نظرة اليوم")
    app.radio(key="navigation").set_value("الجهات").run()
    healthy(app)
    element(app.button, "تحديث").click().run()
    healthy(app)


@pytest.mark.parametrize("page,label,collection", [
    ("الملفات", "بحث في الملفات", "files"),
    ("الجهات", "بحث في دليل الجهات والأشخاص", "stakeholders"),
])
def test_local_filter_reruns_only_its_fragment_and_full_refresh_gets_new_work(
    workspace, monkeypatch, page, label, collection
):
    from dataclasses import replace
    from streamlit.testing.v1.local_script_runner import LocalScriptRunner
    store, token = workspace
    field = "title" if collection == "files" else "name"
    for ident, name in (("target", "هدف"), ("other", "سجل آخر")):
        store.put(token, collection, {"id": ident, field: name, "type": "doc", "text": "نص", "projectId": "p_general"})
    app = platform(store, token, monkeypatch, page)
    search = element(app.text_input, label)
    metadata = app._session_state._state._get_widget_metadata(search.id)
    assert metadata.fragment_id
    latest = store.read(token)[0][collection][0]
    store.put(token, collection, latest | {field: "هدف محدث"}, latest["version"])
    queries = []
    def capture(conn, cursor, statement, parameters, context, many):
        if statement.lstrip().upper().startswith("SELECT") and "gday_" in statement:
            queries.append(statement)
    event.listen(Engine, "before_cursor_execute", capture)
    original = LocalScriptRunner.request_rerun
    def fragment_rerun(runner, data):
        target = replace(data, fragment_id_queue=[metadata.fragment_id])
        # A fresh AppTest runner starts with a pending full run. Replace that
        # bootstrap request too, otherwise it overrides the browser-style event.
        runner._requests._rerun_data = target
        return original(runner, target)
    try:
        # AppTest otherwise simulates a full script run. Send the same fragment
        # routing metadata as a real browser interaction for this performance check.
        with monkeypatch.context() as patch:
            patch.setattr(LocalScriptRunner, "request_rerun", fragment_rerun)
            search.set_value("هدف").run()
        healthy(app)
        assert not queries
        shown = [x.value for x in app.markdown] + [x.value for x in app.subheader]
        assert any("هدف" in x for x in shown)
        assert not any("سجل آخر" in x for x in shown)
        app.run()  # The existing refresh/navigation path always reads live data.
        healthy(app)
        assert len(queries) == 1
        shown = [x.value for x in app.markdown] + [x.value for x in app.subheader]
        assert any("هدف محدث" in x for x in shown)
    finally:
        event.remove(Engine, "before_cursor_execute", capture)


@pytest.mark.parametrize("original_excel", [False, True])
def test_spreadsheet_working_copy_generates_an_authenticated_export_only_on_download(
    workspace, workbook_bytes, monkeypatch, original_excel
):
    import components
    import sheet_preview
    import streamlit as st
    from filetools import parse_upload
    from openpyxl import load_workbook
    store, token = workspace
    record = parse_upload("تقرير.xlsx", workbook_bytes, "p_general") if original_excel else {
        "id": "plain-sheet", "title": "جدول", "type": "sheet", "projectId": "p_general",
        "sheets": [{"name": "البيانات", "rows": [["العدد"], ["0"]]}],
    }
    store.put(token, "files", record)
    monkeypatch.setenv("DATABASE_URL", str(store.engine.url))
    captured, built = {}, []
    download = st.download_button
    build = sheet_preview.edited_excel if original_excel else components.sheet_bytes
    def track_build(*args, **kwargs):
        built.append(True)
        return build(*args, **kwargs)
    monkeypatch.setattr(sheet_preview if original_excel else components, "edited_excel" if original_excel else "sheet_bytes", track_build)
    def capture(label, data, *args, **kwargs):
        captured[label] = data
        return download(label, data, *args, **kwargs)
    monkeypatch.setattr(st, "download_button", capture)
    app = AppTest.from_string('''
import copy, os
import streamlit as st
from workspace import Store
from components import file_working_copy
store = Store(os.environ['DATABASE_URL'])
token = st.session_state['test_token']
state, _, actor = store.context(token)
record = state['files'][0]
raw = store.file_bytes(token, record['id']) if record.get('blob') else None
file_working_copy(store, token, state, actor, record, copy.deepcopy(record), True, raw)
''', default_timeout=20)
    app.session_state["test_token"] = token
    app.run()
    healthy(app)
    label = "تنزيل نسخة التعديلات — Excel" if original_excel else "تنزيل الجدول المحرر — Excel"
    prepare = captured[label]
    assert callable(prepare) and not built
    book = load_workbook(io.BytesIO(prepare()))
    if original_excel:
        assert book["التوثيق"]["D4"].value == "=C4/B4"
        assert book["التوثيق"]["A1"].fill.fgColor.rgb.endswith("173D51")
    else:
        assert book.active["A2"].value == "0"
    book.close()
    assert len(built) == 1
    store.logout(token)
    with pytest.raises(Forbidden):
        prepare()
    assert len(built) == 1
