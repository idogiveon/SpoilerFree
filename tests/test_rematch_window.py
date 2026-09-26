"""אותן שתי קבוצות נפגשות פעמיים בעונה, והכותרת זהה.

"Newcastle United v Hull City | Highlights" של מחזור 24 מתאים מילה במילה
גם למשחק של מחזור 5. ההבדל היחיד הוא מתי הסרטון עלה — ובלי גבול עליון,
פתיחת המשחק הישן הייתה מציגה תקציר של משחק שהמשתמש עוד לא ראה.
"""
from datetime import datetime, timedelta, timezone

import main

TITLE = "Newcastle United v Hull City | Premier League Highlights"


def _search(monkeypatch, feed, match_date):
    monkeypatch.setattr(main, "_rss_feed", lambda cid: feed)
    monkeypatch.setattr(main, "_video_durations", lambda ids: {})
    return main.search_youtube("Newcastle United", "Hull City", match_date, "UC123")


def test_the_later_meeting_is_not_offered_for_the_earlier_one(monkeypatch):
    feed = [("md24", TITLE, "2027-02-06T22:00:00+00:00")]
    assert _search(monkeypatch, feed, "2026-09-19") == []


def test_the_right_meeting_is_still_found(monkeypatch):
    feed = [("md5", TITLE, "2026-09-19T22:00:00+00:00")]
    assert [v["video_id"] for v in _search(monkeypatch, feed, "2026-09-19")] == ["md5"]


def test_a_channel_that_uploads_late_is_still_within_reach(monkeypatch):
    """שחטאר העלו אחרי שלושה ימים — הגבול הוא שבעה."""
    feed = [("late", TITLE, "2026-09-22T12:00:00+00:00")]
    assert [v["video_id"] for v in _search(monkeypatch, feed, "2026-09-19")] == ["late"]


def test_the_window_has_an_end(monkeypatch):
    feed = [("way_late", TITLE, "2026-10-19T12:00:00+00:00")]
    assert _search(monkeypatch, feed, "2026-09-19") == []


def test_only_the_meeting_being_watched_comes_back(monkeypatch):
    """שני המפגשים באותו פיד — נבחר רק זה של המשחק המבוקש."""
    feed = [("md24", TITLE, "2027-02-06T22:00:00+00:00"),
            ("md5", TITLE, "2026-09-19T22:00:00+00:00")]
    assert [v["video_id"] for v in _search(monkeypatch, feed, "2026-09-19")] == ["md5"]
    assert [v["video_id"] for v in _search(monkeypatch, feed, "2027-02-06")] == ["md24"]


def test_the_limit_is_stated_once(monkeypatch):
    assert main.HIGHLIGHT_MAX_DAYS == 7


# ── קישור אתר: לחיפוש ביוטיוב יש גבול עליון, ל-find_web_highlight לא היה ──
def test_the_website_is_not_scanned_for_a_match_that_is_too_old(db, monkeypatch):
    """עמוד ה-VOD של ספורט 1 מציג את המפגש האחרון. פתיחת המשחק של מחזור 5
    בפברואר החזירה את הכתבה של מחזור 22 — תוצאה של משחק שהמשתמש לא ראה,
    ונשמרה לנצח תחת המשחק הישן. HIGHLIGHT_MAX_DAYS חל גם כאן."""
    old = (datetime.now(timezone.utc) - timedelta(days=main.HIGHLIGHT_MAX_DAYS + 3))
    db.execute("INSERT INTO matches (id, league_key, home_team, away_team, date_utc, "
               "time_utc, status, matchday) VALUES ('r5', 'israel', 'Maccabi Haifa', "
               "'Hapoel Beer Sheva', ?, '18:00:00', 'FINISHED', 5)",
               (old.strftime("%Y-%m-%d"),))
    db.commit()
    row = db.execute("SELECT * FROM matches WHERE id='r5'").fetchone()
    monkeypatch.setattr(main, "_site_anchors", lambda url: [
        ("/video/9999", "תקציר: מכבי חיפה - הפועל באר שבע 3-1 (מחזור 22)"),
    ])
    w = main.LEAGUES["israel"]["web_sources"][0]
    assert main._web_link(row, w) is None


def test_a_fresh_match_still_gets_its_website_link(db, monkeypatch):
    fresh = datetime.now(timezone.utc) - timedelta(hours=20)
    db.execute("INSERT INTO matches (id, league_key, home_team, away_team, date_utc, "
               "time_utc, status, matchday) VALUES ('r6', 'israel', 'Maccabi Haifa', "
               "'Hapoel Beer Sheva', ?, '18:00:00', 'FINISHED', 22)",
               (fresh.strftime("%Y-%m-%d"),))
    db.commit()
    row = db.execute("SELECT * FROM matches WHERE id='r6'").fetchone()
    monkeypatch.setattr(main, "_site_anchors", lambda url: [
        ("/video/9999", "תקציר: מכבי חיפה - הפועל באר שבע 3-1 (מחזור 22)"),
    ])
    w = main.LEAGUES["israel"]["web_sources"][0]
    assert main._web_link(row, w) == "https://sport1.maariv.co.il/video/9999"
