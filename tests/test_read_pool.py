import pytest
from sqlalchemy import create_engine, event, update
from sqlalchemy.exc import DBAPIError

import workspace as persistence
from workspace import Forbidden, Store, workspaces
from tests.test_workspace import PASSWORD, task


@pytest.fixture
def remote_store(tmp_path, monkeypatch):
    # Exercise both real pools and invalidation/reconnect locally, with the
    # production remote policy but without a dependency on private credentials.
    url = "sqlite:///" + str(tmp_path / "pools.db")
    engines = []
    def local_engine(_url, **options):
        options["connect_args"] = {"timeout": 30, "check_same_thread": False}
        engine = create_engine(url, **options)
        engines.append(engine)
        return engine
    monkeypatch.setattr(persistence, "create_engine", local_engine)
    store = Store("postgresql+psycopg://test-only.invalid/test")
    store.bootstrap("owner", PASSWORD)
    token = store.login("owner", PASSWORD)
    yield store, token
    for engine in engines:
        engine.dispose()


def test_warm_reads_need_no_ping_and_writes_keep_their_ping(remote_store, monkeypatch):
    store, token = remote_store
    assert store.engine is not store._read_engine
    store.context(token)
    pings = []
    def track_ping(_):
        pings.append(True)
        return True
    monkeypatch.setattr(store.engine.dialect, "do_ping", track_ping)
    monkeypatch.setattr(store._read_engine.dialect, "do_ping", track_ping)
    queries = []
    event.listen(store._read_engine, "before_cursor_execute", lambda *args: queries.append(args[2]))
    for _ in range(3):
        store.context(token)
    assert len(queries) == 3 and not pings
    with store._read_connection() as conn:
        assert conn.connection.driver_connection.isolation_level is None  # Native autocommit.
    store.put(token, "tasks", task("still-transactional"))
    assert pings
    assert store.context(token)[0]["tasks"][0]["id"] == "still-transactional"


def test_closed_idle_read_connection_is_replaced_before_returning_a_result(remote_store):
    store, token = remote_store
    before = store.context(token)
    with store._read_engine.connect() as conn:
        idle = conn.connection.driver_connection
    idle.close()
    assert store.context(token) == before
    assert store.actor(token)["role"] == "admin"


@pytest.mark.parametrize("invalidated,expected_attempts", [(False, 1), (True, 2)])
def test_failed_reads_retry_only_disconnects_and_only_once(remote_store, invalidated, expected_attempts):
    store, token = remote_store
    calls = []
    def fail(*args):
        calls.append(True)
        raise DBAPIError("SELECT", None, RuntimeError("test connection failure"), connection_invalidated=invalidated)
    event.listen(store._read_engine, "before_cursor_execute", fail)
    with pytest.raises(DBAPIError):
        store.context(token)
    assert len(calls) == expected_attempts


def test_reconnect_revalidates_a_session_revoked_during_the_failed_read(remote_store):
    store, token = remote_store
    store.context(token)
    calls = []
    def revoke_then_disconnect(*args):
        calls.append(True)
        if len(calls) == 1:
            store.logout(token)
            raise DBAPIError("SELECT", None, RuntimeError("test disconnect"), connection_invalidated=True)
    event.listen(store._read_engine, "before_cursor_execute", revoke_then_disconnect)
    with pytest.raises(Forbidden):
        store.context(token)
    assert len(calls) == 2


def test_session_expiring_between_read_attempts_is_rejected(remote_store, monkeypatch):
    store, token = remote_store
    clock = [persistence.time.time()]
    with store.transaction() as conn:
        conn.execute(update(persistence.sessions).values(expires=clock[0] + 1))
    monkeypatch.setattr(persistence.time, "time", lambda: clock[0])
    calls = []
    def pass_expiry_before_retry(*args):
        calls.append(True)
        if len(calls) == 1:
            clock[0] += 2
            raise DBAPIError("SELECT", None, RuntimeError("test disconnect"), connection_invalidated=True)
    event.listen(store._read_engine, "before_cursor_execute", pass_expiry_before_retry)
    with pytest.raises(Forbidden):
        store.context(token)
    assert len(calls) == 2


def test_write_failures_are_never_replayed_and_still_roll_back(remote_store):
    store, token = remote_store
    before = store.read(token)
    calls = []
    def fail_save(conn, cursor, statement, parameters, context, many):
        if statement.startswith("UPDATE gday_workspace"):
            calls.append(True)
            raise DBAPIError(statement, None, RuntimeError("test write failure"), connection_invalidated=True)
    event.listen(store.engine, "before_cursor_execute", fail_save)
    with pytest.raises(DBAPIError):
        store.put(token, "tasks", task("never-saved"))
    assert len(calls) == 1
    assert store.read(token) == before
    with pytest.raises(ValueError, match="Only SELECT"):
        store._read_one(update(workspaces).values(revision=999))


def test_postgres_driver_recognizes_the_disconnects_used_by_the_read_retry():
    from types import SimpleNamespace
    import psycopg
    from sqlalchemy.dialects.postgresql.psycopg import PGDialect_psycopg
    dialect = PGDialect_psycopg(dbapi=psycopg)
    error = psycopg.OperationalError("test disconnected connection")
    assert dialect.is_disconnect(error, SimpleNamespace(closed=True, broken=False), None)
    assert dialect.is_disconnect(error, SimpleNamespace(closed=False, broken=True), None)
    assert not dialect.is_disconnect(error, SimpleNamespace(closed=False, broken=False), None)
