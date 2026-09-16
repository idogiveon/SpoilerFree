"""חיפוש תקצירים: RSS קודם (0 יחידות), search.list רק כשהפיד לא מכריע."""
import main

CH = "UCtest"


def feed(*items):
    """items: (video_id, title, published_date) — מהחדש לישן, כמו ה-RSS."""
    return [(v, t, f"{d}T20:00:00+00:00") for v, t, d in items]


def no_network(*a, **k):
    raise AssertionError("unexpected network call")


def search(monkeypatch, fake_feed, date="2026-09-09"):
    monkeypatch.setattr(main, "_rss_feed", lambda cid: fake_feed)
    return main.search_youtube("Barcelona", "Feyenoord", date, CH,
                               query="Barcelona Feyenoord", implicit_team="Barcelona")


def units(db):
    r = db.execute("SELECT SUM(CAST(value AS INTEGER)) AS u FROM meta WHERE key LIKE 'yt_units:%'").fetchone()
    return r["u"] or 0


def test_rss_hit_costs_nothing(monkeypatch, db):
    monkeypatch.setattr(main.requests, "get", no_network)
    res = search(monkeypatch, feed(("v1", "HIGHLIGHTS | FC BARCELONA 5 vs 1 FEYENOORD", "2026-09-10"),
                                   ("v0", "Training", "2026-09-01")))
    assert [v["video_id"] for v in res] == ["v1"]
    assert units(db) == 0


def test_rss_covers_match_day_no_highlight_yet(monkeypatch, db):
    monkeypatch.setattr(main.requests, "get", no_network)
    # הפיד מגיע אחורה עד לפני יום המשחק ואין תקציר — "עוד לא עלה", בלי חיפוש
    res = search(monkeypatch, feed(("v1", "Training", "2026-09-10"), ("v0", "Presser", "2026-09-01")))
    assert res == []
    assert units(db) == 0


BUSY = feed(*[(f"x{i}", "Some clip", "2026-09-12") for i in range(15)])   # הפיד לא מגיע ליום המשחק
HL = "HIGHLIGHTS | FC BARCELONA 5 vs 1 FEYENOORD"


class Resp:
    def __init__(self, data):
        self._d = data

    def json(self):
        return self._d


def _pl(vid, title, date):
    return {"snippet": {"title": title, "publishedAt": f"{date}T20:00:00Z",
                        "resourceId": {"videoId": vid}}}


def test_busy_channel_pages_uploads_instead_of_search(monkeypatch, db):
    calls = []

    def fake_get(url, params=None, timeout=None):
        calls.append(url)
        if url.endswith("/playlistItems"):
            assert params["playlistId"] == "UU" + CH[2:]
            if not params.get("pageToken"):
                return Resp({"items": [_pl("n1", "Some clip", "2026-09-12"), _pl("api1", HL, "2026-09-10")],
                             "nextPageToken": "p2"})
            return Resp({"items": [_pl("old", HL, "2026-09-01")], "nextPageToken": "p3"})
        if url.endswith("/videos"):
            return Resp({"items": [{"id": "api1", "contentDetails": {"duration": "PT4M10S"}}]})
        raise AssertionError("search.list should not be called")

    monkeypatch.setattr(main, "YOUTUBE_API_KEY", "k")
    monkeypatch.setattr(main.requests, "get", fake_get)
    res = search(monkeypatch, BUSY)
    assert [v["video_id"] for v in res] == ["api1"]              # "old" מלפני יום המשחק — לא
    assert sum(u.endswith("/playlistItems") for u in calls) == 2  # עצר כשהגיע לפני יום המשחק
    assert units(db) == 3                                         # 2 דפים + videos.list (היה 101)


def test_uploads_error_falls_back_to_search(monkeypatch, db):
    def fake_get(url, params=None, timeout=None):
        if url.endswith("/playlistItems"):
            return Resp({"error": {"message": "playlistNotFound"}})
        if url.endswith("/search"):
            return Resp({"items": [{"id": {"videoId": "s1"},
                                    "snippet": {"title": HL, "publishedAt": "2026-09-10T20:00:00Z"}}]})
        return Resp({"items": []})

    monkeypatch.setattr(main, "YOUTUBE_API_KEY", "k")
    monkeypatch.setattr(main.requests, "get", fake_get)
    assert [v["video_id"] for v in search(monkeypatch, BUSY)] == ["s1"]
    assert units(db) == 101


def test_daily_brake_blocks_paid_calls(monkeypatch, db):
    monkeypatch.setattr(main, "YOUTUBE_API_KEY", "k")
    monkeypatch.setattr(main.requests, "get", no_network)
    main._yt_units(9000)
    assert search(monkeypatch, BUSY) is None   # None: לא נשמר כ"לא נמצא", ינסה שוב אחרי האיפוס


def test_free_rss_still_works_above_brake(monkeypatch, db):
    monkeypatch.setattr(main, "YOUTUBE_API_KEY", "k")
    monkeypatch.setattr(main.requests, "get", no_network)
    main._yt_units(9000)
    res = search(monkeypatch, feed(("v1", HL, "2026-09-10"), ("v0", "Training", "2026-09-01")))
    assert [v["video_id"] for v in res] == ["v1"]


def test_rss_failure_without_key_is_unknown_not_empty(monkeypatch):
    """RSS נפל ואין מפתח API — None ("לא יודעים"), ולא [] שנשמר כ"אין תקציר"."""
    assert search(monkeypatch, None) is None


def test_retry_guard_keeps_fresh_cache(db):
    from datetime import datetime, timedelta, timezone
    now = datetime.now(timezone.utc)
    db.execute("INSERT INTO highlight_cache VALUES ('m1','fresh','[]',?)", (now.isoformat(),))
    db.execute("INSERT INTO highlight_cache VALUES ('m1','old','[]',?)",
               ((now - timedelta(hours=1)).isoformat(),))
    db.commit()
    main.clear_cache(None, "m1")
    left = [r["source_id"] for r in db.execute(
        "SELECT source_id FROM highlight_cache WHERE match_id='m1'").fetchall()]
    assert left == ["fresh"]
