"""הכתובת הראשית, Cookie settings, וניהול חשבון (פרטים + מחיקה)."""
import pytest

import main
from test_auth import ADMIN, FRIEND, client, login


@pytest.fixture
def auth_on(monkeypatch, mails):
    monkeypatch.setattr(main, "AUTH_ON", True)
    monkeypatch.setattr(main, "ADMIN_EMAILS", {ADMIN})
    return mails


def test_root_is_login_page_for_anonymous(auth_on):
    r = client().get("/")
    assert r.status_code == 200 and "שלח קוד" in r.text


def test_root_serves_app_when_logged_in_and_app_path_still_works(auth_on):
    admin = login(auth_on, ADMIN)
    assert admin.get("/").headers.get("X-SF-App") == "1"
    assert admin.get("/app").headers.get("X-SF-App") == "1"


def test_health_is_public_json():
    assert client().get("/health").json()["status"].startswith("SpoilerFree")


def test_login_page_has_cookie_settings_not_privacy_note(auth_on):
    html = client().get("/").text
    assert "Cookie settings" in html
    assert "מה נשמר" not in html


def test_cookies_text_is_public_and_mentions_usage_and_deletion():
    html = client().get("/cookies").text
    assert "נתוני שימוש" in html and "חשבון" in html and "למחוק" in html


def _approve_friend(mails):
    return login(mails, FRIEND)          # בלי אישור מנהל — הקוד מאמת את המייל


def test_account_details(auth_on):
    friend = _approve_friend(auth_on)
    a = friend.get("/auth/account").json()
    assert a["email"] == FRIEND and a["login_count"] == 1 and a["created_at"]


def test_delete_requires_typing_email(auth_on):
    friend = _approve_friend(auth_on)
    r = friend.post("/auth/delete_account", json={"confirm": "wrong@x.com"})
    assert r.status_code == 400
    assert friend.get("/matches/premier").status_code == 200   # עדיין מחובר


def test_delete_removes_account_and_data(auth_on):
    friend = _approve_friend(auth_on)
    friend.post("/events", json={"type": "app_open"})
    assert friend.post("/auth/delete_account", json={"confirm": " Friend@Test.com "}).json()["ok"]
    assert friend.get("/matches/premier").status_code == 401
    conn = main.get_db()
    for table in ("users", "sessions", "events", "login_codes"):
        n = conn.execute(f"SELECT COUNT(*) AS c FROM {table} WHERE email=?", (FRIEND,)).fetchone()["c"]
        assert n == 0, table
    conn.close()
    # מי שנמחק נרשם מחדש כמו משתמש חדש (קוד → סיסמה חדשה)
    assert login(auth_on, FRIEND).get("/auth/account").json()["login_count"] == 1
