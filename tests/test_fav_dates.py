"""אזור המועדפים בתצוגת ליגה: לכל משחק תאריך, בסדר כרונולוגי (ליג 1, פ.ס.ז')."""
import re

HTML = open("index.html", encoding="utf-8").read()
FN = re.search(r"function favGroupHTML\(ms\) \{(.*?)\n  \}", HTML, re.S).group(1)


def test_league_view_shows_a_date_per_favorite_match():
    assert "favDateHTML(m.date)" in FN
    assert "currentLeague === '__byday'" in FN          # ב"לפי יום" — בלי כפילות תאריך


def test_favorites_are_in_chronological_order():
    assert "parseDateStr(a.date) - parseDateStr(b.date)" in FN


def test_date_line_uses_today_and_yesterday_badges():
    fn = re.search(r"function favDateHTML\(date\) \{(.*?)\n  \}", HTML, re.S).group(1)
    assert "isToday(date)" in fn and "isYesterday(date)" in fn and "dayName(" in fn


def test_date_line_is_styled():
    assert ".fav-date {" in HTML
