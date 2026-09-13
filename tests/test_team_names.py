"""שמות קבוצות לפי שפה (תצוגה בלבד — לא משנה חיפושים)."""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

import main


@pytest.mark.parametrize("name, lang, expected", [
    ("Charlton Athletic", "he", "צ'רלטון"),
    ("Inter Miami", "he", "אינטר מיאמי"),          # לא "אינטר" (התאמה חלקית ב-HEB_TEAMS)
    ("Sporting Kansas City", "he", "ספורטינג קנזס סיטי"),
    ("Hapoel Tel-Aviv", "he", "הפועל תל אביב"),
    ("Real Madrid", "he", "ריאל מדריד"),           # קיים ב-HEB_TEAMS — עדיין עובד
    ("Arsenal FC", "en", "Arsenal"),
    ("AFC Bournemouth", "en", "Bournemouth"),
    ("Bayern Munich", "es", "Bayern de Múnich"),
    ("Barcelona", "fr", "FC Barcelone"),
    ("Wrexham", "fr", "Wrexham"),
    ("Some New Team", "he", "Some New Team"),        # לא מוכר — השם המקורי
])
def test_display_team(name, lang, expected):
    assert main.display_team(name, lang) == expected


def test_display_names_do_not_change_hebrew_search_names():
    # HEB_TEAMS (חיפושים) לא הוחלף — חוץ משתי הקבוצות הישראליות שהיו חסרות
    assert main.to_hebrew_team("Hapoel Tel-Aviv") == "הפועל תל אביב"
    assert main.to_hebrew_team("Maccabi Petah Tikva") == "מכבי פתח תקווה"
    assert main.to_hebrew_team("Charlton Athletic") == "Charlton Athletic"


def test_endpoints_return_names_in_requested_language(db):
    when = datetime.now(timezone.utc) + timedelta(days=1)
    db.execute("INSERT INTO matches (id, league_key, home_team, away_team, date_utc, time_utc, status) "
               "VALUES ('c1', 'championship', 'Charlton Athletic', 'Portsmouth', ?, ?, 'SCHEDULED')",
               (when.strftime("%Y-%m-%d"), when.strftime("%H:%M:%S")))
    db.commit()
    c = TestClient(main.app)
    m = c.get("/matches/championship?lang=he").json()["matches"][0]
    assert (m["home"], m["home_name"], m["away_name"]) == ("Charlton Athletic", "צ'רלטון", "פורטסמות'")
    assert c.get("/matches/championship?lang=en").json()["matches"][0]["home_name"] == "Charlton Athletic"
    day = when.astimezone(main.ISRAEL_TZ).strftime("%Y-%m-%d")
    assert c.get(f"/matches/by_date/{day}?lang=he").json()["matches"][0]["away_name"] == "פורטסמות'"
    assert c.get("/matches/championship?lang=xx").json()["matches"][0]["home_name"] == "צ'רלטון"


def test_highlights_club_source_name_in_language(db, monkeypatch):
    monkeypatch.setattr(main, "search_youtube", lambda *a, **k: [])
    monkeypatch.setattr(main, "resolve_web_link", lambda *a, **k: None)
    past = datetime.now(timezone.utc) - timedelta(hours=20)
    db.execute("INSERT INTO matches (id, league_key, home_team, away_team, date_utc, time_utc, status) "
               "VALUES ('c2', 'championship', 'Charlton Athletic', 'Portsmouth', ?, ?, 'FINISHED')",
               (past.strftime("%Y-%m-%d"), past.strftime("%H:%M:%S")))
    db.commit()
    c = TestClient(main.app)
    names = {s["club_team"]: s["club_name"] for s in c.get("/highlights/c2?lang=he").json()["sources"] if s["club_team"]}
    assert names == {"Charlton Athletic": "צ'רלטון", "Portsmouth": "פורטסמות'"}
