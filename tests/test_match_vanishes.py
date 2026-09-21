"""משחק שכבר התחיל לא נמחק ברענון.

מכבי חיפה–עירוני טבריה (19.9.26, 20:00): המשתמש פתח את המשחק ב-22:39,
הסטטוס ב-DB עוד לא עודכן, הלקוח רענן את הליגה — והרענון מחק את המשחק
עצמו, כי הוא לא חזר מהמקור. החלון נפתח מחדש על משחק שכבר לא קיים,
קיבל 404, והציג "⏳ undefined".
"""
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

import main

HTML = open("index.html", encoding="utf-8").read()


def _insert(db, mid, when, status="SCHEDULED"):
    db.execute("INSERT INTO matches (id, league_key, home_team, away_team, date_utc, "
               "time_utc, status) VALUES (?, 'israel', 'Maccabi Haifa', 'Ironi Tiberias', "
               "?, ?, ?)",
               (mid, when.strftime("%Y-%m-%d"), when.strftime("%H:%M:%S"), status))
    db.commit()


def _purge_without(db, keep_id="other"):
    """רענון שהמקור לא החזיר בו את המשחק הקיים."""
    incoming = {keep_id: {c: None for c in main._MATCH_COLS}}
    incoming[keep_id].update({"home_team": "A", "away_team": "B", "status": "SCHEDULED",
                              "date_utc": "2026-12-01", "time_utc": "18:00:00"})
    return main._sync_league_rows(db, "israel", incoming, purge=True)


def test_a_match_that_already_kicked_off_survives(db):
    started = datetime.now(timezone.utc) - timedelta(hours=2)
    _insert(db, "2493578", started)
    _purge_without(db)
    assert db.execute("SELECT 1 FROM matches WHERE id='2493578'").fetchone()


def test_a_match_still_to_come_is_still_removed(db):
    """מה שכן: משחק עתידי שהמקור כבר לא מכיר — נמחק כמו קודם."""
    later = datetime.now(timezone.utc) + timedelta(days=3)
    _insert(db, "future1", later)
    _purge_without(db)
    assert db.execute("SELECT 1 FROM matches WHERE id='future1'").fetchone() is None


def test_a_finished_match_is_still_kept(db):
    old = datetime.now(timezone.utc) - timedelta(days=5)
    _insert(db, "done1", old, status="FINISHED")
    _purge_without(db)
    assert db.execute("SELECT 1 FROM matches WHERE id='done1'").fetchone()


def test_the_match_is_still_there_right_after_the_refresh(db):
    """הרצף המלא: משחק שהתחיל → רענון → פתיחת החלון עובדת."""
    started = datetime.now(timezone.utc) - timedelta(hours=2)
    _insert(db, "2493578", started)
    _purge_without(db)
    r = TestClient(main.app).get("/highlights/2493578?lang=he")
    assert r.status_code == 200
    assert r.json()["reason_code"] in ("stale", "not_over")


def test_an_error_reply_never_reaches_the_screen_as_undefined():
    """כל שגיאה שאינה 401 הגיעה לכל קורא כגוף {"detail": ...}. הבדיקה
    עברה ל-apiFetch עצמו, כי היו עוד עשרה מקומות עם אותה חשיפה."""
    block = HTML[HTML.index("async function apiFetch("):]
    block = block[:block.index("\n  }")]
    assert "if (!r.ok) {" in block
    assert "throw err;" in block
    assert "|| t('search_error');" in HTML
