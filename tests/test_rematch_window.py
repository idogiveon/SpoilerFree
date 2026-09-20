"""אותן שתי קבוצות נפגשות פעמיים בעונה, והכותרת זהה.

"Newcastle United v Hull City | Highlights" של מחזור 24 מתאים מילה במילה
גם למשחק של מחזור 5. ההבדל היחיד הוא מתי הסרטון עלה — ובלי גבול עליון,
פתיחת המשחק הישן הייתה מציגה תקציר של משחק שהמשתמש עוד לא ראה.
"""
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
