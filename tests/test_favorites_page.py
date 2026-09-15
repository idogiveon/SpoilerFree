"""עמוד המועדפים: קטלוג קבוצות (/teams) ופריט "מועדפים" בתפריט."""
from fastapi.testclient import TestClient

import main


def _match(db, mid, league, home, away):
    db.execute("INSERT INTO matches (id, league_key, home_team, away_team, date_utc, time_utc, status) "
               "VALUES (?, ?, ?, ?, '2026-09-20', '14:00:00', 'SCHEDULED')", (mid, league, home, away))
    db.commit()


def test_catalog_merges_a_team_across_competitions(db):
    _match(db, "a", "premier", "Liverpool", "Arsenal")
    _match(db, "b", "ucl", "Real Madrid", "Liverpool")
    teams = {t["key"]: t for t in TestClient(main.app).get("/teams?lang=he").json()["teams"]}
    liv = teams[main.team_key("Liverpool")]
    assert liv["leagues"] == ["premier", "ucl"]                   # סדר הטאבים
    assert liv["name"] == main.display_team("Liverpool", "he")
    assert set(teams) == {main.team_key(n) for n in ("Liverpool", "Arsenal", "Real Madrid")}
    en = {t["key"]: t for t in TestClient(main.app).get("/teams?lang=en").json()["teams"]}
    assert en[liv["key"]]["name"] == "Liverpool"


def test_catalog_requires_login(monkeypatch):
    monkeypatch.setattr(main, "AUTH_ON", True)
    assert TestClient(main.app).get("/teams").status_code == 401


def test_menu_has_favorites_entry():
    html = open("index.html", encoding="utf-8").read()
    assert "openFavorites()" in html and "async function openFavorites()" in html
