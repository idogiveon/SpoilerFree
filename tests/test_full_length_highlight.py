"""הבונדסליגה מעלה תקציר של דקה בערב המשחק, ואת המלא יום-יומיים אחרי.

מהמשתמש (26.9.26): באיירן–אוניון ברלין ממחזור 4 הציע רק את הקצר. בערוץ
יש "The Kane and Olise Late Night Show 🔥 | FC BAYERN - UNION BERLIN |
Highlights" באורך 4:04, שעלה יומיים אחרי המשחק.

הסיבה: הרקע לא חזר לעולם למשחק שכבר נמצא בו תקציר (`needs_check`
החזיר False ברגע שנמצא), והבדיקה החוזרת שכן מחפשת גרסה מלאה חלה רק על
מי שבמקרה פתח את המשחק בשלושת הימים שאחרי המציאה.
"""
import json
from datetime import datetime, timedelta, timezone

import main

SHORT = [{"video_id": "SHORT1", "label": "תקציר", "extended": False}]
BOTH = [{"video_id": "SHORT1", "label": "תקציר קצר", "extended": False},
        {"video_id": "LONG1", "label": "תקציר מלא", "extended": True}]


def _match(db, mid="bl1", days_ago=2):
    kick = datetime.now(timezone.utc) - timedelta(days=days_ago)
    db.execute("INSERT INTO matches (id, league_key, home_team, away_team, date_utc, "
               "time_utc, status) VALUES (?, 'bundesliga', 'Bayern Munich', "
               "'Union Berlin', ?, ?, 'FINISHED')",
               (mid, kick.strftime("%Y-%m-%d"), kick.strftime("%H:%M:%S")))
    db.commit()


def _cache(db, mid, videos, hours_ago):
    when = (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat()
    db.execute("INSERT OR REPLACE INTO highlight_cache VALUES (?,?,?,?)",
               (mid, "bundesliga_official", json.dumps(videos), when))
    db.commit()


def _cached(db, mid="bl1"):
    row = db.execute("SELECT videos_json FROM highlight_cache WHERE match_id=?",
                     (mid,)).fetchone()
    return json.loads(row["videos_json"]) if row else None


def _round(monkeypatch, found):
    calls = []
    monkeypatch.setattr(main, "search_youtube",
                        lambda **kw: calls.append(kw) or found)
    monkeypatch.setattr(main, "_web_link", lambda row, w: None)
    main.prefetch_highlights_once()
    return calls


def test_the_background_goes_back_for_the_full_version(db, monkeypatch):
    _match(db)
    _cache(db, "bl1", SHORT, hours_ago=20)
    assert _round(monkeypatch, BOTH), "הרקע לא חזר למשחק שיש בו רק תקציר קצר"
    assert [v["video_id"] for v in _cached(db)] == ["SHORT1", "LONG1"]


def test_it_does_not_go_back_once_the_full_version_is_there(db, monkeypatch):
    _match(db)
    _cache(db, "bl1", BOTH, hours_ago=20)
    assert _round(monkeypatch, BOTH) == []


def test_it_does_not_check_twice_in_twelve_hours(db, monkeypatch):
    """הבדיקה היא חינם (RSS), אבל לא סיבה לבדוק בכל סבב."""
    _match(db)
    _cache(db, "bl1", SHORT, hours_ago=2)
    assert _round(monkeypatch, BOTH) == []


def test_it_gives_up_when_the_highlight_can_no_longer_appear(db, monkeypatch):
    _match(db, days_ago=main.HIGHLIGHT_MAX_DAYS + 2)
    _cache(db, "bl1", SHORT, hours_ago=24 * (main.HIGHLIGHT_MAX_DAYS + 1))
    assert _round(monkeypatch, BOTH) == []


def test_the_recheck_is_free_only(db, monkeypatch):
    """בדיקה חוזרת היא RSS/רשימת העלאות בלבד — לא חיפוש ב-100 יחידות."""
    _match(db)
    _cache(db, "bl1", SHORT, hours_ago=20)
    calls = _round(monkeypatch, BOTH)
    assert calls and all(c.get("free_only") for c in calls)


def test_a_user_opening_it_later_in_the_week_also_gets_the_full_one(db, monkeypatch):
    """החלון בפתיחה של משתמש היה שלושה ימים; התקציר המלא של מחזור שנפתח
    בסוף השבוע נשאר מחוץ לו."""
    _match(db, days_ago=5)
    _cache(db, "bl1", SHORT, hours_ago=24 * 4)
    monkeypatch.setattr(main, "search_youtube", lambda **kw: BOTH)
    row = db.execute("SELECT * FROM matches WHERE id='bl1'").fetchone()
    src = main.LEAGUES["bundesliga"]["sources"][0]
    out = main._source_highlights(row, src)
    assert [v["video_id"] for v in out["videos"]] == ["SHORT1", "LONG1"]
