"""מסכי פתיחה (#32): ליגות מועדפות, קבוצות פופולריות, פעם אחת לחשבון."""
import pytest
from fastapi.testclient import TestClient

import main
from test_auth import ADMIN, FRIEND, client


@pytest.fixture
def auth_on(monkeypatch, mails):
    monkeypatch.setattr(main, "AUTH_ON", True)
    monkeypatch.setattr(main, "ADMIN_EMAILS", {ADMIN})
    return mails


def _register(email=FRIEND):
    c = client()
    assert c.post("/auth/register", json={"email": email, "password": "goodpass1"}).status_code == 200
    return c


def test_new_user_sees_onboarding_once(auth_on):
    c = _register()
    assert c.get("/auth/me").json()["onboarded"] is False
    assert c.post("/auth/onboarded").json()["ok"]
    assert c.get("/auth/me").json()["onboarded"] is True


def test_existing_favorites_skip_onboarding(auth_on):
    c = _register()
    c.post("/favorites", json={"team": "Liverpool", "on": True})
    assert c.get("/auth/me").json()["onboarded"] is True


def test_favorite_leagues(auth_on):
    c = _register()
    assert c.post("/favorites", json={"league": "laliga", "on": True}).json()["ok"]
    assert c.post("/favorites", json={"league": "nope", "on": True}).status_code == 400
    assert c.get("/favorites").json()["leagues"] == ["laliga"]
    assert c.get("/auth/me").json()["onboarded"] is True          # יש כבר מועדפים
    c.post("/favorites", json={"league": "laliga", "on": False})
    assert c.get("/favorites").json()["leagues"] == []


def test_delete_account_removes_favorite_leagues(auth_on):
    c = _register()
    c.post("/favorites", json={"league": "laliga", "on": True})
    assert c.post("/auth/delete_account", json={"confirm": FRIEND}).json()["ok"]
    conn = main.get_db()
    assert conn.execute("SELECT COUNT(*) AS n FROM favorite_leagues").fetchone()["n"] == 0
    conn.close()


def _match(db, mid, league, home, away):
    db.execute("INSERT INTO matches (id, league_key, home_team, away_team, date_utc, time_utc, status) "
               "VALUES (?, ?, ?, ?, '2026-09-20', '14:00:00', 'SCHEDULED')", (mid, league, home, away))
    db.commit()


def test_popular_teams_in_curated_order_then_filled(db):
    for i, (h, a) in enumerate([("Brentford", "Arsenal"), ("Liverpool", "Everton"),
                                ("Manchester City", "Fulham")]):
        _match(db, f"p{i}", "premier", h, a)
    _match(db, "s1", "seriea", "Inter", "Genoa")
    res = TestClient(main.app).get("/onboarding/teams?leagues=premier,seriea,bogus&lang=en").json()["leagues"]
    assert list(res) == ["premier", "seriea"]
    keys = [t["key"] for t in res["premier"]]
    k = main.team_key
    assert keys[:3] == [k("Arsenal"), k("Liverpool"), k("Manchester City")]      # לפי הפופולריות
    assert len(keys) == 6 and k("Brentford") in keys                           # הושלם מהנתונים
    assert res["seriea"][0]["key"] == k("Inter")                                # "Inter Milan" ↔ "Inter"


def test_onboarding_wired_in_app():
    html = open("index.html", encoding="utf-8").read()
    assert ".then(maybeOnboard)" in html and "FAV_LEAGUES.has(m.league_key)" in html
