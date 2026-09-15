"""פרמייר ליג: שמות football-data עם "FC" — הכינויים ("man utd") חייבים לחול."""
import main

CITY, UNITED = "Manchester City FC", "Manchester United FC"


def ok(title, home=UNITED, away=CITY):
    return main.is_match_highlight(title, home, away)


def test_manchester_derby_on_uniteds_channel():
    """ערוץ יונייטד, 13–14.9.26 — נפסלו כי "man utd" לא חל על "Manchester United FC"."""
    assert ok("Man Utd 0-1 Man City | Highlights")
    assert ok("Man Utd 0-1 Man City | Extended Highlights")


def test_derby_on_citys_channel_still_passes():
    assert ok("Man United 0-1 Man City | Highlights as 10-man Blues win Manchester derby through Haaland")


def test_non_highlights_still_rejected():
    assert not ok("Michael Carrick Post-Man City Press Conference")
    assert not ok("Man Utd v Brighton | Matchday LIVE", UNITED, "Brighton & Hove Albion FC")


def test_alias_applies_with_fc_suffix():
    base = next(k for k, v in main.TEAM_ALIASES.items() if v and not k.endswith(" FC"))
    alias = main.TEAM_ALIASES[base][0]
    assert main.is_match_highlight(f"{alias} 2-1 Some Opponent | Highlights",
                                   base + " FC", "Some Opponent FC")
