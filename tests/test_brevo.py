"""שליחת קודים דרך Brevo (HTTPS) — Render החינמי חוסם SMTP, Google חוסמת Gmail חדש."""
import json

from fastapi.testclient import TestClient

import main


class R:
    def __init__(self, code, body=None):
        self.status_code, self._body = code, body or {}
        self.text = json.dumps(self._body)

    def json(self):
        return self._body


def _cfg(monkeypatch):
    monkeypatch.setattr(main, "BREVO_API_KEY", "xkeysib-test")
    monkeypatch.setattr(main, "BREVO_SENDER", "owner@example.com")


def test_sends_through_brevo(monkeypatch):
    _cfg(monkeypatch)
    calls = []
    monkeypatch.setattr(main.requests, "post", lambda url, **k: calls.append((url, k)) or R(201, {"messageId": "m"}))
    assert main.send_email("friend@test.com", "קוד כניסה ל-SpoilerFree: 123456", "הקוד שלך: 123456")
    url, k = calls[0]
    assert url == "https://api.brevo.com/v3/smtp/email"
    assert k["headers"]["api-key"] == "xkeysib-test"
    assert k["json"] == {"sender": {"name": "SpoilerFree", "email": "owner@example.com"},
                         "to": [{"email": "friend@test.com"}],
                         "subject": "קוד כניסה ל-SpoilerFree: 123456", "textContent": "הקוד שלך: 123456"}


def test_brevo_error_is_a_failed_send(monkeypatch):
    _cfg(monkeypatch)
    monkeypatch.setattr(main.requests, "post", lambda url, **k: R(401, {"message": "Key not found"}))
    assert main.send_email("friend@test.com", "s", "b") is False


def test_brevo_wins_over_gmail(monkeypatch):
    _cfg(monkeypatch)
    monkeypatch.setattr(main, "GMAIL_USER", "old@gmail.com")
    monkeypatch.setattr(main, "GMAIL_APP_PASSWORD", "abcdefghijklmnop")

    def boom(*a, **k):
        raise AssertionError("SMTP must not be used when Brevo is set")
    monkeypatch.setattr(main.smtplib, "SMTP_SSL", boom)
    monkeypatch.setattr(main.requests, "post", lambda url, **k: R(201))
    assert main.send_email("friend@test.com", "s", "b")


def test_code_request_uses_brevo_end_to_end(monkeypatch):
    _cfg(monkeypatch)
    monkeypatch.setattr(main, "AUTH_ON", True)
    sent = []
    monkeypatch.setattr(main.requests, "post", lambda url, **k: sent.append(k["json"]) or R(201))
    r = TestClient(main.app).post("/auth/request_code", json={"email": "friend@test.com"})
    assert r.json() == {"status": "code_sent"} and sent[0]["to"] == [{"email": "friend@test.com"}]


def test_debug_mail_reports_brevo(monkeypatch):
    _cfg(monkeypatch)
    import socket
    monkeypatch.setattr(socket, "create_connection", lambda *a, **k: (_ for _ in ()).throw(TimeoutError()))
    monkeypatch.setattr(main.requests, "get", lambda url, **k: R(200, {"email": "owner@example.com"}))
    res = TestClient(main.app).get("/debug/mail")
    assert res.json()["brevo"] == {"key_set": True, "sender": "owner@example.com",
                                   "active": True, "key_ok": True}
    assert "xkeysib-test" not in res.text
