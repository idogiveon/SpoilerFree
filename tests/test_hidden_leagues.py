"""הסתרת ליגה: לא מוצגת ב"לפי יום"; הסתרה מוציאה מהמועדפות; נמחקת עם החשבון."""
import pytest

import main
from test_auth import ADMIN, FRIEND, client


@pytest.fixture
def auth_on(monkeypatch, mails):
    monkeypatch.setattr(main, "AUTH_ON", True)
    monkeypatch.setattr(main, "ADMIN_EMAILS", {ADMIN})
    return mails


def _register():
    c = client()
    assert c.post("/auth/register", json={"email": FRIEND, "password": "goodpass1"}).status_code == 200
    return c


def test_hide_and_unhide_league(auth_on):
    c = _register()
    assert c.post("/favorites", json={"hide_league": "ligue1", "on": True}).json()["ok"]
    assert c.get("/favorites").json()["hidden"] == ["ligue1"]
    assert c.post("/favorites", json={"hide_league": "nope", "on": True}).status_code == 400
    c.post("/favorites", json={"hide_league": "ligue1", "on": False})
    assert c.get("/favorites").json()["hidden"] == []


def test_hiding_a_favorite_league_removes_it_from_favorites(auth_on):
    c = _register()
    c.post("/favorites", json={"league": "ligue1", "on": True})
    c.post("/favorites", json={"hide_league": "ligue1", "on": True})
    f = c.get("/favorites").json()
    assert f["leagues"] == [] and f["hidden"] == ["ligue1"]


def test_delete_account_removes_hidden_leagues(auth_on):
    c = _register()
    c.post("/favorites", json={"hide_league": "ligue1", "on": True})
    c.post("/auth/delete_account", json={"confirm": FRIEND})
    conn = main.get_db()
    assert conn.execute("SELECT COUNT(*) AS n FROM hidden_leagues").fetchone()["n"] == 0
    conn.close()


def test_day_view_filters_hidden_leagues_in_app():
    html = open("index.html", encoding="utf-8").read()
    assert "HIDDEN_LEAGUES.has(m.league_key)" in html
