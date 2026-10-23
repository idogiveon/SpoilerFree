"""A3: תקציר מורחב של המנהלת מגיע עד 11 יום אחרי המשחק.

HIGHLIGHT_MAX_DAYS=6 פסל אותו בשקט. הבעלים מצא שני משחקים שהגרסה
המורחבת שלהם עלתה בערך 10 ימים אחרי (סכנין–ר"ג, פ"ת–י-ם), ולא הוצגה.

החלון קיים כדי שמפגש חוזר של אותן שתי קבוצות לא ייתפס — וזו בדיוק
האי-ודאות שמספר המחזור בכותרת מסיר. "מחזור 7" מצביע על מפגש אחד ויחיד
בעונה, ולכן כותרת שנושאת אותו פטורה מהחלון.
"""
import main

TITLE = 'מחזור 7 | תקציר מורחב: מכבי נתניה - הפועל ק"ש 0-1'
KICKOFF = "2026-10-17"


def _keep(title, published, matchday, **kw):
    """away_alt הוא מה ש-to_hebrew_team מחזיר בפועל. _il_title_norm מקפל
    'הפועל ק"ש' שבכותרת ל'עירוני ק"ש', ושם הקבוצה חייב לעבור את אותו קיפול."""
    return main.title_matches(
        title, published, home="Maccabi Netanya", away="Hapoel Ironi Kiryat Shmona",
        match_date=KICKOFF, home_alt="מכבי נתניה",
        away_alt="עירוני קריית שמונה",
        il_both=True, matchday=matchday, **kw)


def test_the_late_extended_version_is_accepted():
    """11 יום אחרי — בדיוק המקרה שהבעלים דיווח עליו."""
    assert _keep(TITLE, "2026-10-28", 7) is True


def test_without_the_matchday_the_window_still_applies():
    """כותרת בלי "מחזור" לא מקבלת שום פטור."""
    plain = 'תקציר מורחב: מכבי נתניה - הפועל ק"ש 0-1'
    assert _keep(plain, "2026-10-28", 7) is False
    assert _keep(plain, "2026-10-19", 7) is True       # בתוך החלון


def test_a_different_round_is_rejected():
    """ההגנה מפני ספוילר: המפגש החוזר נושא מספר מחזור אחר."""
    assert _keep(TITLE, "2026-10-28", 8) is False
    assert _keep('מחזור 24 | תקציר: מכבי נתניה - הפועל ק"ש 3-0',
                 "2027-02-20", 7) is False


def test_a_match_without_a_matchday_gets_no_exemption():
    assert _keep(TITLE, "2026-10-28", None) is False


def test_next_season_is_out_of_reach():
    """"מחזור 7" חוזר בעונה הבאה — התקרה החיצונית חוסמת אותו."""
    assert main.IL_MATCHDAY_MAX_DAYS == 30
    assert _keep(TITLE, "2027-09-20", 7) is False


def test_the_short_version_benefits_too():
    short = 'מחזור 7 | תקציר: מכבי נתניה - הפועל ק"ש 0-1'
    assert _keep(short, "2026-10-26", 7) is True


def test_the_number_is_read_as_a_whole_word():
    assert main._title_matchday("מחזור 7 | תקציר") == 7
    assert main._title_matchday("מחזור 12 | תקציר") == 12
    assert main._title_matchday("תקציר: מכבי נתניה") is None


def test_the_exemption_does_not_leak_to_other_leagues():
    """ההקלה נשענת על il_both, שדלוק רק בערוצים הישראליים."""
    en = "Matchday 7 | Arsenal 2-0 Brighton | Highlights"
    assert main.title_matches(en, "2026-10-28", home="Arsenal", away="Brighton",
                              match_date=KICKOFF, matchday=7) is False
