import time

import pytest
from sqlalchemy import event, update

from workspace import Forbidden, Store, sessions, users
from tests.test_workspace import workspace, task


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
