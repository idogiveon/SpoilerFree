"""כניסה: קוד למייל בפעם הראשונה → סיסמה; אחר כך סיסמה או קוד. הרשאות, מעקב, חסימה."""
import re

import pytest
from fastapi.testclient import TestClient

import main

ADMIN, FRIEND = "admin@test.com", "friend@test.com"


@pytest.fixture
def auth_on(monkeypatch, mails):
    monkeypatch.setattr(main, "AUTH_ON", True)
    monkeypatch.setattr(main, "ADMIN_EMAILS", {ADMIN})
    return mails


def client():
    return TestClient(main.app)


def last_code(mails, email):
    for to, subject, _ in reversed(mails):
        m = re.search(r"(\d{6})$", subject)
        if to == email and m:
            return m.group(1)
    return None


def login(mails, email):
    c = client()
    assert c.post("/auth/request_code", json={"email": email}).json()["status"] == "code_sent"
    r = c.post("/auth/verify", json={"email": email, "code": last_code(mails, email)})
    assert r.status_code == 200, r.text
    return c


def test_anonymous_gets_login_page_and_401(auth_on):
    c = client()
    r = c.get("/app")
    assert "שלח קוד" in r.text and "X-SF-App" not in r.headers
    assert 'id="legacy-link"' not in r.text         # אין APP_PASSWORD — אין כפתור סיסמה
    assert c.get("/matches/premier").status_code == 401
    assert c.post("/auth/request_code", json={"email": "nope"}).status_code == 400


def test_first_login_code_then_set_password_then_password_login(auth_on, monkeypatch):
    mails = auth_on
    monkeypatch.setattr(main, "NOTIFY_EMAILS", {"boss@test.com"})
    friend = client()
    assert friend.post("/auth/request_code", json={"email": " Friend@Test.com"}).json()["status"] == "code_sent"
    assert not any(to == "boss@test.com" for to, _, _ in mails)      # עוד לא אומת — אין הודעה
    r = friend.post("/auth/verify", json={"email": FRIEND, "code": last_code(mails, FRIEND)})
    assert r.json() == {"ok": True, "need_password": True}
    assert any(to == "boss@test.com" and FRIEND in s for to, s, _ in mails), "registration not reported"
    assert friend.get("/matches/premier").status_code == 200       # בלי אישור מנהל

    assert friend.post("/auth/set_password", json={"password": "short"}).status_code == 400
    assert friend.post("/auth/set_password", json={"password": "goodpass1"}).json()["ok"]
    conn = main.get_db()
    stored = conn.execute("SELECT password_hash FROM users WHERE email=?", (FRIEND,)).fetchone()[0]
    conn.close()
    assert "goodpass1" not in stored and stored.startswith("pbkdf2$")

    c = client()
    assert c.post("/auth/login", json={"email": FRIEND, "password": "wrongpass"}).status_code == 400
    assert c.get("/matches/premier").status_code == 401
    assert c.post("/auth/login", json={"email": FRIEND.upper(), "password": "goodpass1"}).json()["ok"]
    assert c.get("/matches/premier").status_code == 200
    # קוד עדיין עובד, ולא מבקש סיסמה שוב; הרשמה נשלחת פעם אחת בלבד
    c2 = client()
    c2.post("/auth/request_code", json={"email": FRIEND})
    assert c2.post("/auth/verify", json={"email": FRIEND, "code": last_code(mails, FRIEND)}).json() == \
        {"ok": True, "need_password": False}
    assert sum(1 for to, s, _ in mails if to == "boss@test.com") == 1


def test_password_change_only_right_after_code_login(auth_on):
    mails = auth_on
    c = login(mails, FRIEND)
    assert c.post("/auth/set_password", json={"password": "firstpass"}).json()["ok"]
    # אחרי שנקבעה — החלפה רק בחלון שאחרי כניסה עם קוד ("שכחתי סיסמה")
    assert c.post("/auth/set_password", json={"password": "hijacked1"}).status_code == 403
    conn = main.get_db()
    conn.execute("DELETE FROM login_codes")
    conn.commit()
    conn.close()
    c = login(mails, FRIEND)
    assert c.post("/auth/set_password", json={"password": "secondpass"}).json()["ok"]
    assert client().post("/auth/login", json={"email": FRIEND, "password": "firstpass"}).status_code == 400
    assert client().post("/auth/login", json={"email": FRIEND, "password": "secondpass"}).status_code == 200


def test_password_lockout_and_unknown_email(auth_on):
    c = login(auth_on, FRIEND)
    c.post("/auth/set_password", json={"password": "goodpass1"})
    for _ in range(main.PW_MAX_FAILS):
        assert client().post("/auth/login", json={"email": FRIEND, "password": "nope-nope"}).status_code == 400
    assert client().post("/auth/login", json={"email": FRIEND, "password": "goodpass1"}).status_code == 429
    r = client().post("/auth/login", json={"email": "ghost@test.com", "password": "whatever1"})
    assert r.status_code == 400 and r.json()["detail"] == "מייל או סיסמה שגויים"


