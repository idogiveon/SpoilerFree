"""הליגה האירופית: ערוצים שסימנתי "אין בהם תקצירים" — ויש.

26.9.26, מהמשתמש: התקציר של יובנטוס–NEC נמצא בערוץ של יובנטוס
(https://www.youtube.com/watch?v=TvUJIjojbOI), ושל אנדרלכט–ליון בערוץ של
ליון (https://www.youtube.com/watch?v=E5pCpJX5awI). שניהם היו ברשימת
"נבדקו ואין בהם תקצירים" — הסינון שלי חיפש "highlights" באנגלית, וליון
מעלים בצרפתית עם התוצאה בכותרת.
"""
import main

JUVE = "5 GOALS! Juventus 5-0 NEC | Europa League Highlights"
LYON = "Anderlecht - OL : 3 points pour démarrer la campagne européenne ! (1-2)"


def _channel(team):
    return main.LEAGUES["uel"]["club_channels"].get(team)


def test_both_clubs_now_have_a_channel():
    assert _channel("Juventus") == "UCLzKhsxrExAC6yAdtZ-BOWw"
    assert _channel("Lyon") == "UCzHCZXmqIdjqRnpdp0l_T6g"


def test_the_juventus_title_is_matched_outside_the_match_day():
    """loose_club חל רק ביום המשחק. משתמש שפותח את המשחק אחרי שלושה ימים
    צריך את אותו תקציר — ולכן שתי הקבוצות חייבות להיות מזוהות בכותרת."""
    assert main.is_match_highlight(JUVE, "Juventus", "NEC Nijmegen",
                                   implicit_team="Juventus")
    assert main.is_match_highlight(JUVE, "Juventus", "NEC Nijmegen")


def test_the_french_title_with_the_score_is_a_highlight():
    assert main.is_match_highlight(LYON, "Anderlecht", "Lyon",
                                   implicit_team="Lyon")


def test_a_short_alias_must_be_a_whole_word():
    """"nec" יושב בתוך "connection" — קיצור שנבדק כתת-מחרוזת מזהה קבוצה
    בכותרת שאין בה שום קבוצה."""
    assert not main.is_match_highlight(
        "Juventus: the connection between the fans and the team vs everyone",
        "Juventus", "NEC Nijmegen")


def test_the_club_source_is_actually_offered_for_that_match(db):
    db.execute("INSERT INTO matches (id, league_key, home_team, away_team, "
               "date_utc, time_utc, status) VALUES ('j1', 'uel', 'Juventus', "
               "'NEC Nijmegen', '2026-09-17', '19:00:00', 'FINISHED')")
    db.commit()
    row = db.execute("SELECT * FROM matches WHERE id='j1'").fetchone()
    chans = [s["channel_id"] for s in main.get_sources_for_match(row)]
    assert "UCLzKhsxrExAC6yAdtZ-BOWw" in chans


# ── הסריקה החוזרת (26.9.26): 15 הקבוצות שנשארו בלי מקור ──────────────
ARARAT = "UEFA Еuropa League | FC Ararat-Armenia - Sparta Praha [1:4]"
DINAMO = "HIGHLIGHTS | Dinamo 3-2 Lokomotiva"


def test_ararat_uploads_the_european_highlight_itself():
    """הכותרת באנגלית עם ה-Е הקירילית, ועם התוצאה בסוגריים מרובעים."""
    assert _channel("Ararat-Armenia") == "UCFzwA2WTexgusRXuBLTGPgw"
    assert main.is_match_highlight(ARARAT, "Ararat-Armenia", "Sparta Prague",
                                   implicit_team="Ararat-Armenia")


def test_dinamo_uploads_highlights_in_the_usual_format():
    assert _channel("Dinamo Zagreb") == "UC6vpARgHA0oSqtBgYcVWdHg"
    assert main.is_match_highlight(DINAMO, "Dinamo Zagreb", "Lokomotiva",
                                   implicit_team="Dinamo Zagreb")


def test_what_those_two_channels_also_upload_is_not_offered():
    """שני הערוצים עמוסים בראיונות, מסיבות עיתונאים ו"רגעים היסטוריים" —
    כולם מזכירים את שתי הקבוצות ולפעמים גם את התוצאה."""
    for title, home, away, club in [
        ("NAKON UTAKMICE | Kovačević i Kotarski nakon remija s Hapoel Be'er Shevom",
         "Dinamo Zagreb", "Hapoel Be'er Sheva", "Dinamo Zagreb"),
        ("UNSEEN HISTORIC MOMENTS | Ararat-Armenia 1–0 Craiova",
         "Ararat-Armenia", "Craiova", "Ararat-Armenia"),
        ("Manuel Tulipa post-match press conference / UEL FC Ararat-Armenia - "
         "Sparta Praha - 1:4", "Ararat-Armenia", "Sparta Prague", "Ararat-Armenia"),
    ]:
        assert not main.is_match_highlight(title, home, away, implicit_team=club), title
