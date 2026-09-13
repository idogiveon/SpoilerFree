"""ONE (לה ליגה, סריה A): כותרות חדשותיות בעברית — כותרות אמיתיות מה-RSS (11–13.9.26)."""
import pytest

import main

H = main.to_hebrew_team


@pytest.mark.parametrize("title, home, away", [
    ("חוזרת לנצח: אספניול גוברת על אוססונה 0:2", "Espanyol", "Osasuna"),
    ("ריאל מדריד חוזרת לנצח לאחר 1:4 על ראיו", "Real Madrid", "Rayo Vallecano"),
    ("90 דק' לרביבו: אלצ'ה ובילבאו נפרדות ב1:1", "Elche", "Athletic Bilbao"),
    ("בלתי מנוצחות: 2:2 אדיר בין לאציו למילאן", "Lazio", "AC Milan"),
    ("סוף למומנטום: ראסינג הכניעה את אלאבס", "Racing de Santander", "Deportivo Alavés"),
    ("פיורנטינה מפרקת את ונציה עם רביעייה", "Fiorentina", "Venezia"),
    ("איגלסיאס מעניק לסביליה ניצחון על ולנסיה", "Sevilla", "Valencia"),
])
def test_both_teams_in_headline(title, home, away):
    assert main.is_headline_highlight(title, H(home), H(away))


def test_single_team_only_within_two_days():
    t = "מלדיני מוביל את קליארי לעוד ניצחון"
    assert main.is_headline_highlight(t, H("Cagliari"), H("Sassuolo"), "2026-09-12T21:04:00+00:00", "2026-09-12")
    assert not main.is_headline_highlight(t, H("Cagliari"), H("Sassuolo"), "2026-09-17T21:04:00+00:00", "2026-09-12")
    assert not main.is_headline_highlight(t, H("Cagliari"), H("Sassuolo"))   # בלי תאריך — לא מנחשים


@pytest.mark.parametrize("title, home, away", [
    # נוסטלגיה / שורטס
    ("חמישה שערים ובישול לכריסטיאנו, בדיוק היום ב-2015 🔥 ריאל מדריד ניצחה 6:0 את אספניול #כדורגלטוק #one",
     "Real Madrid", "Espanyol"),
    ("אוהדי ברצלונה - מתגעגעים? בדיוק היום ב-2008, סרחיו בוסקטס עלה להופעת בכורה נגד ראסינג #כדורגלטוק",
     "Barcelona", "Racing de Santander"),
    ("גולאסו באימון: לאמין עובר את השוער וכובש עם העקב #כדורגלטוק #one #foryou", "Barcelona", "Getafe"),
    # "ריאל"/"מדריד" לבד לא מזהים קבוצה
    ("ריאל מדריד חוזרת לנצח לאחר 1:4 על ראיו", "Atlético Madrid", "Getafe"),
    ("ריאל מדריד חוזרת לנצח לאחר 1:4 על ראיו", "Real Sociedad", "Getafe"),
])
def test_not_a_highlight(title, home, away):
    assert not main.is_headline_highlight(title, H(home), H(away), "2026-09-12T20:00:00+00:00", "2026-09-12")


def test_one_sources_use_headline_mode():
    for key in ("laliga", "seriea"):
        one = next(s for s in main.LEAGUES[key]["sources"] if s["name"] == "ONE")
        assert one["headline_titles"] and one["hebrew_names"]
        assert "תקציר" not in one["search_template"]


def test_search_finds_one_headline_via_rss(monkeypatch):
    feed = [
        ("nost", "חמישה שערים, בדיוק היום ב-2015 ריאל מדריד ניצחה 6:0 את אספניול #כדורגלטוק",
         "2026-09-12T11:44:00+00:00"),
        ("hl", "חוזרת לנצח: אספניול גוברת על אוססונה 0:2", "2026-09-12T16:55:00+00:00"),
        ("old", "ישן", "2026-09-01T10:00:00+00:00"),
    ]
    monkeypatch.setattr(main, "_rss_feed", lambda cid: feed)
    res = main.search_youtube("Espanyol", "Osasuna", "2026-09-12", "UCgbHJENV6UgIZl1Rp_GXCfw",
                              home_alt=H("Espanyol"), away_alt=H("Osasuna"), headline=True)
    assert [v["video_id"] for v in res] == ["hl"]
