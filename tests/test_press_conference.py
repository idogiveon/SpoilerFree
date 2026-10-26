"""מסיבת עיתונאים שמצטטת את התוצאה בכותרת (הבעלים, 26.10.26).

ליברפול–ברייטון, 25.10: הערוץ של ליברפול החזיר את
"Isak's Form, Ronald Araujo, Anfield Win | Liverpool 2-0 Brighton |
Andoni Iraola" — 4:21 דקות של מסיבת עיתונאים. אין בכותרת מילת תקציר,
ואין בה אף אחת ממילות ההדרה הקיימות ("press conference", "interview",
"reaction"): שתי הקבוצות והתוצאה לבדן הספיקו.

הדפוס הוא מה שמזהה אותה — סגמנט אחרון שהוא שם של אדם. ניסיון ראשון
ספר מילים "עודפות" בכותרת, ופסל גם את הכותרות של ליון ושל PSG, שהן
עורכתיות ואמיתיות. הבדיקות כאן שומרות על שני הצדדים.
"""
import main

PRESSER = ("Isak's Form, Ronald Araujo, Anfield Win | "
           "Liverpool 2-0 Brighton | Andoni Iraola")
REAL = "HIGHLIGHTS | Liverpool v Brighton | Premier League"


def _ok(title, home="Liverpool FC", away="Brighton & Hove Albion FC",
        club="Liverpool FC"):
    return main.is_match_highlight(title, home, away, implicit_team=club)


def test_the_press_conference_is_rejected():
    assert _ok(PRESSER) is False


def test_the_real_highlight_still_passes():
    assert _ok(REAL, club="Brighton & Hove Albion FC") is True


def test_the_editorial_titles_the_owner_supplied_still_pass():
    """9.10.26: הבעלים שלח את שתי הכותרות האלה כדי להוכיח שהתקצירים
    קיימים. פתרון שפוסל אותן הוא רגרסיה, לא תיקון."""
    assert main.is_match_highlight(
        "RETOUR EN FORCE EN LIGUE DES CHAMPIONS I PSG 6-1 BRATISLAVA",
        "Paris Saint-Germain", "Slovan Bratislava",
        implicit_team="Paris Saint-Germain") is True
    assert main.is_match_highlight(
        "Anderlecht - OL : 3 points pour démarrer la campagne européenne ! (1-2)",
        "Anderlecht", "Lyon", implicit_team="Lyon") is True


def test_a_scoreline_title_without_pipes_is_untouched():
    assert main.is_match_highlight("Fredrikstad 1 - 1 Sarpsborg 08",
                                   "Fredrikstad", "Sarpsborg 08") is True


def test_a_competition_name_is_not_a_person():
    for tail in ("Premier League", "Champions League", "FA Cup", "Matchweek 8"):
        assert main._ends_with_a_persons_name(f"Liverpool 2-0 Brighton | {tail}") \
            is False, tail


def test_a_managers_name_is():
    for tail in ("Andoni Iraola", "Arne Slot", "Pep Guardiola"):
        assert main._ends_with_a_persons_name(f"Liverpool 2-0 Brighton | {tail}") \
            is True, tail


def test_a_highlight_word_outranks_the_pattern():
    """"תקציר" בכותרת מכריע עוד לפני מסלול התוצאה, ולכן סרטון אמיתי
    שנושא גם שם של שחקן לא נפגע."""
    assert _ok("HIGHLIGHTS | Liverpool 2-0 Brighton | Mohamed Salah") is True


def test_the_stale_row_is_cleared_by_the_revalidation(db):
    """#129 מריץ את אותם כללים על מה ששמור — ולכן השורה הזו תיפול
    מעצמה בהרצה הבאה, בלי קריאת רשת."""
    import json
    club = db.execute("SELECT * FROM clubs WHERE league_key='premier' "
                      "AND yt_channel_id != '' ORDER BY id LIMIT 1").fetchone()
    db.execute("INSERT INTO matches (id, league_key, home_team, away_team, "
               "home_team_id, away_team_id, date_utc, time_utc, status) "
               "VALUES ('lb','premier',?,'Brighton & Hove Albion FC',?,'x',"
               "'2026-10-25','16:30','FINISHED')", (club["name"], club["fd_team_id"]))
    src = main.get_sources_for_match(
        db.execute("SELECT * FROM matches WHERE id='lb'").fetchone())[0]
    title = PRESSER.replace("Liverpool", club["name"])
    db.execute("INSERT INTO highlight_cache VALUES ('lb',?,?,?)",
               (src["id"], json.dumps([{"video_id": "J1YJOP94V0Y", "title": title,
                                        "published": "2026-10-25T18:07:24+00:00"}]),
                main._now().isoformat()))
    db.commit()
    rep = main.revalidate_cache(apply=True)
    assert rep["dropped"] and rep["dropped"][0]["row_deleted"] is True
    assert db.execute("SELECT COUNT(*) FROM highlight_cache").fetchone()[0] == 0
