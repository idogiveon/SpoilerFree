"""שפות: לכל שפה אותם מפתחות, לכל טקסט בדף ולכל ליגה יש תרגום."""
import json
import re
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

import main

LANGS = ("he", "en", "es", "fr")


def _app_i18n():
    html = open("index.html", encoding="utf-8").read()
    block = re.search(r'<script type="application/json" id="i18n">(.*?)</script>', html, re.S).group(1)
    return json.loads(block), html


def test_every_language_has_all_keys():
    i18n, _ = _app_i18n()
    assert set(i18n) == set(LANGS)
    for lang in LANGS:
        assert set(i18n[lang]) == set(i18n["he"]), lang
        assert len(i18n[lang]["days"]) == 7


def test_every_static_text_and_league_is_translated():
    i18n, html = _app_i18n()
    for key in set(re.findall(r'data-i18n="([a-z_]+)"', html)):
        assert key in i18n["he"], key
    for league in main.LEAGUES:
        assert f"lg_{league}" in i18n["he"], league


def test_every_t_call_in_script_has_a_key():
    i18n, html = _app_i18n()
    used = set(re.findall(r"\bt\('([a-z_]+)'", html)) - {"diag_", "lg_", "reason_"}
    missing = [k for k in used if k not in i18n["he"]]
    assert not missing, missing


def test_login_page_languages_match():
    for lang in LANGS:
        assert set(main.LOGIN_I18N[lang]) == set(main.LOGIN_I18N["he"]), lang
    page = main.render_login_page()
    assert "__LOGIN_I18N__" not in page and '"Send code"' in page


def test_server_error_texts_are_mapped_in_login_i18n():
    """הודעות השגיאה של השרת זהות לערכי err_* בעברית — אחרת לא יתורגמו."""
    src = open("main.py", encoding="utf-8").read()
    for key, text in main.LOGIN_I18N["he"].items():
        if key.startswith("err_"):
            assert f'"{text}"' in src, key


def test_cookies_text_by_language():
    c = TestClient(main.app)
    assert "Cookie & privacy settings" in c.get("/cookies?lang=en").text
    assert "Configuración de cookies" in c.get("/cookies?lang=es").text
    assert "Paramètres des cookies" in c.get("/cookies?lang=fr").text
    assert "הגדרות עוגיות" in c.get("/cookies").text
    assert "הגדרות עוגיות" in c.get("/cookies?lang=xx").text


def test_code_email_in_users_language(monkeypatch, mails):
    monkeypatch.setattr(main, "AUTH_ON", True)
    monkeypatch.setattr(main, "ADMIN_EMAILS", {"admin@test.com"})
    TestClient(main.app).post("/auth/request_code", json={"email": "admin@test.com", "lang": "en"})
    to, subject, body = mails[-1]
    assert subject.startswith("Your SpoilerFree login code: ") and re.search(r"\d{6}$", subject)
    assert "Valid for" in body


def test_highlight_messages_have_reason_codes(db):
    now = datetime.now(timezone.utc)
    for mid, when in (("future", now + timedelta(days=2)), ("stale", now - timedelta(hours=3))):
        db.execute("INSERT INTO matches (id, league_key, home_team, away_team, date_utc, time_utc, status) "
                   "VALUES (?, 'laliga', 'A', 'B', ?, ?, 'SCHEDULED')",
                   (mid, when.strftime("%Y-%m-%d"), when.strftime("%H:%M:%S")))
    db.commit()
    c = TestClient(main.app)
    assert c.get("/highlights/future").json()["reason_code"] == "not_over"
    assert c.get("/highlights/stale").json()["reason_code"] == "stale"


# ── ביקורת מוצר (26.9.26): מחרוזות גלויות שנשארו מחוץ ל-i18n ─────────
HTML = open("index.html", encoding="utf-8").read()
def test_the_first_paint_of_every_visit_is_translated():
    """`<div class="loading">טוען משחקים</div>` — מה שכל משתמש רואה
    ראשון, בכל שפה."""
    assert '<div class="loading" data-i18n="loading_matches">' in HTML
    assert 'class="loading">טוען' not in HTML


def test_the_gear_button_has_a_name_in_every_language():
    """הכפתור היחיד שמחזיר ממסך הפתיחה — היה עם title בעברית קשיחה
    ובלי aria-label."""
    assert 'data-i18n-title="leagues_screen"' in HTML
    assert "el.setAttribute('aria-label', el.title)" in HTML


def test_the_delete_error_does_not_leak_a_hebrew_detail():
    """שאר האפליקציה שולחת detail לקונסול ומציגה טקסט מתורגם."""
    assert "j.detail || t('delete_failed')" not in HTML
    assert "console.debug('delete_account:', j.detail)" in HTML


def test_the_youtube_legend_is_not_shown_when_there_is_no_arrow():
    """↗ נוסף לכפתור רק כשהטמעה חסומה. במופע הפרטי אין ↗ בכלל, והמקרא
    הסביר סמל שאינו על המסך."""
    assert "anyExternal ? `<div class=\"shield-note\">" in HTML
    assert "t('opened_on_youtube')" in HTML       # מסלול הכשל: הודעה, לא מקרא


def test_the_same_key_does_not_promise_different_things():
    """no_source_hint בעברית היה TODO של המתחזק ("צריך למצוא את הערוץ
    הרשמי"), ו-no_matches_day_hint נתן הנחיה רק בעברית."""
    assert "צריך למצוא את הערוץ הרשמי" not in HTML
    hints = re.findall(r'"no_matches_day_hint": "(.*?)"', HTML)
    assert len(hints) == 4
    assert all("—" in h for h in hints), hints


def test_the_pwa_description_follows_the_user_language():
    """מחרוזת גלויה שנמצאה מחוץ ל-i18n: ההתקנה הציגה תיאור בעברית לכל
    מי שהתקין."""
    from fastapi.testclient import TestClient
    c = TestClient(main.app)
    assert c.get("/manifest.webmanifest?lang=fr").json()["lang"] == "fr"
    assert c.get("/manifest.webmanifest").json()["dir"] == "rtl"
    assert set(main.MANIFEST_I18N) == {"he", "en", "es", "fr"}
    assert "manifest.webmanifest?lang=" in HTML
