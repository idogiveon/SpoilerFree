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


# ── אותה משפחה: קבוצת הנוער (מהמשתמש, 9.10.26) ─────────────────────
U18 = "Chelsea U18 5-0 Bournemouth U18 | HIGHLIGHTS | U18 Premier League | 2026/27"


def test_the_youth_match_is_not_offered_either():
    """צ'לסי–ברנטפורד: "תקציר מלא" הוביל לתקציר של קבוצת ה-U18."""
    assert not main.is_match_highlight(U18, "Chelsea FC", "Brentford FC",
                                       implicit_team="Chelsea", loose_club=True)


def test_the_youth_team_playing_the_same_fixture_is_the_real_hole():
    """זה מה שכלל "הכותרת חייבת לזהות את היריבה שלנו" לא תופס: קבוצת
    הנוער משחקת לרוב את אותו מפגש, ואז הכותרת מזהה את שתי הקבוצות
    הנכונות ועוברת הכול. u19/u20/u23 היו ברשימה — u18 לא."""
    t = "Chelsea U18 2-0 Brentford U18 | HIGHLIGHTS | U18 Premier League"
    assert not main.is_match_highlight(t, "Chelsea FC", "Brentford FC",
                                       implicit_team="Chelsea")


def test_every_youth_age_group_is_covered():
    for tag in ("U14", "U15", "U16", "U17", "U18", "U19", "U21", "U23", "U-18"):
        t = f"Chelsea {tag} 2-0 Brentford {tag} | HIGHLIGHTS"
        assert not main.is_match_highlight(t, "Chelsea FC", "Brentford FC",
                                           implicit_team="Chelsea"), tag


def test_the_senior_match_still_passes():
    """הבדיקה שמונעת סינון יתר."""
    assert main.is_match_highlight("Chelsea 2-0 Brentford | HIGHLIGHTS | Premier League",
                                   "Chelsea FC", "Brentford FC", implicit_team="Chelsea")


def test_the_labels_say_what_people_understand():
    """"תקציר" הוא הקצר — ככה רוב האנשים מבינים את המילה — ו"ארוך"
    הוא המורחב (הבעלים, 9.10.26). המחרוזות שהשרת שומר הן מזהים
    פנימיים ששמורים בקאש, ולכן לא השתנו."""
    html = open("index.html", encoding="utf-8").read()
    assert '"kind_short": "תקציר",' in html
    assert '"kind_full": "תקציר ארוך",' in html
    assert "תקציר קצר" not in html.split("const HE_LABEL_KIND")[1].split("};")[1]
    # והמיפוי מהשרת נשאר, אחרת משחקים ישנים בקאש יאבדו את התווית
    assert "'תקציר קצר': 'kind_short'" in html
    src = open("main.py", encoding="utf-8").read()
    assert '"label": "תקציר קצר"' in src or '"תקציר קצר"' in src
