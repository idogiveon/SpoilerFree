"""דוח צפייה בתקצירים: לפי ליגה, לפי משתמש, ומוטמע מול חיצוני.

הבעלים ביקש (20.10.26) לדעת כמה תקצירים ראה בשבוע, כמה מכל ליגה, וכמה
נצפו אצלנו מול כמה נשלחו ליוטיוב. השאלה האחרונה לא הייתה ניתנת למענה:
openOnYoutube ו-loadVideo ירו את אותו אירוע בדיוק. מכאן שני סוגים.
"""
from datetime import timedelta

from fastapi.testclient import TestClient

import main


def _ev(db, email, typ, ts, match_id=None):
    db.execute("INSERT INTO events (email, ts, type, match_id) VALUES (?,?,?,?)",
               (email, ts.isoformat(), typ, match_id))


def _match(db, mid, league):
    db.execute("INSERT INTO matches (id, league_key, home_team, away_team, date_utc, "
               "time_utc, status) VALUES (?,?,'A','B','2026-10-18','20:00','FINISHED')",
               (mid, league))


def test_the_split_counts_by_league_and_by_way(db):
    now = main._now()
    db.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('embed_split_since', ?)",
               ((now - timedelta(days=2)).isoformat(),))
    _match(db, "m1", "premier")
    _match(db, "m2", "laliga")
    _ev(db, "a@x.com", "highlight_play", now - timedelta(hours=1), "m1")
    _ev(db, "a@x.com", "highlight_external", now - timedelta(hours=2), "m1")
    _ev(db, "b@x.com", "highlight_play", now - timedelta(hours=3), "m2")
    db.commit()

    r = TestClient(main.app).get("/admin/api/report?days=7").json()
    assert r["totals"] == {"embedded": 2, "external": 1, "unknown": 0, "total": 3}
    assert r["by_league"]["premier"]["embedded"] == 1
    assert r["by_league"]["premier"]["external"] == 1
    assert r["by_league"]["laliga"]["total"] == 1
    assert r["by_user"]["a@x.com"]["total"] == 2


def test_what_came_before_the_split_is_called_unknown(db):
    """לא לנחש: עד הפיצול highlight_play כיסה גם פתיחה ביוטיוב."""
    now = main._now()
    db.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('embed_split_since', ?)",
               ((now - timedelta(hours=1)).isoformat(),))
    _match(db, "m1", "israel")
    _ev(db, "a@x.com", "highlight_play", now - timedelta(days=3), "m1")   # לפני
    _ev(db, "a@x.com", "highlight_play", now - timedelta(minutes=5), "m1")  # אחרי
    db.commit()

    r = TestClient(main.app).get("/admin/api/report?days=7").json()
    assert r["totals"]["unknown"] == 1
    assert r["totals"]["embedded"] == 1


def test_with_no_marker_nothing_is_claimed_as_embedded(db):
    _match(db, "m1", "israel")
    _ev(db, "a@x.com", "highlight_play", main._now(), "m1")
    db.commit()
    r = TestClient(main.app).get("/admin/api/report?days=7").json()
    assert r["split_since"] is None
    assert r["totals"] == {"embedded": 0, "external": 0, "unknown": 1, "total": 1}


def test_the_period_is_respected(db):
    _match(db, "m1", "israel")
    _ev(db, "a@x.com", "highlight_play", main._now() - timedelta(days=20), "m1")
    db.commit()
    c = TestClient(main.app)
    assert c.get("/admin/api/report?days=7").json()["totals"]["total"] == 0
    assert c.get("/admin/api/report?days=30").json()["totals"]["total"] == 1


def test_the_external_event_is_accepted_by_track():
    assert "highlight_external" in main.EVENT_TYPES
    html = open("index.html", encoding="utf-8").read()
    yt = html[html.index("function openOnYoutube("):]
    assert "track('highlight_external'" in yt[:yt.index("\n  }")]


def test_the_admin_page_shows_the_report():
    page = TestClient(main.app).get("/admin/users").text
    for bit in ("צפייה בתקצירים", "loadReport", "rep_lg", "לא ידוע"):
        assert bit in page, bit
