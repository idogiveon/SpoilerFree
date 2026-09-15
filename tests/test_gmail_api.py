"""שליחת קודים דרך Gmail API (HTTPS) — Render החינמי חוסם SMTP."""
import base64
import json
from urllib.parse import parse_qs, unquote, urlparse

from fastapi.testclient import TestClient

import main


class R:
    def __init__(self, code, body):
        self.status_code, self._body, self.text = code, body, json.dumps(body)

    def json(self):
        return self._body


def _cfg(monkeypatch):
    monkeypatch.setattr(main, "GMAIL_CLIENT_ID", "cid")
    monkeypatch.setattr(main, "GMAIL_CLIENT_SECRET", "csecret")
    monkeypatch.setattr(main, "_gmail_token", {"value": None, "exp": 0.0})


def _no_smtp(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("SMTP must not be used when the API is connected")
    monkeypatch.setattr(main.smtplib, "SMTP_SSL", boom)


def test_sends_through_api_and_caches_token(monkeypatch):
    _cfg(monkeypatch)
    _no_smtp(monkeypatch)
    main._meta_set("gmail_refresh_token", "rt1")
    main._meta_set("gmail_sender", "getspoilerfree@gmail.com")
    calls = []

    def post(url, **k):
        calls.append((url, k))
        if "oauth2" in url:
            return R(200, {"access_token": "at1", "expires_in": 3600})
        return R(200, {"id": "m1"})
    monkeypatch.setattr(main.requests, "post", post)

    assert main.send_email("friend@test.com", "קוד כניסה: 123456", "גוף")
    assert main.send_email("friend@test.com", "קוד כניסה: 654321", "גוף")
    assert sum("oauth2" in u for u, _ in calls) == 1                   # access token נשמר
    sends = [k for u, k in calls if "gmail.googleapis.com" in u]
    assert len(sends) == 2 and sends[0]["headers"]["Authorization"] == "Bearer at1"
    raw = base64.urlsafe_b64decode(sends[0]["json"]["raw"]).decode()
    assert "To: friend@test.com" in raw and "getspoilerfree@gmail.com" in raw


def test_revoked_connection_fails_cleanly(monkeypatch):
    _cfg(monkeypatch)
    _no_smtp(monkeypatch)
    main._meta_set("gmail_refresh_token", "rt-old")
    monkeypatch.setattr(main.requests, "post", lambda url, **k: R(400, {"error": "invalid_grant"}))
    assert main.send_email("friend@test.com", "s", "b") is False


def test_connect_then_callback_stores_token(monkeypatch):
    _cfg(monkeypatch)
    c = TestClient(main.app)
    loc = c.get("/admin/gmail/connect", follow_redirects=False).headers["location"]
    q = parse_qs(urlparse(loc).query)
    assert loc.startswith("https://accounts.google.com/")
    assert "gmail.send" in unquote(q["scope"][0]) and q["access_type"] == ["offline"]
    assert q["redirect_uri"] == [main.APP_URL + "/admin/gmail/callback"]
    state = q["state"][0]

    assert c.get("/admin/gmail/callback", params={"code": "x", "state": "forged"}).status_code == 400
    payload = base64.urlsafe_b64encode(json.dumps({"email": "getspoilerfree@gmail.com"}).encode()).decode().rstrip("=")
    monkeypatch.setattr(main.requests, "post", lambda url, **k: R(200, {
        "refresh_token": "rt9", "access_token": "a", "id_token": f"h.{payload}.s"}))
    r = c.get("/admin/gmail/callback", params={"code": "x", "state": state})
    assert r.status_code == 200 and "getspoilerfree@gmail.com" in r.text
    assert "rt9" not in r.text                                         # לא מוצג
    assert main._meta_get("gmail_refresh_token") == "rt9"
    assert main._meta_get("gmail_sender") == "getspoilerfree@gmail.com"
    # ה-state חד-פעמי
    assert c.get("/admin/gmail/callback", params={"code": "x", "state": state}).status_code == 400


def test_gmail_endpoints_are_admin_only(monkeypatch):
    _cfg(monkeypatch)
    monkeypatch.setattr(main, "AUTH_ON", True)
    c = TestClient(main.app)
    assert c.get("/admin/gmail/connect", follow_redirects=False).status_code == 401
    assert c.get("/admin/gmail/callback", params={"code": "x", "state": "y"}).status_code == 401


def test_debug_mail_reports_api(monkeypatch):
    _cfg(monkeypatch)
    main._meta_set("gmail_refresh_token", "rt1")
    monkeypatch.setattr(main.requests, "post", lambda url, **k: R(200, {"access_token": "at", "expires_in": 3600}))
    import socket
    monkeypatch.setattr(socket, "create_connection", lambda *a, **k: (_ for _ in ()).throw(TimeoutError()))
    api = TestClient(main.app).get("/debug/mail").json()["gmail_api"]
    assert api == {"client_set": True, "connected": True, "sender": None, "token_ok": True}
