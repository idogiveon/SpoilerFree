"""רענון חלקי לא מוחק מה שלא נשלף (הבעלים, 31.10.26).

ליגה ספרדית, צרפתית ואיטלקית: בכולן המחזור הנוכחי הכיל 1-3 משחקים
במקום 9-10, ובכולן סך המשחקים בליגה היה 60-90 במקום 380.

הרענון מצד הלקוח מושך חלון של חמישה מחזורים בלבד (TheSportsDB חסום
מ-Render), ו-purge מחק כל משחק עתידי שלא הופיע במטען — כלומר את כל
העונה שמחוץ לחלון. וכשגם מחזור בתוך החלון נשלף חלקית, הוא איבד את מה
שכבר היה ידוע עליו.
"""
from fastapi.testclient import TestClient

import main


def _ev(mid, round_no, date, home="A", away="B"):
    return {"idEvent": mid, "intRound": str(round_no), "dateEvent": date,
            "strHomeTeam": home, "strAwayTeam": away, "strTime": "20:00:00",
            "strStatus": "", "idHomeTeam": "h" + mid, "idAwayTeam": "a" + mid}


def _rows(db, league="laliga"):
    return {r["id"]: r["matchday"] for r in db.execute(
        "SELECT id, matchday FROM matches WHERE league_key=?", (league,))}


def test_a_matchday_outside_the_window_survives(db):
    """מחזור 20 לא נשלף כלל — ואין שום סיבה למחוק אותו."""
    main._store_sportsdb_events(db, "laliga", [
        _ev("far", 20, "2027-02-14"), _ev("near", 11, "2026-10-31")], purge=True)
    db.commit()
    main._store_sportsdb_events(db, "laliga", [_ev("near", 11, "2026-10-31")],
                                purge=True)
    db.commit()
    assert _rows(db) == {"far": 20, "near": 11}


def test_a_match_that_vanished_from_a_fetched_matchday_is_removed(db):
    """בתוך מחזור שכן נשלף, purge עדיין עושה את עבודתו — משחק שבוטל
    או שעבר מחזור נמחק."""
    main._store_sportsdb_events(db, "laliga", [
        _ev("keep", 11, "2026-10-31"), _ev("gone", 11, "2026-11-01")], purge=True)
    db.commit()
    main._store_sportsdb_events(db, "laliga", [_ev("keep", 11, "2026-10-31")],
                                purge=True)
    db.commit()
    assert _rows(db) == {"keep": 11}


def test_history_still_survives(db):
    """ההגנה הקיימת על משחק שהסתיים לא נפגעה."""
    main._store_sportsdb_events(db, "laliga", [_ev("old", 11, "2026-10-01")],
                                purge=True)
    db.execute("UPDATE matches SET status='FINISHED' WHERE id='old'")
    db.commit()
    main._store_sportsdb_events(db, "laliga", [_ev("new", 11, "2026-10-31")],
                                purge=True)
    db.commit()
    assert set(_rows(db)) == {"old", "new"}


def test_a_hard_reset_still_clears_everything(db):
    """איפוס עונה הוא פעולת מנהל, והוא עדיין מוחק הכול."""
    main._store_sportsdb_events(db, "laliga", [
        _ev("far", 20, "2027-02-14"), _ev("near", 11, "2026-10-31")], purge=True)
    db.commit()
    main._store_sportsdb_events(db, "laliga", [_ev("near", 11, "2026-10-31")],
                                purge=True, hard=True)
    db.commit()
    assert set(_rows(db)) == {"near"}


def test_the_client_does_not_purge_after_a_failed_fetch():
    """מטען חלקי אינו תמונת מצב, ו-purge היה קורא בו "אלה כל מה שנותר"."""
    html = open("index.html", encoding="utf-8").read()
    assert "purge: counts.failed === 0" in html
    # והכשל נספר במקום להיבלע
    grab = html[html.index("async function grab(ep, label"):]
    grab = grab[:grab.index("\n    }")]
    assert "counts.failed++" in grab


def test_an_empty_round_counts_as_a_block():
    """מחזור ריק באמצע עונה אינו מחזור ריק. ההבדל חשוב: תשובה ריקה
    חוזרת כ-HTTP 200 ועוברת בשקט, בלי שום חריגה לתפוס."""
    html = open("index.html", encoding="utf-8").read()
    assert "emptyIsFailure && !ev.length" in html
    assert "'rounds', true]" in html          # המחזורים נשלחים עם הדגל
    assert "const BACKOFF = [1000, 3000];" in html


def test_the_current_round_is_fetched_first():
    """אם התקציב ייגמר באמצע, שייגמר על מחזור רחוק."""
    html = open("index.html", encoding="utf-8").read()
    assert "[maxRound, maxRound + 1, maxRound - 1, maxRound + 2, maxRound + 3]" in html


def test_the_window_anchor_uses_both_endpoints():
    """המפתח החינמי מחזיר אירוע אחד בכל אחד מהם (היו 15), ועוגן על
    אירוע בודד מחטיא ברגע שהוא דחוי או שייך למחזור קודם."""
    html = open("index.html", encoding="utf-8").read()
    assert "for (const e of [...past, ...next])" in html


# ── מחזור "נראה" בזכות אירוע בודד (הבעלים, 31.10.26) ───────────────
def test_a_single_event_does_not_authorise_purging_its_matchday(db):
    """הבונדסליגה איבדה את מחזור 8: eventspastleague ו-eventsnextleague
    תרמו שני אירועים ממנו, המחזור נחשב "נראה", וכל השאר נמחק — נשארו בו
    רק מי שכבר התחיל לשחק. רק מחזור שנשלף במלואו מתיר מחיקה."""
    main._store_sportsdb_events(db, "bundesliga", [
        _ev("a", 8, "2026-10-30"), _ev("b", 8, "2026-10-31"),
        _ev("c", 8, "2026-11-01"), _ev("d", 8, "2026-11-01")], purge=True)
    db.commit()
    # רענון שבו eventsround של מחזור 8 נחסם, ורק next תרם אירוע ממנו
    main._store_sportsdb_events(db, "bundesliga", [_ev("c", 8, "2026-11-01")],
                                purge=True, purge_rounds={11})
    db.commit()
    assert set(_rows(db, "bundesliga")) == {"a", "b", "c", "d"}


def test_a_fully_fetched_round_still_purges(db):
    main._store_sportsdb_events(db, "bundesliga", [
        _ev("keep", 8, "2026-11-01"), _ev("gone", 8, "2026-11-01")], purge=True)
    db.commit()
    main._store_sportsdb_events(db, "bundesliga", [_ev("keep", 8, "2026-11-01")],
                                purge=True, purge_rounds={8})
    db.commit()
    assert set(_rows(db, "bundesliga")) == {"keep"}


def test_an_old_client_keeps_the_previous_behaviour(db):
    """לקוח ישן לא שולח rounds, ואז נשמרת ההתנהגות הקודמת."""
    main._store_sportsdb_events(db, "bundesliga", [
        _ev("keep", 8, "2026-11-01"), _ev("gone", 8, "2026-11-01")], purge=True)
    db.commit()
    main._store_sportsdb_events(db, "bundesliga", [_ev("keep", 8, "2026-11-01")],
                                purge=True, purge_rounds=None)
    db.commit()
    assert set(_rows(db, "bundesliga")) == {"keep"}


def test_the_client_sends_the_rounds_it_fetched():
    html = open("index.html", encoding="utf-8").read()
    assert "const okRounds = new Set();" in html
    assert "rounds: [...okRounds]" in html
    assert "if (got[i] && got[i].length) okRounds.add(r);" in html
