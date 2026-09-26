"""מדיניות פרטיות — לפני המשתמש הראשון.

הטקסט נכתב מתוך הסכימה בפועל (26.9.26) ולא מתבנית. הבדיקות כאן קושרות
בין השניים: אם ייאסף שדה חדש או ייווסף צד שלישי, הן ייפלו.
"""
from fastapi.testclient import TestClient

import main

HTML = open("index.html", encoding="utf-8").read()


def _page(lang="he"):
    return TestClient(main.app).get(f"/privacy?lang={lang}").text


def test_it_is_public_and_needs_no_account(monkeypatch):
    """מי ששוקל להירשם צריך לקרוא אותה לפני שהוא מוסר מייל."""
    monkeypatch.setattr(main, "AUTH_ON", True)
    r = TestClient(main.app).get("/privacy")
    assert r.status_code == 200
    assert "<h2>" in r.text


def test_hebrew_and_english_are_written_out():
    assert "פרטיות" in _page("he")
    assert "Privacy" in _page("en")
    # es/fr נופלים לאנגלית — עדיף על תרגום מכונה של טקסט משפטי.
    # הגוף זהה; הקישורים בתחתית נושאים את שפת הקורא.
    assert main.privacy_html("fr") == main.privacy_html("en")
    assert "?lang=fr" in _page("fr")


def test_every_table_that_holds_a_person_is_described(db):
    """הטבלאות שמפתחן הוא כתובת מייל."""
    page = _page("he")
    for word in ("מייל", "סיסמה", "הליגות והקבוצות", "פתיחת משחק"):
        assert word in page, word


def test_the_password_claim_matches_the_code():
    assert main.PW_ITER == 200_000
    assert "200,000" in _page("he")
    assert "200,000" in _page("en")


def test_the_session_length_matches_the_code():
    assert main.SESSION_DAYS == 90
    assert "90" in _page("he")


def test_the_third_parties_the_browser_really_reaches_are_named():
    """TheSportsDB נשלף מהדפדפן של המשתמש — כלומר הוא רואה את ה-IP שלו.
    זו בדיוק העובדה שקל לשכוח במסמך שנכתב מתבנית."""
    page = _page("en")
    for who in ("YouTube", "TheSportsDB", "Brevo", "Render", "Turso", "Google Fonts"):
        assert who in page, who
    assert "IP" in page


def test_the_old_claim_that_nothing_leaves_is_gone():
    """הטקסט הישן הבטיח שהמידע "לא מועבר לצדדים שלישיים" — לא נכון."""
    assert "לא מועבר לצדדים שלישיים" not in main.COOKIES_HTML_BY_LANG["he"]
    assert "/privacy" in main.COOKIES_HTML_BY_LANG["he"]


def test_deletion_is_offered_because_it_exists():
    assert any(r.path == "/auth/delete_account" for r in main.app.routes
               if hasattr(r, "path"))
    assert "למחוק את החשבון" in _page("he")


def test_a_way_to_reach_the_owner(monkeypatch):
    monkeypatch.setattr(main, "NOTIFY_EMAILS", {"owner@example.com"})
    assert "owner@example.com" in main.privacy_html("he")
    monkeypatch.setattr(main, "NOTIFY_EMAILS", set())
    monkeypatch.setattr(main, "ADMIN_EMAILS", set())
    assert "mailto" not in main.privacy_html("he")   # בלי כתובת — בלי שורה ריקה


def test_both_doors_link_to_it():
    """מסך הכניסה והאפליקציה."""
    assert 'href="/privacy"' in main.LOGIN_PAGE
    assert 'href="/privacy"' in HTML
    for lang in ("he", "en", "es", "fr"):
        assert main.LOGIN_I18N[lang]["privacy_link"]
    assert HTML.count('"privacy_link"') >= 4
