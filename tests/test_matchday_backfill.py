"""דפדוף לכל המחזורים: מחזור שלא נשלף מעולם נמשך לפי דרישה ונשמר (MLS 2–23)."""
from fastapi.testclient import TestClient

import main

OLD_ROUND = [{"idEvent": "mls5a", "intRound": "5", "dateEvent": "2026-03-21", "strTime": "23:30:00",
              "strHomeTeam": "Philadelphia Union", "strAwayTeam": "Chicago Fire",
              "strStatus": "Match Finished"},
             {"idEvent": "mls5b", "intRound": "5", "dateEvent": "2026-03-21", "strTime": "23:30:00",
              "strHomeTeam": "Toronto FC", "strAwayTeam": "Columbus Crew",
              "strStatus": "Match Finished"}]


def test_old_round_is_added_without_touching_existing(db):
    db.execute("INSERT INTO matches (id, league_key, home_team, away_team, date_utc, time_utc, "
               "matchday, status) VALUES ('mls26', 'mls', 'LA Galaxy', 'Austin', '2026-09-13', "
               "'02:00:00', 26, 'FINISHED')")
    db.commit()
    c = TestClient(main.app)
    r = c.post("/refresh/mls", json={"events": OLD_ROUND, "purge": False})
    assert r.json()["stored"] == 2
    rows = db.execute("SELECT id, matchday FROM matches WHERE league_key='mls' ORDER BY id").fetchall()
    assert [(x["id"], x["matchday"]) for x in rows] == [("mls26", 26), ("mls5a", 5), ("mls5b", 5)]


def test_matchday_list_covers_every_round_and_fetches_on_demand():
    html = open("index.html", encoding="utf-8").read()
    # רשימת המחזורים: 1..האחרון (ולא רק אלה שקיימים בנתונים)
    assert "Array.from({ length: present[present.length - 1] }, (_, i) => i + 1)" in html
    # מחזור ריק → משיכה של אותו מחזור בלבד, ושמירה בלי purge
    assert "eventsround.php?id=${id}&r=${md}&s=${cfg.season}" in html
    assert "JSON.stringify({ events, purge: false })" in html
