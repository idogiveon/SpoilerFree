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
    assert ".then(maybeOnboard)" in html
    assert "seen.sort((a, b) => leagueRank(a) - leagueRank(b))" in html


# ── ביקורת מוצר (26.9.26): שלושת הפתוחים במסך הפתיחה ─────────────────
PAGE = open("index.html", encoding="utf-8").read()


def test_the_hint_points_at_something_that_exists_after_the_screen_closes():
    """ההבטחה הייתה "ב-⚙ שליד הליגות" — אבל שורת הטאבים מגיעה סגורה
    ונשארת סגורה ב"לפי יום", כלומר ברגע שהמסך נסגר אין ⚙ על המסך."""
    import re
    hints = re.findall(r'"ob_hint1": "(.*?)"', PAGE)
    assert len(hints) == 4
    assert all("⚙" not in h and "☰" in h for h in hints), hints


def test_skip_says_what_it_actually_does():
    """המשפט מעל הכפתור אומר "רק הן יוצגו", ו"דלג" נתן 17 ליגות."""
    import re
    skips = re.findall(r'"ob_skip": "(.*?)"', PAGE)
    assert len(skips) == 4
    assert all(len(s) > len("דלג") for s in skips), skips


def test_continue_with_nothing_picked_is_not_a_silent_skip():
    assert "next.disabled = !sel.size" in PAGE
    # וגם אומר למה: כפתור מושבת לא יורה אירוע, כלומר אפס משוב בטלפון
    assert "need.hidden = !!sel.size" in PAGE
    assert PAGE.count('"ob_pick_one":') == 4
    assert ".ob-next:disabled" in PAGE


def test_the_feed_is_not_painted_before_the_hidden_leagues_are_known():
    """loadDay() התחיל לפני ש-loadFavorites חזר, ולכן הפיד נצבע עם כל
    17 הליגות ורק אחר כך הצטמצם."""
    assert "favsReady = loadUserBar().then(loadFavorites);" in PAGE
    assert "if (favsReady) { try { await favsReady; } catch (e) {} }" in PAGE
    # הבקשה עצמה עדיין יוצאת במקביל — רק הצביעה מחכה
    boot = PAGE[PAGE.index("favsReady = loadUserBar()"):]
    assert boot.index("enterDayView();") < boot.index("loadScorePref")
