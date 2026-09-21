"""תשובת שגיאה מהשרת היא לא נתונים.

עד עכשיו `apiFetch` טיפל רק ב-401. כל שאר השגיאות חזרו כ-`{"detail": ...}`,
וכל קורא שעשה `.json()` קיבל אובייקט שנראה כמו תשובה תקינה. כך הופיע
"⏳ undefined" בחלון המשחק (19.9.26) — והיו עוד עשרה מקומות חשופים.
"""
import re

HTML = open("index.html", encoding="utf-8").read()


def _api_fetch_body():
    block = HTML[HTML.index("async function apiFetch("):]
    return block[:block.index("\n  }")]


def test_every_error_becomes_an_exception():
    body = _api_fetch_body()
    assert "if (r.status === 401)" in body          # התנהגות קיימת נשמרת
    assert "if (!r.ok) {" in body
    assert "throw err;" in body


def test_the_server_detail_is_carried_but_not_shown_raw():
    """ההודעה מהשרת בעברית ולא נכתבה למשתמש קצה: לקונסול, לא למסך."""
    assert ".detail || ''" in _api_fetch_body()
    assert "function errorHTML(err)" in HTML
    assert "console.warn('[api]', err.message)" in HTML
    assert "${err.message}</div>" not in HTML      # לא מוצג גולמי בשום מקום


def test_no_caller_still_checks_the_status_itself():
    """הבדיקה מרוכזת במקום אחד — כפילות תתפצל מהר."""
    assert HTML.count("if (!r.ok)") == 1


def test_the_match_window_relies_on_the_central_guard():
    block = HTML[HTML.index("apiFetch(`${API}/highlights/"):]
    block = block[:block.index(".then(data => {")]
    assert ".then(r => r.json())" in block
    assert "!r.ok" not in block


def test_the_two_screens_a_user_sees_render_a_real_message():
    """אומת גם בדפדפן מול תשובת 404 ו-500: חלון המשחק מציג
    "לא הצלחנו לחפש תקציר", ותצוגת לפי יום מציגה "שגיאה" — בשפה
    שנבחרה, ובלי "undefined" בשום מקום."""
    modal = HTML[HTML.index("apiFetch(`${API}/highlights/"):]
    modal = modal[:modal.index("function loadVideo")]
    assert ".catch(err => {" in modal
    assert "t('search_error')" in modal

    day = HTML[HTML.index("async function loadDay()"):]
    day = day[:day.index("function renderDayMatches")]
    assert "errorHTML(err)" in day
    assert "err.message === 'auth'" in day      # ניתוק מטופל בנפרד
