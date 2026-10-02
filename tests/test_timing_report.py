"""המדידה שממנה ייגזרו החלונות.

HIGHLIGHT_WINDOW_HOURS=48 ו-_SLOW_LEAGUES={"israel": 5*24} נקבעו בעין.
הדוח הזה אומר מה הערוצים באמת עושים — ובאותה נשימה כמה דגימות עומדות
מאחורי כל מספר: "שלושה שבועות" שכוללים הפסקת נבחרות הם עשרה ימי
משחקים, וזה חייב להיראות בפלט ולא להיעלם בתוך ממוצע.
"""
import json
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

import main


def _match(db, mid, league, days_ago, hour="18:00:00"):
    day = (datetime.now(timezone.utc) - timedelta(days=days_ago)).strftime("%Y-%m-%d")
    db.execute("INSERT INTO matches (id, league_key, home_team, away_team, date_utc, "
               "time_utc, status) VALUES (?, ?, 'A', 'B', ?, ?, 'FINISHED')",
               (mid, league, day, hour))
    db.commit()
    return day


def _cache(db, mid, videos):
    db.execute("INSERT OR REPLACE INTO highlight_cache VALUES (?,?,?,?)",
               (mid, "src", json.dumps(videos), datetime.now(timezone.utc).isoformat()))
    db.commit()


def _video(day, hours_after, extended=False, hour=18):
    pub = datetime.fromisoformat(f"{day}T{hour:02d}:00:00+00:00") + timedelta(hours=hours_after)
    return {"video_id": f"v{hours_after}", "label": "x", "extended": extended,
            "published": pub.isoformat()}


def _report(days=30):
    return TestClient(main.app).get(f"/debug/timing?days={days}").json()


def test_it_measures_the_channel_not_our_polling(db):
    """found_at אומר מתי אנחנו בדקנו. published אומר מה הערוץ עשה."""
    day = _match(db, "t1", "bundesliga", 3)
    _cache(db, "t1", [_video(day, 2.5), _video(day, 50, extended=True)])
    lg = _report()["leagues"]["bundesliga"]
    assert lg["short"]["n"] == 1 and lg["short"]["p50"] == 2.5
    assert lg["full"]["n"] == 1 and lg["full"]["p50"] == 50.0


def test_the_full_version_is_counted_separately(db):
    """זה כל הסיפור של הבונדסליגה: הקצר בערב המשחק, המלא יומיים אחרי.
    ממוצע אחד על שניהם היה מסתיר בדיוק את מה שאנחנו מחפשים."""
    for i in range(3):
        day = _match(db, f"b{i}", "bundesliga", 4 + i)
        _cache(db, f"b{i}", [_video(day, 3), _video(day, 48, extended=True)])
    lg = _report()["leagues"]["bundesliga"]
    assert lg["short"]["max"] == 3.0
    assert lg["full"]["max"] == 48.0


def test_how_thin_the_sample_is_cannot_hide(db):
    """הפסקת נבחרות: הרבה ימים, מעט משחקים."""
    for i, d in enumerate((20, 19, 2)):
        day = _match(db, f"i{i}", "israel", d)
        _cache(db, f"i{i}", [_video(day, 6)])
    lg = _report()["leagues"]["israel"]
    assert lg["short"]["n"] == 3
    assert lg["match_days"] == 3          # שלושה ימי משחקים, לא שלושה שבועות
    assert lg["from"] < lg["to"]
    assert lg["window_now_h"] == 120      # מה שמוגדר היום, להשוואה


def test_a_video_from_another_meeting_is_not_a_sample(db):
    """תקציר שנתפס בטעות מהמפגש החוזר היה מזהם את המדידה."""
    day = _match(db, "n1", "laliga", 3)
    _cache(db, "n1", [_video(day, 24 * 60)])          # חודשיים אחרי
    assert "laliga" not in _report()["leagues"]


def test_rows_from_before_we_saved_published_are_skipped(db):
    day = _match(db, "o1", "seriea", 3)
    _cache(db, "o1", [{"video_id": "old", "label": "x", "extended": False}])
    assert "seriea" not in _report()["leagues"]


def test_it_is_admin_only(db, monkeypatch):
    monkeypatch.setattr(main, "AUTH_ON", True)
    assert TestClient(main.app).get("/debug/timing").status_code == 401
