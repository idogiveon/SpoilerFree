"""MLS: תקצירי הערוץ הרשמי — כותרות אמיתיות מה-RSS (13.9.26)."""
import pytest

import main

MLS = main.LEAGUES["mls"]["sources"][0]


@pytest.mark.parametrize("title, home, away, expected", [
    ("St. Louis CITY vs. Minnesota United | Full Match Highlights | Rafael Navarro BRACE!",
     "St. Louis City SC", "Minnesota United", True),
    ("Sporting Kansas City vs. LAFC | Full Match Highlights | André Luiz STUNNER!",
     "Sporting Kansas City", "Los Angeles FC", True),
    ("D.C. United vs. Atlanta United | Full Match Highlights", "DC United", "Atlanta United", True),
    ("Real Salt Lake vs. New York City FC | Full Match Highlights | Nico Fernández Mercau BLAST!",
     "Real Salt Lake", "New York City FC", True),
    ("Colorado Rapids vs. CF Montréal | Full Match Highlights", "Colorado Rapids", "CF Montréal", True),
    ("FC Dallas vs. Portland Timbers | Full Match Highlights", "FC Dallas", "Portland Timbers", True),
    ("San Jose Earthquakes vs. Houston Dynamo FC | Full Match Highlights | DEFENSIVE BATTLE!",
     "San Jose Earthquakes", "Houston Dynamo", True),
    # קליפ של שחקן — קבוצה אחת בלבד
    ("Jordan Morris to Paul Arriola EQUALIZER FOR SEATTLE!🔥", "LA Galaxy", "Seattle Sounders", False),
    # LA Galaxy ≠ LAFC
    ("LA Galaxy vs. Seattle Sounders FC | Full Match Highlights", "Los Angeles FC", "Seattle Sounders", False),
    # "SC" קצר מדי לזיהוי לבד (היה נמצא ב-"scores" וכו')
    ("Nashville scores late | Columbus Crew vs. Chicago Fire | Full Match Highlights",
     "St. Louis City SC", "Chicago Fire", False),
])
def test_mls_titles(title, home, away, expected):
    assert main.is_match_highlight(title, home, away) is expected


def test_mls_search_keeps_only_highlights(monkeypatch):
    feed = [
        ("clip", "Sam Surridge TIED THE GAME LATE🚨 in Miami!", "2026-09-13T04:00:00+00:00"),
        ("hl", "Orlando City vs. Toronto FC | Full Match Highlights | GRITTY Griezmann goal!",
         "2026-09-13T03:00:00+00:00"),
        ("old", "Older video", "2026-09-01T10:00:00+00:00"),
    ]
    monkeypatch.setattr(main, "_rss_feed", lambda cid: feed)
    res = main.search_youtube("Orlando City", "Toronto FC", "2026-09-12", MLS["channel_id"],
                              title_include=MLS["title_include"])
    assert [v["video_id"] for v in res] == ["hl"]
