"""ערוץ מועדון שלא כותב את היריבה (פ.ס.וו): מילת תקציר + עלה ביום המשחק/למחרת."""
import main

PSV_TITLE = "HIGHLIGHTS | A proper PSV night 😊"


def _search(monkeypatch, feed, date="2026-09-16", club="PSV Eindhoven"):
    monkeypatch.setattr(main, "_rss_feed", lambda cid: feed)
    monkeypatch.setattr(main, "_video_durations", lambda ids: {})
    return main.search_youtube("PSV Eindhoven", "Ajax", date, "UCx", implicit_team=club)


def test_psv_style_title_is_accepted_on_the_day(monkeypatch):
    res = _search(monkeypatch, [("v1", PSV_TITLE, "2026-09-16T22:00:00+00:00")])
    assert [v["video_id"] for v in res] == ["v1"]


def test_next_day_still_counts(monkeypatch):
    res = _search(monkeypatch, [("v2", PSV_TITLE, "2026-09-17T09:00:00+00:00")])
    assert [v["video_id"] for v in res] == ["v2"]


def test_three_days_later_is_another_match(monkeypatch):
    assert _search(monkeypatch, [("v3", PSV_TITLE, "2026-09-19T20:00:00+00:00")]) == []


def test_press_conference_never_counts(monkeypatch):
    feed = [("v4", "PSV | Press conference after the match", "2026-09-16T23:00:00+00:00")]
    assert _search(monkeypatch, feed) == []


def test_other_channels_are_not_loosened(monkeypatch):
    """בלי ערוץ מועדון — כותרת בלי שתי הקבוצות נדחית, גם באותו יום."""
    monkeypatch.setattr(main, "_rss_feed", lambda cid: [("v5", "HIGHLIGHTS | A great night",
                                                        "2026-09-16T22:00:00+00:00")])
    monkeypatch.setattr(main, "_video_durations", lambda ids: {})
    assert main.search_youtube("PSV Eindhoven", "Ajax", "2026-09-16", "UCx") == []


def test_ajax_style_title_still_works(monkeypatch):
    """אייאקס כן כותבים את שתי הקבוצות — הכלל הרגיל, בלי תלות בתאריך."""
    feed = [("v6", "Second big win in 4 days! 🫡 | Highlights Ajax - Willem II | VriendenLoterij Eredivisie",
             "2026-09-20T22:00:00+00:00")]
    monkeypatch.setattr(main, "_rss_feed", lambda cid: feed)
    monkeypatch.setattr(main, "_video_durations", lambda ids: {})
    res = main.search_youtube("Ajax", "Willem II", "2026-09-15", "UCx", implicit_team="Ajax")
    assert [v["video_id"] for v in res] == ["v6"]
