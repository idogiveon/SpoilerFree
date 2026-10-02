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
    """שישה ולא שבעה: שבעה הם בדיוק המרחק בין שני מפגשים בנוק-אאוט
    של אופ"א, והגבול מכיל."""
    assert main.HIGHLIGHT_MAX_DAYS == 6


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


# ── ביקורת דאטה (2.10.26): שני מפגשים במרחק שבעה ימים בדיוק ─────────
def test_the_second_leg_is_not_offered_for_the_first(monkeypatch):
    """בנוק-אאוט של אופ"א רבע הגמר הוא שלישי ושלישי — בדיוק שבעה ימים.
    גבול מכיל של שבעה החזיר את תקציר הגומלין, עם התוצאה בכותרת, כתקציר
    של משחק ההלוך שהמשתמש עוד לא ראה."""
    leg1, leg2 = "2026-04-07", "2026-04-14"
    assert (datetime.fromisoformat(leg2) - datetime.fromisoformat(leg1)).days == 7
    assert not main._within_days(leg2, leg1, main.HIGHLIGHT_MAX_DAYS)
    feed = [("ret", "Arsenal 2-1 Real Madrid | Highlights | UEFA Champions League",
             f"{leg2}T22:00:00+00:00")]
    monkeypatch.setattr(main, "_rss_feed", lambda cid: feed)
    monkeypatch.setattr(main, "_video_durations", lambda ids: {})
    assert main.search_youtube("Real Madrid", "Arsenal", leg1, "UC123") == []


def test_but_a_channel_that_is_three_days_late_still_counts():
    """שחטאר מעלים אחרי שלושה ימים, והמקסימום שנמדד בכל הליגות הוא
    2.7 ימים — הקיצור ל-6 לא מפסיד אף דגימה שראינו."""
    assert main._within_days("2026-04-10", "2026-04-07", main.HIGHLIGHT_MAX_DAYS)
    assert main.HIGHLIGHT_MAX_DAYS >= 3
