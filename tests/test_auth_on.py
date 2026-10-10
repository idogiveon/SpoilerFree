"""מתי הכניסה חובה — ומה נשאר סגור גם כשהיא לא.

עד 10.10.26 האתר ב-Render היה נעול תמיד. הבעלים ביקש שהדבר הראשון
שמשתמש חדש נתקל בו לא יהיה עמוד הרשמה, ולכן הכניסה חובה רק כשהאתר
באמת סגור: הכתובת הפרטית (ALLOWED_EMAILS) או REQUIRE_LOGIN=1.
"""
import os
import subprocess
import sys

import pytest
from fastapi.testclient import TestClient

import main

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _auth_on(**env):
    clean = {k: v for k, v in os.environ.items()
             if k not in ("APP_PASSWORD", "GMAIL_USER", "BREVO_API_KEY", "GMAIL_CLIENT_ID",
                          "AUTH_DEV", "RENDER", "TURSO_DATABASE_URL",
                          "ALLOWED_EMAILS", "REQUIRE_LOGIN")}
    out = subprocess.run([sys.executable, "-c", "import main; print(main.AUTH_ON)"],
                         cwd=ROOT, env={**clean, **env}, capture_output=True, text=True)
    return out.stdout.strip().splitlines()[-1]


def test_the_public_site_is_open():
    """זו הבקשה עצמה: מבקר חדש מגיע לאתר, לא לעמוד הרשמה."""
    assert _auth_on(RENDER="true") == "False"


def test_the_private_address_stays_locked():
    """הכתובת עם הנגן המוטמע — הסיכון המשפטי היחיד — נשארת סגורה."""
    assert _auth_on(RENDER="true", ALLOWED_EMAILS="owner@example.com") == "True"


def test_login_can_be_demanded_explicitly():
    assert _auth_on(RENDER="true", REQUIRE_LOGIN="1") == "True"


def test_local_dev_without_secrets_is_open():
    assert _auth_on() == "False"


# ── מה שחייב להישאר סגור גם כשהאתר פתוח ──────────────────────────────
@pytest.fixture
def open_site(monkeypatch):
    monkeypatch.setattr(main, "AUTH_ON", False)
    monkeypatch.setattr(main, "ALLOWED_EMAILS", set())
    monkeypatch.setattr(main, "ADMIN_EMAILS", {"owner@example.com"})
    return TestClient(main.app)


def test_the_admin_page_is_not_open_to_everyone(open_site):
    """`if not AUTH_ON: return` ב-require_admin היה פותח את רשימת
    המשתמשים ואת נתיבי הדיבאג לכל אנונימי ברגע שהכניסה הפסיקה להיות
    חובה. זה הפטור שצומצם לפיתוח מקומי בלבד."""
    for path in ("/admin/api/users", "/debug/mail", "/debug/timing", "/debug/db"):
        assert open_site.get(path).status_code in (401, 403), path
    # העמוד עצמו מפנה הביתה — לא מגיש את הטבלה
    page = open_site.get("/admin/users")
    assert "SPOILERFREE — משתמשים" not in page.text


def test_an_anonymous_visitor_is_not_an_admin(open_site, db):
    """`is_admin: ... or not AUTH_ON` היה הופך כל מבקר למנהל בעיני
    הלקוח, ומציג לו את הקישור לעמוד הניהול."""
    me = open_site.get("/auth/me").json()
    assert me["is_admin"] is False
    assert me["email"] is None


def test_the_app_itself_is_served_without_a_login(open_site, db):
    r = open_site.get("/")
    assert r.status_code == 200
    assert r.headers.get("X-SF-App") == "1"      # האפליקציה, לא מסך הכניסה


def test_an_existing_user_still_has_a_way_in(open_site):
    r = open_site.get("/login")
    assert r.status_code == 200
    assert 'id="step-login"' in r.text
