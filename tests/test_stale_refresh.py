"""משחק שהפתיחה שלו עברה אבל לא מסומן כגמור: הדפדפן מרענן את הליגה בעצמו
(גם מ"לפי יום"), במקום לשלוח את המשתמש לטאב הליגה."""
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

import main


def _insert(db, mid, when, status="SCHEDULED", league="laliga"):
    db.execute("INSERT INTO matches (id, league_key, home_team, away_team, date_utc, time_utc, status) "
               "VALUES (?, ?, 'Espanyol', 'Osasuna', ?, ?, ?)",
               (mid, league, when.strftime("%Y-%m-%d"), when.strftime("%H:%M:%S"), status))
    db.commit()


def test_stale_sportsdb_match_asks_browser_to_refresh(db):
    _insert(db, "m1", datetime.now(timezone.utc) - timedelta(hours=20))
    r = TestClient(main.app).get("/highlights/m1").json()
    assert r["available"] is False
    assert r["needs_refresh"] is True and r["league_key"] == "laliga"
    assert "טאב הליגה" not in r["reason"]          # לא שולחים לעמוד אחר


def test_future_match_does_not_ask_refresh(db):
    _insert(db, "m2", datetime.now(timezone.utc) + timedelta(days=2))
    r = TestClient(main.app).get("/highlights/m2").json()
    assert r["available"] is False and not r.get("needs_refresh")


def test_by_date_flags_stale_matches_only(db):
    kick = datetime.now(timezone.utc) - timedelta(hours=20)
    _insert(db, "stale", kick)
    _insert(db, "done", kick + timedelta(minutes=5), status="FINISHED")
    il_day = kick.astimezone(main.ISRAEL_TZ).strftime("%Y-%m-%d")
    res = TestClient(main.app).get(f"/matches/by_date/{il_day}").json()
    flags = {m["id"]: m["needs_refresh"] for m in res["matches"]}
    assert flags["stale"] is True and flags["done"] is False
