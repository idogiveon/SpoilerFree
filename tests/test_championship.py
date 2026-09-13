"""צ'מפיונשיפ: תקצירי Sky Sports Football (ערוץ רב-ליגתי ועמוס)."""
import pytest

import main

SKY = main.LEAGUES["championship"]["sources"][0]


@pytest.mark.parametrize("title, home, away, expected", [
    # כותרות אמיתיות מה-RSS של Sky Sports Football (12.9.26)
    ("Larin double as Saints score FOUR! | Southampton 4-1 Bristol City | EFL Highlights",
     "Southampton", "Bristol City", True),
    ("Draper snatches late win for Lincoln! 💥 | Preston 0-1 Lincoln | EFL Highlights",
     "Preston North End", "Lincoln City", True),
    # ליג 1 באותו ערוץ — לא המשחק שלנו
    ("Irow SCREAMER in Pilgrims win! | Plymouth 3-0 Barnsley | EFL Highlights",
     "Southampton", "Bristol City", False),
    # קיצורים של Sky (מבנה כותרת זהה)
    ("Late drama at Molineux | Wolves 2-1 QPR | EFL Highlights",
     "Wolverhampton Wanderers", "Queens Park Rangers", True),
    ("Points shared | West Brom 1-1 Sheff Utd | EFL Highlights",
     "West Bromwich Albion", "Sheffield United", True),
])
def test_sky_titles(title, home, away, expected):
    assert main.is_match_highlight(title, home, away) is expected


@pytest.mark.parametrize("title, home, away, club, expected", [
    # כותרות אמיתיות מערוצי המועדונים (RSS, 8–13.9.26) — הערוץ הוא של club
    ("HIGHLIGHTS | Wanderers v Cardiff City", "Bolton Wanderers", "Cardiff City", "Bolton Wanderers", True),
    ("Highlights 🟡 | Charlton v Pompey", "Charlton Athletic", "Portsmouth", "Portsmouth", True),
    ("Highlights | PNE 0-1 Lincoln City", "Preston North End", "Lincoln City", "Preston North End", True),
    ("Callum Styles’ strike earns point | Albion 1-1 QPR | MATCH HIGHLIGHTS",
     "West Bromwich Albion", "Queens Park Rangers", "West Bromwich Albion", True),
    ("Southampton 4-1 Bristol City | Extended Highlights", "Southampton", "Bristol City", "Bristol City", True),
    ("Extended Highlights: Rovers 3-1 Millwall", "Blackburn Rovers", "Millwall", "Blackburn Rovers", True),
    # תוכן אחרי המשחק — לא תקציר
    ("POST-MATCH ANALYSIS | Southampton 4-1 Bristol City", "Southampton", "Bristol City", "Bristol City", False),
    ("John Mousinho post-match 🎙️ | Charlton v Pompey", "Charlton Athletic", "Portsmouth", "Portsmouth", False),
    # סיומת כללית לא מספיקה לבד: ערוצים שגויים שהיו "עוברים" בגלל City/County
    ("Riis Brace Fires Foxes To Victory | Stockport County 3-4 Leicester City | Extended Highlights",
     "Lincoln City", "Bristol City", "Lincoln City", False),
    ("HIGHLIGHTS | NOTTS COUNTY 0-1 BRADFORD CITY", "Middlesbrough", "Norwich City", "Norwich City", False),
])
def test_club_channel_titles(title, home, away, club, expected):
    assert main.is_match_highlight(title, home, away, implicit_team=club) is expected


def test_sources_clubs_first_then_sky():
    def ids(home, away):
        row = {"league_key": "championship", "home_team": home, "away_team": away,
               "home_team_id": None, "away_team_id": None}
        return [s["id"] for s in main.get_sources_for_match(row)]
    assert ids("Southampton", "Bristol City") == ["club_southampton", "club_bristol-city", "sky_efl"]
    assert ids("Lincoln City", "Wrexham") == ["sky_efl"]          # בלי ערוץ פעיל — רק Sky


def test_title_include_drops_other_leagues(monkeypatch):
    feed = [
        ("laliga", "Mbappe and Bellingham star again! | Real Madrid 4-1 Rayo Vallecano | La Liga Highlights",
         "2026-09-12T20:00:00+00:00"),
        ("efl", "Larin double as Saints score FOUR! | Southampton 4-1 Bristol City | EFL Highlights",
         "2026-09-12T19:00:00+00:00"),
        ("old", "Older video", "2026-09-01T10:00:00+00:00"),
    ]
    monkeypatch.setattr(main, "_rss_feed", lambda cid: feed)
    res = main.search_youtube("Southampton", "Bristol City", "2026-09-12", SKY["channel_id"],
                              title_include=SKY["title_include"])
    assert [v["video_id"] for v in res] == ["efl"]


