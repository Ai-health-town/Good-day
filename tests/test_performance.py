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
