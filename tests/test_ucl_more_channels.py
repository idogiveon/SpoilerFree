"""ערוצים שהמשתמש מצא (16.9.26): TV2 הנורווגי, סלביה פראג, לאנס, לאסק."""
import main

UCL = main.LEAGUES["ucl"]


def test_new_club_channels_are_configured():
    cc = UCL["club_channels"]
    assert cc["Slavia Prague"] == "UCPi3_GbTljPZ6b2Laiw-Z5g"
    assert cc["Lens"] == "UCE-f1Taamum6q2S-Ve4koSw"
    assert cc["LASK"] == "UC989Kq_d33oi_wwR5NsRZLw"


def test_tv2_is_a_league_source():
    tv2 = next(s for s in UCL["sources"] if s["id"] == "tv2_no")
    assert tv2["channel_id"] == "UC9QZZRUajPEoo1Q-V3MfvnQ"
    assert "allow_embed" not in tv2      # מדיניות מרכזית, לא לכל מקור


def test_norwegian_titles_pass_with_both_teams():
    """כותרות אמיתיות מ-TV2: תוצאה בכותרת, לפעמים גם "Høydepunkter"."""
    assert main.is_match_highlight("Viking 8 - 1 Kristiansund BK", "Viking", "Kristiansund BK")
    assert main.is_match_highlight("Strømsgodset 4 - 1 Sandnes Ulf - Høydepunkter",
                                   "Strømsgodset", "Sandnes Ulf")
    assert main.is_match_highlight("Bodø/Glimt 2 - 2 Slavia Praha - Høydepunkter",
                                   "Bodø/Glimt", "Slavia Prague")


def test_a_score_with_only_one_team_is_not_our_match():
    """המשחק שאנחנו מחפשים הוא ויקינג–סלביה; זה ויקינג נגד מישהו אחר."""
    assert not main.is_match_highlight("Viking 8 - 1 Kristiansund BK", "Viking", "Slavia Prague")


def test_slavia_club_channel_highlight():
    assert main.is_match_highlight("NIKDO SE NETRAPTE | Slavia - RC Lens 2:3 | Liga mistrů",
                                   "Slavia Prague", "Lens", None, None, False, "Slavia Prague")


def test_recaps_and_press_are_still_rejected():
    """לאנס ולאסק מעלים סיכומים וראיונות — לא תקצירים."""
    assert not main.is_match_highlight("SK Slavia Prague-RC Lens I Résilience 💫",
                                       "Slavia Prague", "Lens", None, None, False, "Lens")
    assert not main.is_match_highlight("Knappe Niederlage beim CL-Debüt",
                                       "LASK", "AEK Athens", None, None, False, "LASK")
    assert not main.is_match_highlight("Pressekonferenz nach LASK - SCR Altach",
                                       "LASK", "SCR Altach", None, None, False, "LASK")
