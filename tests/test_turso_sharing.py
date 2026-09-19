"""חיבור Turso משותף לכל התהליך.

libsql.connect() מסנכרן מול הענן, וקודם כל בקשה פתחה חיבור משלה —
לפעמים כמה, כי אותה בקשה קוראת ל-get_db() יותר מפעם אחת. כל סנכרון הוא
סבב רשת. libsql לא נבנה ל-Python 3.14, ולכן כאן הוא מדומה: מה שנבדק
הוא ההתנהגות שלנו — מתי מסנכרנים, מה קורה בכישלון, ומה קורה בו-זמנית.
"""
import threading

import pytest

import main


class FakeCursor:
    description = [("a",)]

    def fetchone(self):
        return (1,)

    def fetchall(self):
        return [(1,)]


class FakeLibsqlConn:
    def __init__(self, log):
        self.log = log
        self.closed = False
        self.fail_next_execute = False

    def execute(self, sql, params=()):
        if self.fail_next_execute:
            self.fail_next_execute = False
            raise RuntimeError("stream closed")
        self.log.append("execute")
        return FakeCursor()

    def executemany(self, sql, seq):
        self.log.append("executemany")

    def commit(self):
        self.log.append("commit")

    def sync(self):
        self.log.append("sync")

    def close(self):
        self.closed = True
        self.log.append("close")


class FakeLibsql:
    def __init__(self):
        self.log = []
        self.conns = []

    def connect(self, path, sync_url=None, auth_token=None):
        self.log.append("connect")
        c = FakeLibsqlConn(self.log)
        self.conns.append(c)
        return c


@pytest.fixture
def turso(monkeypatch):
    fake = FakeLibsql()
    monkeypatch.setattr(main, "libsql", fake)
    monkeypatch.setattr(main, "TURSO_DATABASE_URL", "libsql://example.turso.io")
    monkeypatch.setattr(main, "TURSO_SHARED", True)
    monkeypatch.setattr(main, "TURSO_SYNC_SEC", 20.0)
    monkeypatch.setattr(main, "_libsql_state",
                        {"conn": None, "synced_at": 0.0,
                         "syncs": 0, "skipped": 0, "errors": 0, "rebuilds": 0})
    return fake


def test_one_connection_serves_every_request(turso):
    for _ in range(25):
        conn = main.get_db()
        conn.execute("SELECT 1").fetchone()
        conn.close()
    assert turso.log.count("connect") == 1
    assert turso.log.count("sync") == 0          # בתוך החלון — בלי סבב רשת
    assert main._libsql_state["skipped"] == 24


def test_closing_keeps_the_shared_connection_open(turso):
    conn = main.get_db()
    conn.close()
    assert turso.conns[0].closed is False
    main.get_db().execute("SELECT 1")
    assert turso.log.count("connect") == 1


def test_the_replica_still_refreshes_on_its_own_clock(turso, monkeypatch):
    main.get_db()
    assert turso.log.count("sync") == 0
    clock = [main.time.time() + 21]
    monkeypatch.setattr(main.time, "time", lambda: clock[0])
    main.get_db()
    assert turso.log.count("sync") == 1
    main.get_db()                                 # מיד אחר כך — שוב בתוך החלון
    assert turso.log.count("sync") == 1


def test_a_write_reaches_the_cloud_immediately(turso):
    """כתיבה לא מחכה לשעון: היא חייבת להגיע לענן, ומיד קוראים אותה."""
    conn = main.get_db()
    conn.execute("INSERT INTO t VALUES (1)")
    conn.commit()
    assert turso.log[-2:] == ["commit", "sync"]


def test_a_failed_sync_does_not_take_the_site_down(turso, monkeypatch):
    clock = [main.time.time() + 21]
    monkeypatch.setattr(main.time, "time", lambda: clock[0])
    turso.conns.clear()
    main.get_db()                                  # יוצר חיבור
    def boom():
        raise RuntimeError("network")
    main._libsql_state["conn"].sync = boom
    clock[0] += 21
    conn = main.get_db()                           # סנכרון נכשל
    assert main._libsql_state["errors"] == 1
    assert conn.execute("SELECT 1").fetchone()[0] == 1     # והקריאה עובדת


def test_a_broken_connection_does_not_fail_the_request(turso):
    """אי אפשר לבדוק כאן את libsql האמיתי, ולכן תקלה בחיבור המשותף
    מורידה את הבקשה לחיבור משלה במקום להחזיר שגיאה."""
    conn = main.get_db()
    turso.conns[0].fail_next_execute = True
    assert conn.execute("SELECT 1").fetchone()[0] == 1     # עבר על חיבור טרי
    assert main._libsql_state["conn"] is None              # המשותף נזרק
    assert turso.log.count("connect") == 2


def test_after_three_failures_it_stops_sharing_by_itself(turso, monkeypatch):
    """אם libsql לא סובל שימוש מכמה threads, האתר חוזר מעצמו להתנהגות
    הישנה — בלי שאף אחד יצטרך לגעת ב-Render."""
    for _ in range(main.SHARED_FAIL_LIMIT):
        conn = main.get_db()
        main._libsql_state["conn"].fail_next_execute = True
        conn.execute("SELECT 1")
    assert main.TURSO_SHARED is False
    assert main._libsql_state["fails"] == main.SHARED_FAIL_LIMIT
    before = turso.log.count("connect")
    c = main.get_db()
    c.execute("SELECT 1")
    c.close()
    assert turso.log.count("connect") == before + 1        # חיבור לכל בקשה
    assert turso.conns[-1].closed is True


def test_the_emergency_switch_restores_a_connection_per_request(turso, monkeypatch):
    monkeypatch.setattr(main, "TURSO_SHARED", False)
    for _ in range(3):
        c = main.get_db()
        c.execute("SELECT 1")
        c.close()
    assert turso.log.count("connect") == 3
    assert turso.conns[0].closed is True


def test_threads_do_not_trip_over_each_other(turso):
    errors = []

    def work():
        try:
            for _ in range(40):
                c = main.get_db()
                c.execute("SELECT 1").fetchall()
                c.close()
        except Exception as e:      # pragma: no cover
            errors.append(e)

    threads = [threading.Thread(target=work) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    assert turso.log.count("connect") == 1


def test_the_stats_endpoint_shows_what_was_saved(turso, monkeypatch):
    from fastapi.testclient import TestClient
    monkeypatch.setattr(main, "AUTH_ON", False)
    for _ in range(5):
        main.get_db().close()
    body = TestClient(main.app).get("/debug/db").json()
    assert body["shared"] is True and body["connected"] is True
    assert body["syncs"] == 1 and body["skipped"] == 4
