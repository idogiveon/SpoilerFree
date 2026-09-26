"""ערוץ עמוס: ה-RSS לא מגיע עד יום המשחק.

הפועל ת"א–הפועל פ"ת, מחזור 5 (26.9.26): לערוץ של מנהלת הליגות יש תקציר
("Hapoel Tel Aviv vs. Hapoel Petah Tikva - Game Highlights"), והאתר לא
הציע אותו. ה-RSS שם מחזיק 15 פריטים שמכסים יומיים-שלושה, כלומר תקציר
של מחזור שעבר נמצא מחוץ לטווח — וברקע ויתרנו בדיוק שם.

רשימת ההעלאות כן מגיעה עד יום המשחק, ועולה יחידה אחת ל-50 סרטונים מול
100 של חיפוש. לכן ברקע היא מותרת והחיפוש היקר לא.
"""
import main

TITLE = "Hapoel Tel Aviv vs. Hapoel Petah Tikva - Game Highlights"
MATCH_DATE = "2026-09-18"
# ה-RSS האמיתי של הערוץ באותו יום: 15 פריטים, הישן ביותר מ-22.9
BUSY_FEED = [(f"v{i}", "תוכן אחר", f"2026-09-2{2 + i % 3}T10:00:00+00:00")
             for i in range(15)]


def _search(monkeypatch, *, free_only, uploads=None, key="k"):
    monkeypatch.setattr(main, "_rss_feed", lambda cid: BUSY_FEED)
    monkeypatch.setattr(main, "YOUTUBE_API_KEY", key)
    monkeypatch.setattr(main, "_video_durations", lambda ids: {})
    monkeypatch.setattr(main, "_uploads_since", lambda cid, d: uploads)
    return main.search_youtube("Hapoel Tel-Aviv", "Hapoel Petah Tikva", MATCH_DATE,
                               "UCxjaVFauWASy0CuJfHKZeiw", il_both=True,
                               free_only=free_only)


def test_the_title_itself_was_never_the_problem():
    assert main.is_il_both_teams_en(TITLE, "Hapoel Tel-Aviv", "Hapoel Petah Tikva",
                                    "2026-09-18T14:00:00+00:00", MATCH_DATE)


def test_the_feed_cannot_decide_so_it_is_not_treated_as_an_answer(monkeypatch):
    """15 פריטים שמתחילים אחרי יום המשחק — "לא נמצא" כאן הוא שקר."""
    assert min(p for _, _, p in BUSY_FEED)[:10] > MATCH_DATE
    assert _search(monkeypatch, free_only=True, uploads=None) is None


def test_the_background_now_reaches_it_through_the_cheap_list(monkeypatch):
    found = _search(monkeypatch, free_only=True,
                    uploads=([("hit", TITLE, "2026-09-18T14:00:00+00:00")], True))
    assert [v["video_id"] for v in found] == ["hit"]


def test_the_background_still_refuses_the_expensive_search(monkeypatch):
    """זה מה ששרף 9,000 יחידות ביום."""
    monkeypatch.setattr(main, "requests", None)      # כל קריאת רשת תתפוצץ
    assert _search(monkeypatch, free_only=True, uploads=None) is None


def test_without_a_key_the_background_gives_up_quietly(monkeypatch):
    assert _search(monkeypatch, free_only=True, uploads=None, key="") is None


def test_the_background_respects_its_own_budget(monkeypatch):
    monkeypatch.setattr(main, "_yt_units_today", lambda: main.PREFETCH_UNIT_BUDGET)
    assert _search(monkeypatch, free_only=True,
                   uploads=([("hit", TITLE, "2026-09-18T14:00:00+00:00")], True)) is None


def test_a_user_opening_the_match_may_still_pay_for_a_search(monkeypatch):
    """בקשה של משתמש אמיתי אינה מוגבלת לתקציב הרקע."""
    monkeypatch.setattr(main, "_yt_units_today", lambda: main.PREFETCH_UNIT_BUDGET + 1)
    found = _search(monkeypatch, free_only=False,
                    uploads=([("hit", TITLE, "2026-09-18T14:00:00+00:00")], True))
    assert [v["video_id"] for v in found] == ["hit"]
