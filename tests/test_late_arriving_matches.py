"""משחק שנכנס ל-DB אחרי שהחלון נסגר.

ליגות sportsdb מגיעות מהדפדפן (TheSportsDB חסום מ-Render), ולכן מחזור
שלם יכול להיכנס שבוע אחרי ששוחק. הרקע מדד את החלון משריקת הפתיחה, אז
משחק כזה נולד כבר "מחוץ לחלון" ולא נבדק מעולם.

נמדד ב-/debug/timing (2.10.26): לצ'מפיונס ליג 18 משחקים שנגמרו ו**אפס**
שורות קאש — אפילו לא ריקות. ליל–ריאל בטיס שוחק ב-8.9 ונכנס ל-DB ב-19.9.
"""
from datetime import datetime, timedelta, timezone

import main


def _match(db, mid, days_ago, league="ucl"):
    kick = datetime.now(timezone.utc) - timedelta(days=days_ago)
    db.execute("INSERT INTO matches (id, league_key, home_team, away_team, date_utc, "
               "time_utc, status) VALUES (?, ?, 'Real Madrid', 'Inter Milan', ?, ?, "
               "'FINISHED')",
               (mid, league, kick.strftime("%Y-%m-%d"), kick.strftime("%H:%M:%S")))
    db.commit()


def _round(monkeypatch):
    seen = []
    monkeypatch.setattr(main, "search_youtube",
                        lambda **kw: seen.append(kw["channel_id"]) or [])
    monkeypatch.setattr(main, "_web_link", lambda row, w: None)
    main.prefetch_highlights_once()
    return seen


def test_a_match_that_arrived_late_is_still_checked(db, monkeypatch):
    """ארבעה ימים — מחוץ לחלון של הליגה (72 שעות), בתוך הגבול שבו
    תקציר עוד יכול להופיע."""
    _match(db, "late", days_ago=4)
    assert main._highlight_window("ucl") < timedelta(days=4)
    assert _round(monkeypatch), "הרקע דילג על משחק שאף פעם לא נבדק"


def test_and_it_leaves_a_row_behind_even_when_nothing_is_found(db, monkeypatch):
    """"נבדק ואין" הוא מידע. אפס שורות זה מה שהשאיר את הצ'מפיונס ריק."""
    _match(db, "late2", days_ago=4)
    _round(monkeypatch)
    n = db.execute("SELECT COUNT(*) AS n FROM highlight_cache "
                   "WHERE match_id='late2'").fetchone()["n"]
    assert n > 0


def test_but_not_forever(db, monkeypatch):
    """מעבר ל-HIGHLIGHT_MAX_DAYS אין מה לחפש, והתור לא נסתם בהיסטוריה."""
    _match(db, "ancient", days_ago=main.HIGHLIGHT_MAX_DAYS + 2)
    assert _round(monkeypatch) == []


def test_the_fresh_match_still_comes_first(db, monkeypatch):
    """הרוטציה ממיינת לפי מי נבדק לפני הכי הרבה זמן — משחק טרי שלא
    נבדק מעולם לא נדחק מפני ערימה של ישנים."""
    for i in range(3):
        _match(db, f"old{i}", days_ago=5)
    _match(db, "fresh", days_ago=0)
    monkeypatch.setattr(main, "PREFETCH_MAX_MATCHES", 4)
    assert _round(monkeypatch)
    rows = {r["match_id"] for r in db.execute(
        "SELECT DISTINCT match_id FROM highlight_cache").fetchall()}
    assert "fresh" in rows
