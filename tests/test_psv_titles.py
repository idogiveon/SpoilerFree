"""ערוץ פ.ס.וו: "HIGHLIGHTS" הוא תקציר — אבל לא של הנשים, העתודה, הנוער,
ולא קליפ של שער בודד. כותרות אמיתיות מהערוץ (16.9.26)."""
import main

# רק הכותרת הזו באמת צריכה את הכלל הרפוי: היא לא מזכירה את היריבה כלל
FIRST_TEAM = [
    "HIGHLIGHTS | A proper PSV night 😊",
]
# הכותרת הזו כן מזכירה את היריבה — ולכן מקומה בכלל הרגיל, מול המשחק הנכון
NAMES_THE_OPPONENT = "HIGHLIGHTS | Kicking Off the 26-27 Champions League vs Shakhtar Donetsk"
NOT_A_MATCH_HIGHLIGHT = [
    "HIGHLIGHTS | AZ Vrouwen - PSV Vrouwen",                      # נשים
    "HIGHLIGHTS | Drie goals in drie minuten voor Jong PSV 🐏",     # עתודה
    "HIGHLIGHTS | Liam van Nistelrooij scoort in eerste UEFA Youth League-wedstrijd",
    "HIGHLIGHTS | De vierde goal in vijf wedstrijden voor Austyn Jones 🥵",   # קומפילציה
    "HIGHLIGHTS | Heerlijke goal van Kyano Penso in Helmond 🤌",    # שער בודד
    "5️⃣ goals for you to vote for our August PUMA Goal of the Month 🔝",
    "INTERVIEWS | 'We weten wat we kunnen'",
]


def _keep(title, published="2026-09-13T22:00:00+00:00", date="2026-09-13"):
    """כמו במסלול האמיתי: ערוץ של מועדון, בחלון של יום מהמשחק."""
    if not main._within_days(published, date, 1):
        return False
    return main.is_match_highlight(title, "PSV Eindhoven", "Ajax", None, None,
                                   False, "PSV Eindhoven", loose_club=True)


def test_first_team_highlights_pass():
    assert all(_keep(t) for t in FIRST_TEAM)


def test_a_title_that_names_the_opponent_is_matched_against_that_opponent():
    """הבדיקה הזו הייתה בנויה לא נכון: היא העבירה את הכותרת הזו מול
    "Ajax" כיריבה מדומה, ועברה — כלומר אישרה בדיוק את ההתנהגות שגרמה
    לבאג. ארסנל העלו ב-19.9 תקציר של קבוצת הנשים ("Arsenal vs
    Manchester United | WSL") באותו יום שבו הגברים שיחקו מול ברייטון,
    והוא הוצע כתקציר של המשחק הגברי (מהמשתמש, 9.10.26).

    כותרת שמצהירה על מפגש אמורה לזהות את היריבה שלנו. אם לא — זה
    משחק אחר באותו ערוץ ובאותו יום."""
    assert main.is_match_highlight(NAMES_THE_OPPONENT, "PSV Eindhoven",
                                   "Shakhtar Donetsk", implicit_team="PSV Eindhoven")
    assert not main.is_match_highlight(NAMES_THE_OPPONENT, "PSV Eindhoven", "Ajax",
                                       implicit_team="PSV Eindhoven", loose_club=True)


def test_everything_else_on_the_channel_is_rejected():
    for title in NOT_A_MATCH_HIGHLIGHT:
        assert not _keep(title), title


def test_still_bounded_to_the_match_day():
    assert not _keep(FIRST_TEAM[0], published="2026-09-20T22:00:00+00:00")


def test_generic_words_are_not_enough_on_a_club_channel():
    """"goals"/"vs" לבד לא הופכים סרטון לתקציר כשאין את שם היריבה."""
    assert not _keep("Five goals to remember vs everyone 🔝")
