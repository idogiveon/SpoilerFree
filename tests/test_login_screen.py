"""מסך הכניסה אחרי הפידבק החיצוני (19.9.26): הרשמה כברירת מחדל,
"שכחתי סיסמה" שאומר למי לכתוב, ושפה לפי המכשיר."""
from fastapi.testclient import TestClient

import main

HTML = open("index.html", encoding="utf-8").read()


def _page():
    return main.render_login_page()


def test_signup_is_the_first_screen_with_a_way_back_to_login():
    page = _page()
    assert "else { show('step-register'); $('reg-email').focus(); }" in page
    # מי שכבר רשום — לחיצה אחת
    assert 'onclick="show(\'step-login\')" data-i18n="have_account"' in page
    for lang in ("he", "en", "es", "fr"):
        assert main.LOGIN_I18N[lang]["have_account"], lang


def test_signup_first_only_when_a_code_is_not_required():
    """כשהרשמה דורשת קוד למייל, מסך ההרשמה לא רלוונטי."""
    assert "if (CFG.code_required) { $('email').focus(); }" in _page()


def test_forgot_password_is_a_button_that_says_who_to_write_to():
    page = _page()
    assert 'id="forgot-admin" data-i18n="forgot_admin" onclick="askReset()"' in page
    assert "async function askReset()" in page
    assert "'mailto:'" in page or "mailto:" in page


def test_the_contact_address_is_not_in_the_page_source():
    """כתובת בקוד המקור = מזון לסורקי ספאם. היא נמסרת רק בלחיצה."""
    main.ADMIN_EMAILS.add("someone@example.com")
    try:
        assert "someone@example.com" not in _page()
        got = TestClient(main.app).get("/auth/contact").json()
        assert got["email"] == "someone@example.com"
    finally:
        main.ADMIN_EMAILS.discard("someone@example.com")


def test_language_follows_the_device_when_nothing_was_chosen():
    """הופץ לחו"ל: מכשיר בצרפתית מקבל צרפתית, מכשיר בשפה שאין לנו — אנגלית."""
    for src in (_page(), HTML):
        assert "function deviceLang()" in src
        assert "navigator.languages" in src
        assert "if (code === 'iw') return 'he';" in src      # קוד ישן לעברית
        assert "return 'en';" in src                          # לא עברית כברירת מחדל
        assert "localStorage.getItem('sf:lang') || 'he'" not in src


def test_what_is_kept_is_stated_in_every_language():
    for lang in ("he", "en", "es", "fr"):
        note = main.LOGIN_I18N[lang]["privacy_note"]
        assert len(note) > 40, lang
