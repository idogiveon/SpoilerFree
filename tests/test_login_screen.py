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


# ── ביקורת מוצר (26.9.26): מה שמבקר חדש רואה במסך הכניסה ─────────────
def test_the_legal_links_are_not_bare_flex_items_beside_the_card():
    """הכלל היה `button.cookie-link{position:fixed}` בלבד, ושני ה-<a>
    נשארו ילדים ישירים של body — שהוא display:flex. כלומר שני קישורים
    כחולים 16px *לצד* כרטיס הכניסה, שדוחקים אותו. הבעלים לא רואה את זה:
    יש לו קוקי ל-90 יום."""
    page = main.LOGIN_PAGE
    assert ".legal{position:fixed" in page
    assert ".cookie-link{width:auto" in page       # לא רק button
    legal = page[page.index('<div class="legal">'):]
    legal = legal[:legal.index("</div>")]
    for el in ('id="privacy-link"', 'id="terms-link"', 'onclick="openCookies()"'):
        assert el in legal, el


def test_the_cookie_button_is_translated_in_both_doors():
    """הכפתור היה "Cookie settings" קשיח בשני המקומות, בזמן שהמפתח
    cookie_settings קיים בארבע השפות."""
    assert 'data-i18n="cookie_settings"' in main.LOGIN_PAGE
    html = open("index.html", encoding="utf-8").read()
    assert html.count('data-i18n="cookie_settings"') == 2      # ☰ והפוטר
    assert "Cookie settings</button>" not in html


def test_the_hebrew_server_messages_the_login_screen_shows_are_translated():
    """serverMsg מתרגם רק detail שזהה לערך של מפתח err_*. שלוש ההודעות
    האלה יוצאות מהשרת בעברית לכל משתמש, בכל שפה — וביניהן הפנים של תקרת
    ההרשמה ושל הכתובת הסגורה."""
    src = open("main.py", encoding="utf-8").read()
    for detail in ("האתר הזה סגור", "יותר מדי בקשות — נסה שוב בעוד שעה",
                   "אין חשבון אישי"):
        assert f'"{detail}"' in src, detail
        keys = [k for k, v in main.LOGIN_I18N["he"].items()
                if k.startswith("err_") and v == detail]
        assert len(keys) == 1, detail
        for lang in ("en", "es", "fr"):
            other = main.LOGIN_I18N[lang][keys[0]]
            assert other and other != detail, (lang, detail)


def test_choosing_a_password_has_a_way_out():
    """המשתמש כבר מחובר בשלב הזה, ולא היה לו שום מסלול חוץ מרענון ידני."""
    step = main.LOGIN_PAGE[main.LOGIN_PAGE.index('id="step-setpw"'):]
    step = step[:step.index("</div>")]
    assert 'data-i18n="skip_pw"' in step


def test_the_spanish_and_french_reader_is_told_the_document_is_in_english():
    from fastapi.testclient import TestClient
    c = TestClient(main.app)
    assert "solo está disponible en inglés" in c.get("/terms?lang=es").text
    assert "n'est disponible qu'en anglais" in c.get("/privacy?lang=fr").text
    assert "only available" not in c.get("/terms?lang=en").text