def test_old_pending_user_gets_in_with_code(auth_on):
    conn = main.get_db()
    conn.execute("INSERT INTO users (email, status, created_at) VALUES (?, 'pending', '2026-09-13')", (FRIEND,))
    conn.commit()
    conn.close()
    assert login(auth_on, FRIEND).get("/matches/premier").status_code == 200


def test_permissions_tracking_and_block(auth_on):
    mails = auth_on
    admin = login(mails, ADMIN)
    assert admin.get("/auth/me").json() == {"auth_on": True, "email": ADMIN, "is_admin": True,
                                            "legacy": False, "onboarded": False,
                                            "private": False, "embed": main.EMBED_IN_APP}
    assert admin.get("/app").headers.get("X-SF-App") == "1"
    assert admin.get("/debug/quota").status_code == 200

    friend = login(mails, FRIEND)
    assert friend.get("/matches/premier").status_code == 200
    assert friend.get("/debug/db").status_code == 403
    assert friend.get("/admin/api/users").status_code == 403
    r = friend.get("/admin/users", follow_redirects=False)
    assert r.status_code in (302, 307) and r.headers["location"] == "/"
    for ev in ({"type": "app_open"}, {"type": "league_view", "league": "ucl"},
               {"type": "match_open", "league": "ucl", "match_id": "1"},
               {"type": "highlight_play", "match_id": "1", "detail": "v"}):
        assert friend.post("/events", json=ev).json()["ok"]
    assert friend.post("/events", json={"type": "hack"}).status_code == 400
    u = next(x for x in admin.get("/admin/api/users").json()["users"] if x["email"] == FRIEND)
    assert (u["login_count"], u["match_open"], u["highlight_play"], u["top_leagues"]) == (1, 1, 1, ["ucl"])

    friend.post("/auth/set_password", json={"password": "goodpass1"})
    admin.post(f"/admin/api/users/{FRIEND}", json={"status": "blocked"})
    assert friend.get("/matches/premier").status_code == 401
    assert client().post("/auth/request_code", json={"email": FRIEND}).status_code == 403
    assert client().post("/auth/login", json={"email": FRIEND, "password": "goodpass1"}).status_code == 403


def test_code_single_use_and_attempt_cap(auth_on):
    mails = auth_on
    c = client()
    c.post("/auth/request_code", json={"email": ADMIN})
    code = last_code(mails, ADMIN)
    wrong = "000000" if code != "000000" else "111111"
    assert c.post("/auth/verify", json={"email": ADMIN, "code": wrong}).status_code == 400
    assert c.post("/auth/verify", json={"email": ADMIN, "code": code}).status_code == 200
    assert c.post("/auth/verify", json={"email": ADMIN, "code": code}).status_code == 400

    c2 = client()
    conn = main.get_db()
    conn.execute("DELETE FROM login_codes")
    conn.commit()
    conn.close()
    c2.post("/auth/request_code", json={"email": ADMIN})
    code = last_code(mails, ADMIN)
    wrong = "000000" if code != "000000" else "111111"
    for _ in range(5):
        c2.post("/auth/verify", json={"email": ADMIN, "code": wrong})
    assert c2.post("/auth/verify", json={"email": ADMIN, "code": code}).status_code == 429


def test_resend_within_a_minute_reuses_code(auth_on):
    mails = auth_on
    c = client()
    c.post("/auth/request_code", json={"email": ADMIN})
    c.post("/auth/request_code", json={"email": ADMIN})
    assert sum(1 for to, s, _ in mails if to == ADMIN and "קוד" in s) == 1


def test_logout(auth_on):
    admin = login(auth_on, ADMIN)
    admin.post("/auth/logout")
    assert admin.get("/matches/premier").status_code == 401


def test_legacy_password_still_admin(auth_on, monkeypatch):
    monkeypatch.setattr(main, "APP_PASSWORD", "pw")
    c = client()
    assert "כניסה עם סיסמה" in c.get("/app").text
    c.post("/login", json={"password": "pw"})
    assert c.get("/matches/premier").status_code == 200
    assert c.get("/debug/quota").status_code == 200
    assert c.post("/events", json={"type": "app_open"}).json().get("skipped")


def test_send_failure_is_reported(monkeypatch):
    monkeypatch.setattr(main, "AUTH_ON", True)
    monkeypatch.setattr(main, "ADMIN_EMAILS", {ADMIN})
    monkeypatch.setattr(main, "send_email", lambda *a: False)
    r = client().post("/auth/request_code", json={"email": ADMIN})
    assert r.status_code == 503
