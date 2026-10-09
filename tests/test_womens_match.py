"""תקציר של קבוצת הנשים הוצע כתקציר של המשחק הגברי.

מהמשתמש (9.10.26): ארסנל–ברייטון מ-19.9 החזיר את
"SMILLA HOLMBERG WITH A LATE LEVELLER | HIGHLIGHTS | Arsenal vs
Manchester United (1-1) | WSL" — משחק של קבוצת הנשים, שעלה באותו יום
לאותו ערוץ.

שני כשלים נפגשו: המילה "women" לא מופיעה בכותרת (רק WSL), והכלל
loose_club — שנועד לכותרות שלא מזכירות את היריבה כלל — קיבל כותרת
שדווקא כן מצהירה על מפגש, רק על מפגש אחר.
"""
import main

WSL = ("SMILLA HOLMBERG WITH A LATE LEVELLER | HIGHLIGHTS | "
       "Arsenal vs Manchester United (1-1) | WSL")
PSV = "HIGHLIGHTS | A proper PSV night"


def test_the_womens_match_is_not_offered_for_the_mens_one():
    assert not main.is_match_highlight(WSL, "Arsenal FC", "Brighton & Hove Albion FC",
                                       implicit_team="Arsenal", loose_club=True)


def test_a_title_that_names_a_fixture_must_name_ours():
    """זה הכלל הכללי: אם הכותרת מצהירה על מפגש, היריבה אמורה להיות
    מזוהה. אם היא לא — זה משחק אחר, בלי קשר לנשים או לנוער."""
    for title in ("HIGHLIGHTS | Arsenal vs Tottenham (2-0)",
                  "HIGHLIGHTS | Arsenal 3-1 Everton"):
        assert not main.is_match_highlight(title, "Arsenal FC",
                                           "Brighton & Hove Albion FC",
                                           implicit_team="Arsenal", loose_club=True), title


def test_but_the_case_loose_club_exists_for_still_works():
    """פ.ס.וו לא כותבים את שם היריבה — זה בדיוק מה שהכלל נועד לתפוס."""
    assert main.is_match_highlight(PSV, "PSV Eindhoven", "Shakhtar Donetsk",
                                   implicit_team="PSV Eindhoven", loose_club=True)


def test_womens_competitions_are_excluded_even_without_the_word():
    """WSL, NWSL, UWCL, Frauen — אף אחת לא מכילה את המילה women."""
    for tag in ("WSL", "NWSL", "UWCL", "Frauen-Bundesliga", "Liga F Femenina"):
        t = f"HIGHLIGHTS | Arsenal vs Brighton (2-1) | {tag}"
        assert not main.is_match_highlight(t, "Arsenal FC", "Brighton & Hove Albion FC",
                                           implicit_team="Arsenal"), tag


def test_a_newsletter_is_not_mistaken_for_a_womens_match():
    """"wsl" כתת-מחרוזת יושב בתוך "newsletter"."""
    t = "Arsenal vs Brighton | Highlights | Subscribe to our newsletter"
    assert main.is_match_highlight(t, "Arsenal FC", "Brighton & Hove Albion FC",
                                   implicit_team="Arsenal")
