"""כמה זמן ממשיכים לחפש תקציר — לפי ליגה.

עד 2.10.26 היו כאן שני מספרים שנקבעו בעין: 48 שעות, ו-120 לישראל.
מאז הם נמדדו (/debug/timing, 30 יום, לפי published של הסרטון) —
והתברר ששלוש ליגות חורגות מ-48, כי הגרסה המלאה עולה יום-יומיים אחרי
הקצרה. הטבלה למטה היא המדידה עצמה: חלון שיירד מתחתיה ייפול כאן.
"""
from datetime import datetime, timedelta, timezone

import main


def _row(db, mid, league, hours_ago):
    kick = datetime.now(timezone.utc) - timedelta(hours=hours_ago)
    db.execute("INSERT INTO matches (id, league_key, home_team, away_team, date_utc, "
               "time_utc, status) VALUES (?, ?, 'Maccabi Haifa', 'Hapoel Petah Tikva', "
               "?, ?, 'FINISHED')",
               (mid, league, kick.strftime("%Y-%m-%d"), kick.strftime("%H:%M:%S")))
    db.commit()
    return db.execute("SELECT * FROM matches WHERE id=?", (mid,)).fetchone()


# המקסימום שנמדד בפועל, בשעות מהפתיחה (n = דגימות, d = ימי משחקים).
# התקופה כוללת הפסקת נבחרות, ולכן מה שנראה כחודש הוא 2–11 ימי משחקים.
MEASURED_MAX = {
    "israel": 64.8, "bundesliga": 51.5, "uel": 45.0, "premier": 44.5,
    "seriea": 43.0, "laliga": 39.3, "eredivisie": 38.7, "ligue1": 30.8,
    "championship": 13.4, "argentina": 4.6, "mls": 3.4,
}


def test_israel_gets_longer_than_europe():
    assert main._highlight_window("israel") > main._highlight_window("premier")
    assert main._highlight_window("premier") == timedelta(hours=72)


def test_an_unknown_league_gets_the_default_window():
    assert main._highlight_window("whatever") == timedelta(hours=72)


def test_every_window_covers_what_was_actually_measured():
    """זו הבדיקה שמחזיקה את T2: חלון שמקצר מתחת למה שנמדד מוותר על
    תקציר שראינו בעיניים שכן מגיע."""
    for league, observed in MEASURED_MAX.items():
        assert main._highlight_window(league) >= timedelta(hours=observed), league


def test_the_fast_leagues_are_not_searched_for_three_days():
    """MLS וארגנטינה: 85 דגימות על פני 21 ימי משחקים, והכול בתוך 5
    שעות. חלון ארוך שם הוא בדיקות רקע על ריק."""
    for league in ("mls", "argentina"):
        w = main._highlight_window(league)
        assert w <= timedelta(hours=24), league
        assert w >= timedelta(hours=2 * MEASURED_MAX[league]), league


def test_a_three_day_old_israeli_match_is_still_checked_often(db):
    """יום שלישי אחרי משחק שבת: באירופה כבר ויתרנו, בישראל עוד מחפשים."""
    il = _row(db, "w1", "israel", hours_ago=72)
    pl = _row(db, "w2", "premier", hours_ago=72)
    assert main._not_found_retry(il) == timedelta(minutes=30)
    assert main._not_found_retry(pl) == timedelta(hours=6)


def test_the_background_keeps_looking_inside_the_window(db, monkeypatch):
    il = _row(db, "w3", "israel", hours_ago=72)
    _row(db, "w4", "premier", hours_ago=72)
    calls = []
    monkeypatch.setattr(main, "search_youtube",
                        lambda home, *a, **k: calls.append(k.get("channel_id")) or [])
    monkeypatch.setattr(main, "_web_link", lambda row, w: None)
    main.prefetch_highlights_once()
    checked = {r["match_id"] for r in
               db.execute("SELECT DISTINCT match_id FROM highlight_cache").fetchall()}
    assert "w3" in checked        # ישראלי בן 3 ימים — עדיין בחלון
    assert "w4" not in checked    # אנגלי בן 3 ימים — מחוץ לחלון


def test_the_window_still_ends(db):
    """גם בישראל לא מחפשים לנצח — אחרי שבוע זה כבר פעם בשבוע."""
    old = _row(db, "w5", "israel", hours_ago=24 * 9)
    assert main._not_found_retry(old) == timedelta(days=7)
