"""פילטר כותרות התקצירים — כותרות אמיתיות מהערוצים (13.9.26)."""
import pytest

import main


@pytest.mark.parametrize("title, home, away, expected", [
    # ליג 1: בלי מילת תקציר, רק "Week N"
    ("OLYMPIQUE DE MARSEILLE - RC STRASBOURG ALSACE () | Week 1 - Ligue 1 McDonald's 26/27", "Marseille", "Strasbourg", True),
    ("TOUS LES BUTS de la 1ère journée | Ligue 1 McDonald's 26/27", "Marseille", "Strasbourg", False),
    ("Borussia Dortmund - Hamburger SV | Highlights | Bundesliga", "Borussia Dortmund", "Hamburger SV", True),
    ("HIGHLIGHTS | Porto 0-2 Man City | Haaland scores two", "Porto", "Manchester City", True),
    ("Crystal Palace 1-2 Man City | Premier League Highlights", "Crystal Palace", "Manchester City", True),
    ("תקציר: מכבי חיפה - הפועל פתח תקווה", "Maccabi Haifa", "Hapoel Petah Tikva", True),
    # צ'מפיונס — ערוצי מועדונים
    ("Le résumé vidéo de LOSC - Real Betis en Champions League (2-3)", "Lille", "Real Betis", True),
    ("Fenerbahçe 1-1 Roma ( UEFA Şampiyonlar Ligi 1. Hafta )", "Fenerbahçe", "Roma", True),
    ("ZOSTRIH | PSG – ŠK Slovan Bratislava 6:1", "Paris Saint-Germain", "Slovan Bratislava", True),
    # חייבים להיפסל
    ("Conferência de Imprensa |Rescaldo FC Porto vs. Manchester City", "Porto", "Manchester City", False),
    ("BVB U19 - Villarreal CF U19 2:3 | Highlights", "Borussia Dortmund", "Villarreal", False),
    ("Matchday LIVE! ПСВ – Шахтар | PSV vs Shakhtar", "PSV Eindhoven", "Shakhtar Donetsk", False),
    ("LIVE | La conferenza stampa al termine di #NapoliArsenal", "Napoli", "Arsenal", False),
    # בלי implicit_team — שם המועדון חסר בכותרת
    ("HIGHLIGHTS | Kicking Off the 26-27 Champions League vs Shakhtar Donetsk", "PSV Eindhoven", "Shakhtar Donetsk", False),
])
def test_filter(title, home, away, expected):
    assert main.is_match_highlight(title, home, away) is expected


def test_implicit_own_team_on_club_channel():
    t = "HIGHLIGHTS | Kicking Off the 26-27 Champions League vs Shakhtar Donetsk"
    assert main.is_match_highlight(t, "PSV Eindhoven", "Shakhtar Donetsk",
                                   implicit_team="PSV Eindhoven")


def _row(home, away):
    return {"league_key": "ucl", "home_team": home, "away_team": away,
            "home_team_id": None, "away_team_id": None}


def test_ucl_sources_both_clubs():
    s = main.get_sources_for_match(_row("Liverpool", "Atlético Madrid"))
    # קודם ערוצי המועדונים, ואחריהם מקורות הליגה (TV2 הנורווגי)
    assert [x["club_team"] for x in s if x.get("club_team")] == ["Liverpool", "Atlético Madrid"]
    assert [x["id"] for x in s if not x.get("club_team")] == ["tv2_no"]
    assert all(x["channel_id"].startswith("UC") for x in s)


def test_ucl_sources_one_or_none():
    one = main.get_sources_for_match(_row("Napoli", "Arsenal"))
    assert [x["club_team"] for x in one if x.get("club_team")] == ["Arsenal"]
    # לשתי קבוצות בלי ערוץ מועדון נשאר מקור הליגה בלבד
    assert [x["id"] for x in main.get_sources_for_match(_row("Galatasaray", "Porto"))] == ["tv2_no"]
