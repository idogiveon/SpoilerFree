"""ליגה אירופית: לוח מ-TheSportsDB, ערוצי מועדונים, ספורט 5, שמות בעברית."""
import main

# 36 הקבוצות של שלב הליגה (TheSportsDB, מחזורים 1–2, 13.9.26)
UEL_TEAMS = [
    "AC Milan", "AZ Alkmaar", "Anderlecht", "Ararat-Armenia", "Bayer Leverkusen", "Benfica", "Beşiktaş",
    "Bournemouth", "Celje", "Celta Vigo", "Celtic", "Crystal Palace", "Dinamo Zagreb", "Ferencváros",
    "Hapoel Be'er Sheva", "Hoffenheim", "Jagiellonia Białystok", "Juventus", "Lech Poznań", "Levski Sofia",
    "Lillestrøm", "Lyon", "Marseille", "NEC Nijmegen", "OFI", "Olympiacos", "Omonia Nicosia",
    "Real Sociedad", "Red Bull Salzburg", "Rennes", "Sparta Prague", "Sturm Graz", "Sunderland",
    "Torreense", "Union Saint-Gilloise", "Viktoria Plzeň",
]


def test_uel_config():
    cfg = main.LEAGUES["uel"]
    assert cfg["sportsdb_ids"] == ["4481"] and cfg["min_date"] == "2026-09-01"
    assert all(t in UEL_TEAMS for t in cfg["club_channels"])


def test_every_uel_team_has_a_hebrew_name():
    english = [t for t in UEL_TEAMS if main.display_team(t, "he") == t]
    assert english == []
    assert main.display_team("Lillestrøm", "he") == "לילסטרום"     # לא "ליל" (התאמה חלקית)


def _row(home, away):
    return {"league_key": "uel", "home_team": home, "away_team": away,
            "home_team_id": None, "away_team_id": None}


def test_sources():
    """להפועל באר שבע אין ערוץ שמעלה תקצירים, ולכן המקור היחיד למשחק שלה
    הוא הערוץ של היריבה (דינמו זאגרב נוסף 26.9.26)."""
    assert [s["club_team"] for s in
            main.get_sources_for_match(_row("Hapoel Be'er Sheva", "Dinamo Zagreb"))
            ] == ["Dinamo Zagreb"]
    assert [s["club_team"] for s in main.get_sources_for_match(_row("Celtic", "Ferencváros"))] == ["Celtic"]


def test_no_israeli_web_source_yet():
    """ספורט 5 כנראה לא משדרים את הליגה האירופית — המקור הישראלי ייקבע
    אחרי מחזור 1, כשיהיה ברור איפה התקצירים עולים."""
    assert not main.LEAGUES["uel"].get("web_sources")


# ── M2 (2.10.26): המשחקים שאין להם מקור, ומה המסך אומר עליהם ────────
def test_a_match_with_no_club_channel_says_so_about_the_match(db):
    """בליגה האירופית 64 מתוך 72 המשחקים מכוסים דרך ערוץ של אחת
    הקבוצות. בשמונה הנותרים לשתיהן אין ערוץ — ושם המסך אמר "מקור
    תקצירים לליגה זו עדיין לא הוגדר · בקרוב". שתי אמירות לא נכונות:
    לליגה יש מקורות, ו"בקרוב" הוא הבטחה שלא תתקיים (בדקתי את שלושת
    המשחקים ששוחקו — אין להם תקציר באף ערוץ רשמי)."""
    from fastapi.testclient import TestClient
    db.execute("INSERT INTO matches (id, league_key, home_team, away_team, date_utc, "
               "time_utc, status) VALUES ('m2a', 'uel', 'OFI', 'Hoffenheim', "
               "'2026-09-17', '19:00:00', 'FINISHED')")
    db.commit()
    out = TestClient(main.app).get("/highlights/m2a?client=2").json()
    assert out["sources"] == []
    assert out["no_source_scope"] == "match"


def test_a_covered_match_does_not_get_that_message(db):
    from fastapi.testclient import TestClient
    db.execute("INSERT INTO matches (id, league_key, home_team, away_team, date_utc, "
               "time_utc, status) VALUES ('m2b', 'uel', 'OFI', 'AC Milan', "
               "'2026-09-17', '19:00:00', 'FINISHED')")
    db.commit()
    out = TestClient(main.app).get("/highlights/m2b?client=2").json()
    assert out["no_source_scope"] is None


def test_the_client_tells_the_two_apart():
    html = open("index.html", encoding="utf-8").read()
    assert "data.no_source_scope === 'match'" in html
    for key in ('"no_source_match":', '"no_source_match_hint":'):
        assert html.count(key) == 4, key
