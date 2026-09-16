"""תקלת RSS לא "מקבעת" משחק בלי תקציר (MLS 6.9 נתקע על "לא עלה תקציר")."""
from datetime import datetime, timedelta, timezone

import main


def _row(db, mid, kickoff, league="mls"):
    db.execute("INSERT INTO matches (id, league_key, home_team, away_team, date_utc, time_utc, status) "
               "VALUES (?, ?, 'LA Galaxy', 'Austin', ?, ?, 'FINISHED')",
               (mid, league, kickoff.strftime("%Y-%m-%d"), kickoff.strftime("%H:%M:%S")))
    db.commit()
    return db.execute("SELECT * FROM matches WHERE id=?", (mid,)).fetchone()


def test_unavailable_feed_is_unknown_not_empty(monkeypatch):
    """RSS נפל (None) ואין מפתח API — לא יודעים, ולא "אין תקציר"."""
    monkeypatch.setattr(main, "_rss_feed", lambda cid: None)
    monkeypatch.setattr(main, "YOUTUBE_API_KEY", "")
    assert main.search_youtube("A", "B", "2026-09-06", "UCx") is None


def test_feed_that_covers_the_match_still_says_no_highlight_yet(monkeypatch):
    """הפיד כן הגיע ומכסה את יום המשחק — "עוד אין תקציר" זו תשובה אמיתית."""
    monkeypatch.setattr(main, "_rss_feed", lambda cid: [("v", "Other match | Highlights",
                                                        "2026-09-07T10:00:00+00:00")])
    monkeypatch.setattr(main, "YOUTUBE_API_KEY", "")
    assert main.search_youtube("A", "B", "2026-09-06", "UCx") == []


def test_outage_is_not_cached(db, monkeypatch):
    row = _row(db, "m1", datetime.now(timezone.utc) - timedelta(days=10))
    monkeypatch.setattr(main, "search_youtube", lambda *a, **k: None)
    res = main._source_highlights(row, main.LEAGUES["mls"]["sources"][0])
    assert res["status"] == "api_error"
    assert db.execute("SELECT COUNT(*) AS n FROM highlight_cache").fetchone()["n"] == 0


def test_old_match_is_retried_weekly(db):
    """לפני התיקון: משחק בן שבוע+ לא נבדק שוב לעולם."""
    old = _row(db, "m2", datetime.now(timezone.utc) - timedelta(days=10))
    assert main._not_found_retry(old) == timedelta(days=7)
    fresh = _row(db, "m3", datetime.now(timezone.utc) - timedelta(hours=5))
    assert main._not_found_retry(fresh) == timedelta(minutes=30)


def test_old_not_found_is_searched_again_after_a_week(db, monkeypatch):
    row = _row(db, "m4", datetime.now(timezone.utc) - timedelta(days=10))
    src = main.LEAGUES["mls"]["sources"][0]
    stale = (datetime.now(timezone.utc) - timedelta(days=8)).isoformat()
    db.execute("INSERT INTO highlight_cache VALUES ('m4', ?, '[]', ?)", (src["id"], stale))
    db.commit()
    calls = []
    monkeypatch.setattr(main, "search_youtube", lambda *a, **k: calls.append(1) or [
        {"video_id": "v9", "label": "תקציר", "extended": False, "published": ""}])
    res = main._source_highlights(row, src)
    assert calls and [v["video_id"] for v in res["videos"]] == ["v9"]
