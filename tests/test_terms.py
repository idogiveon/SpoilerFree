"""תנאי שימוש — לפני הפתיחה לאנשים.

כמו מסמך הפרטיות, נכתב מתוך מה שהאתר באמת עושה: הוא לא מארח תקצירים,
הוא תלוי במקורות חיצוניים, ואי אפשר להבטיח שתוצאה לא תיחשף.
"""
from fastapi.testclient import TestClient

import main

HTML = open("index.html", encoding="utf-8").read()


def _page(lang="he"):
    return TestClient(main.app).get(f"/terms?lang={lang}").text


def test_it_is_public(monkeypatch):
    monkeypatch.setattr(main, "AUTH_ON", True)
    assert TestClient(main.app).get("/terms").status_code == 200


def test_it_says_we_do_not_host_the_videos():
    """זו הנקודה המשפטית המרכזית: אנחנו מפנים, לא מאחסנים."""
    assert "לא מארחים" in _page("he")
    assert "do not host" in _page("en")


def test_there_is_a_way_to_ask_for_a_link_to_come_down(monkeypatch):
    monkeypatch.setattr(main, "NOTIFY_EMAILS", {"owner@example.com"})
    he = main.terms_html("he")
    assert "בעל זכויות" in he and "יוסר" in he
    assert "owner@example.com" in he


def test_it_does_not_promise_what_cannot_be_promised():
    """האתר עושה מאמץ שלא ייחשפו תוצאות — הבטחה גורפת הייתה שקר."""
    assert "אי אפשר להבטיח" in _page("he")
    assert "cannot be guaranteed" in _page("en")


def test_the_limits_it_describes_are_the_ones_in_the_code():
    he = _page("he")
    assert "אוטומטיים" in he          # יש הגבלת קצב בפועל
    assert main.REGISTER_PER_IP_HOUR > 0
    assert "למחוק את החשבון" in he    # והנתיב קיים
    assert any(getattr(r, "path", "") == "/auth/delete_account" for r in main.app.routes)


def test_both_documents_link_to_each_other():
    page = _page("he")
    assert "/privacy?lang=he" in page and "/terms?lang=he" in page


def test_the_contact_line_has_one_source():
    """גם הפרטיות וגם התנאים צריכים כתובת — ומקום אחד שמייצר אותה."""
    src = open("main.py", encoding="utf-8").read()
    assert src.count("def _with_contact(") == 1
    assert "_with_contact(PRIVACY_HE" in src
    assert "_with_contact(TERMS_HE" in src


def test_signing_up_says_what_you_are_agreeing_to():
    """ההסכמה יושבת ליד כפתור ההרשמה, לא בתחתית העמוד."""
    page = main.LOGIN_PAGE
    reg = page[page.index('id="reg-btn"'):]
    assert 'id="agree-note"' in reg[:300]
    for lang in ("he", "en", "es", "fr"):
        note = main.LOGIN_I18N[lang]["agree"]
        assert "{t}" in note and "{p}" in note, lang


def test_both_doors_link_to_the_terms():
    assert 'href="/terms"' in main.LOGIN_PAGE
    assert 'href="/terms"' in HTML
    assert HTML.count('"terms_link"') >= 4
