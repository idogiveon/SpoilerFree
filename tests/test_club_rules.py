"""ערוצי מועדונים עם פורמט משלהם: PSG (תוצאה בכותרת), שחטאר (אוקראינית + תאריך)."""
import main

UCL = main.LEAGUES["ucl"]["club_channels"]


def _row(home, away):
    return {"league_key": "ucl", "home_team": home, "away_team": away,
            "home_team_id": None, "away_team_id": None}


def test_psg_title_with_score():
    def ok(title):
        return main.is_match_highlight(title, "Paris Saint-Germain", "Slovan Bratislava",
                                       None, None, False, "Paris Saint-Germain")
    assert ok("RETOUR EN FORCE EN LIGUE DES CHAMPIONS I PSG 6-1 BRATISLAVA")
    assert not ok("CHAMPIONS LEAGUE Kick-off 26-27! ⚽️🔴🔵")                 # בלי היריבה
    assert not ok("Six goals to kick off our Champions League campaign! 💪 #PSG #UCL")


def test_score_counts_when_both_teams_are_identified():
    """תוצאה + שתי הקבוצות = תקציר בכל ערוץ (TV2 הנורווגי כותב רק תוצאה).
    תוצאה בלי היריבה — רק בערוץ של המועדון עצמו."""
    assert main.is_match_highlight("PSG 6-1 BRATISLAVA", "Paris Saint-Germain", "Slovan Bratislava")
    assert not main.is_match_highlight("CHAMPIONS LEAGUE Kick-off 26-27! ⚽️🔴🔵",
                                       "Paris Saint-Germain", "Slovan Bratislava")


def test_shakhtar_date_rule(monkeypatch):
    feed = [
        ("s1", "ПСВ – Шахтар – 1:1. Повернення Ліги чемпіонів! Голи та огляд матчу (10.09.2026)",
         "2026-09-11T21:02:13+00:00"),
        ("s2", "НЛМ U14. ПРО Ліга. Шахтар – АФ Рух – 2:0. Огляд матчу (12.09.2026)",
         "2026-09-12T14:00:00+00:00"),
        ("s3", "UYL. ПСВ U19 – Шахтар U19 – 2:1. Огляд матчу (10.09.2026)", "2026-09-10T18:00:00+00:00"),
        ("s4", "🧡 Арда Туран – про дебют у Лізі чемпіонів та гру з ПСВ 👊 #Shakhtar #UCL",
         "2026-09-10T21:11:00+00:00"),
    ]
    monkeypatch.setattr(main, "_rss_feed", lambda cid: feed)
    monkeypatch.setattr(main, "_video_durations", lambda ids: {})
    src = next(s for s in main.get_sources_for_match(_row("PSV Eindhoven", "Shakhtar Donetsk"))
               if s.get("club_team") == "Shakhtar Donetsk")
    assert src["channel_id"] == UCL["Shakhtar Donetsk"] and src["title_date"]
    res = main.search_youtube("PSV Eindhoven", "Shakhtar Donetsk", "2026-09-10", src["channel_id"],
                              title_include=src["title_include"], title_exclude=src["title_exclude"],
                              implicit_team="Shakhtar Donetsk", date_in_title=True)
    assert [v["video_id"] for v in res] == ["s1"]
    assert res[0]["published"] == "2026-09-11T21:02:13+00:00"


def test_psg_channel_used():
    srcs = main.get_sources_for_match(_row("Paris Saint-Germain", "Slovan Bratislava"))
    assert srcs[0]["channel_id"] == UCL["Paris Saint-Germain"]
