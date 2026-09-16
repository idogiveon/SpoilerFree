"""ליגה הולנדית: 18 מועדונים, כל אחד בערוץ שלו (אין ערוץ ליגה שמעלה תקצירים)."""
import main

TEAMS = ["ADO Den Haag", "Ajax", "AZ Alkmaar", "Cambuur", "Excelsior", "Feyenoord",
         "Fortuna Sittard", "Go Ahead Eagles", "Groningen", "Heerenveen", "NEC Nijmegen",
         "PEC Zwolle", "PSV Eindhoven", "Sparta Rotterdam", "Telstar", "Twente",
         "Utrecht", "Willem II"]


def test_league_config():
    cfg = main.LEAGUES["eredivisie"]
    assert cfg["sportsdb_ids"] == ["4337"] and cfg["sportsdb_season"] == "2026-2027"
    assert sorted(cfg["club_channels"]) == sorted(TEAMS)
    assert all(c.startswith("UC") for c in cfg["club_channels"].values())


def test_every_team_has_a_hebrew_name():
    assert [t for t in TEAMS if main.display_team(t, "he") == t] == []


def _row(home, away):
    return {"league_key": "eredivisie", "home_team": home, "away_team": away,
            "home_team_id": None, "away_team_id": None}


def test_both_clubs_are_sources():
    s = main.get_sources_for_match(_row("Ajax", "PSV Eindhoven"))
    assert [x["club_team"] for x in s] == ["Ajax", "PSV Eindhoven"]
