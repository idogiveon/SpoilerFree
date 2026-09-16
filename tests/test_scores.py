"""תוצאות: נשלחות רק כשמבקשים במפורש. ברירת המחדל בכל מכשיר — כבוי."""
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

import pytest

import main
from test_auth import ADMIN, FRIEND, client


@pytest.fixture
def auth_on(monkeypatch, mails):
    monkeypatch.setattr(main, "AUTH_ON", True)
    monkeypatch.setattr(main, "ADMIN_EMAILS", {ADMIN})
    return mails


def _finished(db, mid="s1", league="laliga", hs=2, aw=1):
    past = datetime.now(timezone.utc) - timedelta(hours=20)
    db.execute("INSERT INTO matches (id, league_key, home_team, away_team, date_utc, time_utc, "
               "status, home_score, away_score) VALUES (?, ?, 'Barcelona', 'Getafe', ?, ?, "
               "'FINISHED', ?, ?)",
               (mid, league, past.strftime("%Y-%m-%d"), past.strftime("%H:%M:%S"), hs, aw))
    db.commit()
    return past


def test_scores_are_never_sent_unless_asked(db):
    _finished(db)
    m = TestClient(main.app).get("/matches/laliga").json()["matches"][0]
    assert "home_score" not in m and "away_score" not in m


def test_scores_are_sent_when_asked(db):
    _finished(db)
    m = TestClient(main.app).get("/matches/laliga?scores=1").json()["matches"][0]
    assert (m["home_score"], m["away_score"]) == (2, 1)


def test_day_view_follows_the_same_rule(db):
    past = _finished(db)
    day = past.astimezone(main.ISRAEL_TZ).strftime("%Y-%m-%d")
    c = TestClient(main.app)
    plain = c.get(f"/matches/by_date/{day}").json()["matches"]
    asked = c.get(f"/matches/by_date/{day}?scores=1").json()["matches"]
    assert plain and "home_score" not in plain[0]
    assert asked and (asked[0]["home_score"], asked[0]["away_score"]) == (2, 1)


def test_a_match_still_playing_has_no_score_to_give(db):
    db.execute("INSERT INTO matches (id, league_key, home_team, away_team, date_utc, time_utc, status) "
               "VALUES ('s2', 'laliga', 'A', 'B', '2027-01-01', '20:00:00', 'SCHEDULED')")
    db.commit()
    r = TestClient(main.app).get("/score/s2").json()
    assert r == {"available": False}


def test_single_match_score(db):
    _finished(db, "s3")
    assert TestClient(main.app).get("/score/s3").json() == {"available": True, "home": 2, "away": 1}
    assert TestClient(main.app).get("/score/nope").status_code == 404


def test_default_is_off_and_can_be_changed(auth_on):
    c = client()
    c.post("/auth/register", json={"email": FRIEND, "password": "goodpass1"})
    assert c.get("/prefs").json()["scores_default"] == "off"
    assert c.post("/prefs", json={"scores_default": "all"}).json()["ok"]
    assert c.get("/prefs").json()["scores_default"] == "all"
    assert c.post("/prefs", json={"scores_default": "match"}).status_code == 200
    assert c.post("/prefs", json={"scores_default": "everything"}).status_code == 400


def test_deleting_the_account_clears_the_preference(auth_on):
    c = client()
    c.post("/auth/register", json={"email": FRIEND, "password": "goodpass1"})
    c.post("/prefs", json={"scores_default": "all"})
    c.post("/auth/delete_account", json={"confirm": FRIEND})
    conn = main.get_db()
    assert conn.execute("SELECT COUNT(*) AS n FROM prefs").fetchone()["n"] == 0
    conn.close()


def test_scores_are_stored_from_both_sources():
    sdb = main._sportsdb_rows([{"idEvent": "e1", "strHomeTeam": "A", "strAwayTeam": "B",
                               "dateEvent": "2026-09-16", "intHomeScore": "3", "intAwayScore": "0",
                               "strStatus": "Match Finished"}])
    assert (sdb["e1"]["home_score"], sdb["e1"]["away_score"]) == (3, 0)
    assert "home_score" in main._MATCH_COLS and "away_score" in main._MATCH_COLS
