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


def test_busy_channel_falls_back_to_api(monkeypatch, db):
    busy = feed(*[(f"x{i}", "Some clip", "2026-09-12") for i in range(15)])
    calls = []

    class Resp:
        def __init__(self, data):
            self._d = data

        def json(self):
            return self._d

    def fake_get(url, params=None, timeout=None):
        calls.append(url)
        if url.endswith("/search"):
            return Resp({"items": [{"id": {"videoId": "api1"},
                                    "snippet": {"title": "HIGHLIGHTS | FC BARCELONA 5 vs 1 FEYENOORD"}}]})
        return Resp({"items": [{"id": "api1", "contentDetails": {"duration": "PT4M10S"}}]})

    monkeypatch.setattr(main, "YOUTUBE_API_KEY", "k")
    monkeypatch.setattr(main.requests, "get", fake_get)
    res = search(monkeypatch, busy)
    assert [v["video_id"] for v in res] == ["api1"]
    assert sum(u.endswith("/search") for u in calls) == 1
    assert units(db) == 101   # search 100 + videos.list 1


def test_rss_failure_without_key_returns_empty(monkeypatch):
    assert search(monkeypatch, None) == []


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
