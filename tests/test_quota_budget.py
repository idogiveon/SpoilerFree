"""בדיקות רקע לא שורפות מכסה (15–16.9.26: 9,000 יחידות ביום = הבלם)."""
from datetime import datetime, timedelta, timezone

import main


def _row(db, mid, kickoff, league="israel"):
    db.execute("INSERT INTO matches (id, league_key, home_team, away_team, date_utc, time_utc, status) "
               "VALUES (?, ?, 'Maccabi Haifa', 'Hapoel Tel-Aviv', ?, ?, 'FINISHED')",
               (mid, league, kickoff.strftime("%Y-%m-%d"), kickoff.strftime("%H:%M:%S")))
    db.commit()


def test_free_only_never_calls_the_paid_api(monkeypatch):
    monkeypatch.setattr(main, "_rss_feed", lambda cid: None)      # הפיד לא הכריע
    monkeypatch.setattr(main, "YOUTUBE_API_KEY", "key")

    def boom(*a, **k):
        raise AssertionError("background check must not spend quota")
    monkeypatch.setattr(main.requests, "get", boom)
    assert main.search_youtube("A", "B", "2026-09-06", "UCx", free_only=True) is None


def test_free_only_still_uses_the_free_feed(monkeypatch):
    feed = [("v1", "מכבי חיפה נגד הפועל תל אביב תקציר", "2026-09-06T21:00:00+00:00")]
    monkeypatch.setattr(main, "_rss_feed", lambda cid: feed)
    monkeypatch.setattr(main, "_video_durations", lambda ids: {})
    res = main.search_youtube("Maccabi Haifa", "Hapoel Tel-Aviv", "2026-09-06", "UCx",
                              home_alt=main.to_hebrew_team("Maccabi Haifa"),
                              away_alt=main.to_hebrew_team("Hapoel Tel-Aviv"),
                              il_both=True, free_only=True)
    assert [v["video_id"] for v in res] == ["v1"]


def _prefetch_modes(db, monkeypatch, units):
    """מריץ סבב רקע ומחזיר {source_id: free_only} לכל קריאה."""
    calls = {}
    monkeypatch.setattr(main, "_yt_units_today", lambda: units)
    monkeypatch.setattr(main, "_web_link", lambda row, w: None)
    monkeypatch.setattr(main, "_source_highlights",
                        lambda row, s, free_only=False: calls.setdefault(s["id"], free_only))
    main.prefetch_highlights_once()
    return calls


def test_recheck_is_free_and_first_lookup_is_paid_within_budget(db, monkeypatch):
    _row(db, "i1", datetime.now(timezone.utc) - timedelta(hours=5))
    src = main.LEAGUES["israel"]["sources"]
    db.execute("INSERT INTO highlight_cache VALUES ('i1', ?, '[]', ?)",
               (src[0]["id"], (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat()))
    db.commit()
    calls = _prefetch_modes(db, monkeypatch, units=0)
    assert calls[src[0]["id"]] is True        # נבדק כבר — רק חינם
    assert calls[src[1]["id"]] is False       # פעם ראשונה — מותר בתשלום


def test_over_the_background_budget_everything_is_free(db, monkeypatch):
    _row(db, "i2", datetime.now(timezone.utc) - timedelta(hours=5))
    calls = _prefetch_modes(db, monkeypatch, units=main.PREFETCH_UNIT_BUDGET + 1)
    assert calls and all(free is True for free in calls.values())


def test_budget_leaves_most_of_the_day_to_real_users():
    assert main.PREFETCH_UNIT_BUDGET < main.YT_DAILY_BRAKE / 3
