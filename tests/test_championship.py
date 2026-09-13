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


def test_sources_for_championship_match():
    row = {"league_key": "championship", "home_team": "Southampton", "away_team": "Bristol City",
           "home_team_id": None, "away_team_id": None}
    assert [s["id"] for s in main.get_sources_for_match(row)] == ["sky_efl"]
