"""מסכי הפתיחה היו איטיים (פידבק חיצוני, 19.9.26): בקשה לכל ליגה ולכל
קבוצה. כל חיבור ל-Turso מסנכרן מול הענן, אז המחיר הזה שולם שוב ושוב."""
import pytest

import main
from test_auth import ADMIN, FRIEND, client

HTML = open("index.html", encoding="utf-8").read()


@pytest.fixture
def user(monkeypatch, mails):
    monkeypatch.setattr(main, "AUTH_ON", True)
    monkeypatch.setattr(main, "ADMIN_EMAILS", {ADMIN})
    c = client()
    assert c.post("/auth/register", json={"email": FRIEND, "password": "goodpass1"}).status_code == 200
    return c


def test_everything_is_saved_in_one_request(user):
    auth_client = user
    r = auth_client.post("/favorites/bulk",
                         json={"teams": ["Liverpool FC", "Maccabi Haifa"],
                               "leagues": ["premier", "carabao"]})
    assert r.json() == {"ok": True, "teams": 2, "leagues": 2}
    favs = auth_client.get("/favorites").json()
    assert set(favs["favorites"]) == {main.team_key("Liverpool FC"), main.team_key("Maccabi Haifa")}
    assert set(favs["leagues"]) == {"premier", "carabao"}


def test_a_favorite_league_stops_being_hidden(user):
    auth_client = user
    auth_client.post("/favorites", json={"hide_league": "premier", "on": True})
    assert "premier" in auth_client.get("/favorites").json()["hidden"]
    auth_client.post("/favorites/bulk", json={"leagues": ["premier"]})
    assert "premier" not in auth_client.get("/favorites").json()["hidden"]


def test_junk_never_reaches_the_database(user):
    auth_client = user
    r = auth_client.post("/favorites/bulk",
                         json={"teams": ["", "  "], "leagues": ["not_a_league"]})
    assert r.json()["teams"] == 0 and r.json()["leagues"] == 0


def test_the_client_saves_once_and_locks_the_button():
    """הכפתור היה נשאר לחיץ בזמן השמירה, ולכן נלחץ שוב ושוב."""
    assert "async function saveFavsBulk(" in HTML
    block = HTML[HTML.index("done.onclick = async () => {"):]
    block = block[:block.index("finishOnboarding();")]
    assert "if (done.disabled) return;" in block
    assert "done.disabled = true;" in block
    assert "t('saving')" in block
    assert "await toggleFav(" not in block          # לא עוד בקשה לכל קבוצה


def test_leagues_and_teams_are_fetched_together():
    block = HTML[HTML.index("async function onboardTeams("):]
    block = block[:block.index("const chosen")]
    assert "Promise.all([" in block
    assert "for (const l of leagues) if (!FAV_LEAGUES.has(l)) toggleFavLeague" not in block


def test_the_teams_query_runs_once_for_all_leagues():
    src = open("main.py", encoding="utf-8").read()
    block = src[src.index('def onboarding_teams('):]
    block = block[:block.index("return {\"leagues\": out}")]
    assert "WHERE league_key IN ({marks})" in block
    assert block.count("conn.execute") == 1


def test_a_cup_offers_the_big_clubs_of_its_country():
    """בלי זה, מסך הפתיחה היה מציע את מוקדמות הגביע האנגלי לפי א\"ב."""
    assert main.POPULAR_TEAMS["carabao"] == main.POPULAR_TEAMS["premier"]
    assert main.POPULAR_TEAMS["dfbpokal"] == main.POPULAR_TEAMS["bundesliga"]
    assert "Real Madrid" in main.POPULAR_TEAMS["copadelrey"]


def test_a_team_is_offered_under_one_league_only(db):
    """ריאל מדריד הופיעה גם תחת לה ליגה וגם תחת צ'מפיונס — שני צ'יפים
    לאותה בחירה, וסימון שניהם ביטל אותה."""
    for i, (lg, home, away) in enumerate([("laliga", "Real Madrid", "Barcelona"),
                                          ("ucl", "Real Madrid", "Bayern Munich")]):
        db.execute("INSERT INTO matches (id, league_key, home_team, away_team, date_utc, "
                   "time_utc, status) VALUES (?, ?, ?, ?, '2026-09-20', '20:00:00', 'TIMED')",
                   (f"d{i}", lg, home, away))
    db.commit()
    import main as m
    from fastapi.testclient import TestClient
    data = TestClient(m.app).get("/onboarding/teams?leagues=laliga,ucl").json()["leagues"]
    keys = [t["key"] for ts in data.values() for t in ts]
    assert len(keys) == len(set(keys)), keys
