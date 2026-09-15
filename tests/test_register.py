"""הרשמה מיידית עם מייל + סיסמה (בלי קוד), מתג EMAIL_CODE_REQUIRED, איפוס ע"י מנהל."""
import json
import re

import pytest

import main
from test_auth import ADMIN, FRIEND, client, login


@pytest.fixture
def auth_on(monkeypatch, mails):
    monkeypatch.setattr(main, "AUTH_ON", True)
    monkeypatch.setattr(main, "ADMIN_EMAILS", {ADMIN})
    return mails


def _register(email, pw="goodpass1"):
    c = client()
    return c, c.post("/auth/register", json={"email": email, "password": pw})


def test_register_logs_in_and_password_works_later(auth_on, monkeypatch):
    monkeypatch.setattr(main, "NOTIFY_EMAILS", {"boss@test.com"})
    c, r = _register(" Friend@Test.com ")
    assert r.json() == {"ok": True}
    assert c.get("/matches/premier").status_code == 200
    assert any(to == "boss@test.com" and FRIEND in s for to, s, _ in auth_on)
    other = client()
    assert other.post("/auth/login", json={"email": FRIEND, "password": "goodpass1"}).status_code == 200


def test_register_rules(auth_on):
    assert _register(FRIEND, "short")[1].status_code == 400
    assert _register(FRIEND)[1].status_code == 200
    r = _register(FRIEND, "anotherpass")[1]
    assert r.status_code == 409 and r.json()["detail"] == "המייל כבר רשום — היכנס עם הסיסמה"
    # כתובת מנהל — לא בלי סיסמת המנהל (אחרת כל אחד מקבל הרשאות מנהל)
    assert _register(ADMIN)[1].status_code == 403


def test_admin_registers_only_with_admin_password(auth_on, monkeypatch):
    monkeypatch.setattr(main, "APP_PASSWORD", "owner-secret")
    c = client()
    r = c.post("/auth/register", json={"email": ADMIN, "password": "goodpass1", "admin_key": "guess"})
    assert r.status_code == 403 and r.json()["detail"] == "כתובת מנהל דורשת את סיסמת המנהל"
    r = c.post("/auth/register", json={"email": ADMIN, "password": "goodpass1", "admin_key": "owner-secret"})
    assert r.status_code == 200
    # אחרי ההרשמה: כניסה עם הסיסמה האישית — בלי סיסמת המנהל, עם הרשאות מנהל
    monkeypatch.setattr(main, "APP_PASSWORD", "")
    me = client()
    assert me.post("/auth/login", json={"email": ADMIN, "password": "goodpass1"}).status_code == 200
    assert me.get("/auth/me").json()["is_admin"] is True


def test_admin_registration_closed_without_app_password(auth_on):
    r = client().post("/auth/register", json={"email": ADMIN, "password": "goodpass1", "admin_key": ""})
    assert r.status_code == 403


def test_code_required_switch(auth_on, monkeypatch):
    monkeypatch.setattr(main, "EMAIL_CODE_REQUIRED", True)
    assert _register(FRIEND)[1].status_code == 403
    assert login(auth_on, FRIEND).get("/matches/premier").status_code == 200   # הקוד עדיין עובד


def test_blocked_cannot_register_again(auth_on):
    _register(FRIEND)
    login(auth_on, ADMIN).post(f"/admin/api/users/{FRIEND}", json={"status": "blocked"})
    assert _register(FRIEND, "newpass123")[1].status_code == 403


def test_admin_reset_then_register_again(auth_on):
    friend, _ = _register(FRIEND)
    admin = login(auth_on, ADMIN)
    users = admin.get("/admin/api/users").json()["users"]
    row = next(u for u in users if u["email"] == FRIEND)
    assert row["has_password"] is True
    assert not any("password_hash" in u or "pw_fails" in u for u in users)   # לא דולף לדפדפן
    assert admin.post(f"/admin/api/users/{FRIEND}/reset_password").json()["ok"]
    assert friend.get("/matches/premier").status_code == 401                  # נותק
    c, r = _register(FRIEND, "brandnew99")
    assert r.status_code == 200
    assert client().post("/auth/login", json={"email": FRIEND, "password": "goodpass1"}).status_code == 400
    assert client().post("/admin/api/users/ghost@test.com/reset_password").status_code == 401


def _cfg(html):
    return json.loads(re.search(r"const CFG = (\{.*?\});", html).group(1))


def test_login_page_config(auth_on, monkeypatch):
    assert _cfg(client().get("/").text) == {"code_required": False, "can_send": False}
    monkeypatch.setattr(main, "EMAIL_CODE_REQUIRED", True)
    monkeypatch.setattr(main, "BREVO_API_KEY", "k")
    monkeypatch.setattr(main, "BREVO_SENDER", "s@example.com")
    assert _cfg(client().get("/").text) == {"code_required": True, "can_send": True}
