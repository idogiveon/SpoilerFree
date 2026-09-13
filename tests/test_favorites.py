"""מועדפים: לפי קבוצה בכל מפעל (מפתח אחיד), בחשבון, נפרדים בין משתמשים."""
from datetime import datetime, timedelta, timezone

import pytest

import main
from test_auth import ADMIN, FRIEND, client, login


@pytest.fixture
def auth_on(monkeypatch, mails):
    monkeypatch.setattr(main, "AUTH_ON", True)
    monkeypatch.setattr(main, "ADMIN_EMAILS", {ADMIN})
    return mails


def _friend(mails):
    client().post("/auth/request_code", json={"email": FRIEND})
    login(mails, ADMIN).post(f"/admin/api/users/{FRIEND}", json={"status": "approved"})
    return login(mails, FRIEND)


@pytest.mark.parametrize("a, b", [
    ("Liverpool FC", "Liverpool"),                       # football-data ↔ TheSportsDB
    ("Manchester City FC", "Manchester City"),
    ("AFC Bournemouth", "Bournemouth"),
    ("Tottenham Hotspur FC", "Tottenham"),
    ("Brighton & Hove Albion FC", "Brighton"),
    ("Paris Saint-Germain", "PSG"),
    ("Atlético Madrid", "Atletico Madrid"),
    ("Newell's Old Boys", "Newell s Old Boys"),
])
def test_same_team_same_key(a, b):
    assert main.team_key(a) == main.team_key(b)


@pytest.mark.parametrize("a, b", [
    ("Manchester City FC", "Manchester United FC"),
    ("Real Madrid", "Atlético Madrid"),
    ("Inter Milan", "AC Milan"),
    ("Hapoel Tel-Aviv", "Maccabi Tel Aviv"),
])
def test_different_teams_different_keys(a, b):
    assert main.team_key(a) != main.team_key(b)


def test_add_list_remove_normalizes(auth_on):
    admin = login(auth_on, ADMIN)
    assert admin.get("/favorites").json() == {"favorites": []}
    admin.post("/favorites", json={"team": "Liverpool FC", "on": True})        # שם מקור → מנורמל
    admin.post("/favorites", json={"team": "liverpool", "on": True})           # אותה קבוצה — פעם אחת
    admin.post("/favorites", json={"team": "Newell's Old Boys", "on": True})
    assert admin.get("/favorites").json()["favorites"] == ["liverpool", "newell s old boys"]
    admin.post("/favorites", json={"team": "Liverpool", "on": False})
    assert admin.get("/favorites").json()["favorites"] == ["newell s old boys"]


def test_one_favorite_applies_in_every_competition(auth_on, db):
    """ליברפול מסומנת פעם אחת → המפתח זהה במשחק פרמייר ובמשחק צ'מפיונס."""
    admin = login(auth_on, ADMIN)
    admin.post("/favorites", json={"team": "liverpool"})
    when = datetime.now(timezone.utc) + timedelta(days=1)
    for mid, lg, home in (("p1", "premier", "Liverpool FC"), ("u1", "ucl", "Liverpool")):
        db.execute("INSERT INTO matches (id, league_key, home_team, away_team, date_utc, time_utc, status) "
                   "VALUES (?, ?, ?, 'X', ?, ?, 'SCHEDULED')",
                   (mid, lg, home, when.strftime("%Y-%m-%d"), when.strftime("%H:%M:%S")))
    db.commit()
    favs = set(admin.get("/favorites").json()["favorites"])
    day = when.astimezone(main.ISRAEL_TZ).strftime("%Y-%m-%d")
    keys = {m["id"]: m["home_key"] for m in admin.get(f"/matches/by_date/{day}").json()["matches"]}
    assert keys["p1"] in favs and keys["u1"] in favs
    assert admin.get("/matches/premier").json()["matches"][0]["home_key"] == "liverpool"


def test_old_per_league_rows_are_converted_on_startup(db):
    db.execute("INSERT INTO favorites (email, league_key, team) VALUES ('a@b.c', 'premier', 'Liverpool FC')")
    db.execute("INSERT INTO favorites (email, league_key, team) VALUES ('a@b.c', 'ucl', 'Liverpool')")
    db.commit()
    main.init_db()
    rows = db.execute("SELECT league_key, team FROM favorites WHERE email='a@b.c'").fetchall()
    assert [(r["league_key"], r["team"]) for r in rows] == [("", "liverpool")]


def test_favorites_are_per_user(auth_on):
    login(auth_on, ADMIN).post("/favorites", json={"team": "Barcelona"})
    assert _friend(auth_on).get("/favorites").json()["favorites"] == []


def test_invalid_input_rejected(auth_on):
    assert login(auth_on, ADMIN).post("/favorites", json={"team": " & "}).status_code == 400


def test_requires_login(auth_on):
    assert client().get("/favorites").status_code == 401


def test_deleting_account_removes_favorites(auth_on):
    friend = _friend(auth_on)
    friend.post("/favorites", json={"team": "Barcelona"})
    friend.post("/auth/delete_account", json={"confirm": FRIEND})
    conn = main.get_db()
    assert conn.execute("SELECT COUNT(*) AS c FROM favorites WHERE email=?", (FRIEND,)).fetchone()["c"] == 0
    conn.close()


def test_without_personal_account_favorites_are_per_device(auth_on, monkeypatch):
    monkeypatch.setattr(main, "APP_PASSWORD", "pw")
    c = client()
    c.post("/login", json={"password": "pw"})
    assert c.get("/favorites").json() == {"favorites": [], "per_device": True}
    assert c.post("/favorites", json={"team": "Barcelona"}).status_code == 400
