"""ליגה חדשה מזריעה את עצמה: הנתונים מגיעים מהדפדפן, ולכן ליגה בלי
שורות בשרת לא הופיעה ב"לפי יום" — ומי שלא נכנס לטאב שלה לא היה רואה
אותה אף פעם (הגביעים, 19.9.26)."""
from fastapi.testclient import TestClient

import main

HTML = open("index.html", encoding="utf-8").read()


def test_leagues_without_a_single_match_are_reported_to_the_client(db):
    db.execute("INSERT INTO matches (id, league_key, home_team, away_team, date_utc, "
               "time_utc, status) VALUES ('s1', 'carabao', 'Bournemouth', 'Aston Villa', "
               "'2026-10-28', '19:45:00', 'TIMED')")
    db.commit()
    r = TestClient(main.app).get("/matches/by_date/2026-10-28").json()
    assert "carabao" not in r["empty_leagues"]          # יש לה משחק — לא ריקה
    for key in ("facup", "dfbpokal", "copadelrey", "coupedefrance"):
        assert key in r["empty_leagues"], key
    # פרמייר ליג נשלפת בשרת (football-data), לא מהדפדפן
    assert "premier" not in r["empty_leagues"]


def test_the_client_seeds_them_once_per_visit():
    assert "let seededThisVisit = false;" in HTML
    block = HTML[HTML.index("const empty = (data.empty_leagues"):]
    block = block[:block.index("}")]
    assert "!autoRefreshed.has(lk)" in block
    assert "!HIDDEN_LEAGUES.has(lk)" in block          # ליגה שהוסרה לא נמשכת
    seeding = HTML[HTML.index("seededThisVisit = true;"):][:600]
    assert "slice(0, 5)" in seeding                    # חמשת הגביעים בפתיחה אחת
    assert "for (const lk of batch) await refreshLeague(lk);" in seeding
