"""שיפורי מכסה (#30): חיפוש כשהדפדוף נעצר לפני יום המשחק, "לא נמצא" מתייצב
לפי גיל המשחק, וחיפוש מראש ברקע של משחקים שהסתיימו."""
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

import main
from test_youtube_search import BUSY, HL, Resp, _pl, search, units


def _row(db, mid, kickoff, status="FINISHED", league="laliga", home="Barcelona", away="Getafe"):
    db.execute("INSERT INTO matches (id, league_key, home_team, away_team, date_utc, time_utc, status) "
               "VALUES (?, ?, ?, ?, ?, ?, ?)",
               (mid, league, home, away, kickoff.strftime("%Y-%m-%d"), kickoff.strftime("%H:%M:%S"), status))
    db.commit()
    return db.execute("SELECT * FROM matches WHERE id=?", (mid,)).fetchone()


def test_not_found_retry_grows_with_match_age(db):
    now = datetime.now(timezone.utc)
    assert main._not_found_retry(_row(db, "a", now - timedelta(days=1))) == timedelta(minutes=30)
    assert main._not_found_retry(_row(db, "b", now - timedelta(days=3))) == timedelta(hours=6)
    # משחק ישן — פעם בשבוע, כדי שתקלה זמנית לא תקבע "אין תקציר" לנצח
    assert main._not_found_retry(_row(db, "c", now - timedelta(days=10))) == timedelta(days=7)


def test_old_not_found_is_not_searched_again(db, monkeypatch):
    now = datetime.now(timezone.utc)
    _row(db, "old", now - timedelta(days=10))
    for sid in ("one_laliga", "laliga_official"):
        db.execute("INSERT INTO highlight_cache VALUES ('old', ?, '[]', ?)",
                   (sid, (now - timedelta(days=2)).isoformat()))
    db.commit()

    def boom(*a, **k):
        raise AssertionError("should not search")

    monkeypatch.setattr(main, "search_youtube", boom)
    monkeypatch.setattr(main, "resolve_web_link", lambda *a, **k: None)
    res = TestClient(main.app).get("/highlights/old").json()
    assert {s["status"] for s in res["sources"]} == {"cached"}


def test_uploads_cap_before_match_day_falls_back_to_search(monkeypatch, db):
    calls = []

    def fake_get(url, params=None, timeout=None):
        calls.append(url)
        if url.endswith("/playlistItems"):   # תמיד סרטונים חדשים, אף פעם לא מגיע ליום המשחק
            return Resp({"items": [_pl("n", "Some clip", "2026-09-12")], "nextPageToken": "more"})
        if url.endswith("/search"):
            return Resp({"items": [{"id": {"videoId": "s1"},
                                    "snippet": {"title": HL, "publishedAt": "2026-09-10T20:00:00Z"}}]})
        return Resp({"items": []})

    monkeypatch.setattr(main, "YOUTUBE_API_KEY", "k")
    monkeypatch.setattr(main.requests, "get", fake_get)
    assert [v["video_id"] for v in search(monkeypatch, BUSY)] == ["s1"]
    assert sum(u.endswith("/playlistItems") for u in calls) == main.UPLOADS_MAX_PAGES
    assert units(db) == main.UPLOADS_MAX_PAGES + 100 + 1


def test_prefetch_searches_recent_finished_matches_once(db, monkeypatch):
    now = datetime.now(timezone.utc)
    _row(db, "recent", now - timedelta(hours=10))                      # כן
    _row(db, "old", now - timedelta(days=3))                           # ישן מדי
    _row(db, "future", now + timedelta(hours=5), status="SCHEDULED")   # עוד לא שוחק
    searched = []

    def fake_search(**k):
        searched.append(k["channel_id"])
        return [{"video_id": "v", "label": "תקציר", "extended": False}]

    monkeypatch.setattr(main, "search_youtube", lambda *a, **k: fake_search(**k))
    assert main.prefetch_highlights_once() == 1
    n_sources = len([s for s in main.LEAGUES["laliga"]["sources"] if s.get("channel_id")])
    assert len(searched) == n_sources
    cached = db.execute("SELECT COUNT(*) AS c FROM highlight_cache WHERE match_id='recent'").fetchone()["c"]
    assert cached == n_sources
    assert main.prefetch_highlights_once() == 0          # כבר בקאש — לא מחפש שוב


def test_prefetch_over_the_budget_only_uses_the_free_feed(db, monkeypatch):
    """מעל תקציב הרקע הבדיקה נמשכת — אבל רק מהפיד החינמי, בלי מכסה."""
    _row(db, "recent", datetime.now(timezone.utc) - timedelta(hours=10))
    main._yt_units(main.YT_DAILY_BRAKE)
    modes = []
    monkeypatch.setattr(main, "search_youtube",
                        lambda *a, **k: modes.append(k.get("free_only")) or [])
    main.prefetch_highlights_once()
    assert modes and all(m is True for m in modes)
