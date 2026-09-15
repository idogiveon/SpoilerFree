"""/debug/mail: למה שליחת הקוד נכשלת — פורט חסום או סיסמה שגויה, בלי לחשוף אותה."""
import smtplib
import socket

from fastapi.testclient import TestClient

import main

PW = "abcdefghijklmnop"


class _Conn:
    def close(self):
        pass


def _setup(monkeypatch, ports_open=True, login_error=None):
    monkeypatch.setattr(main, "GMAIL_USER", "getspoilerfree@gmail.com")
    monkeypatch.setattr(main, "GMAIL_APP_PASSWORD", PW)

    def conn(addr, timeout=None):
        if not ports_open:
            raise TimeoutError()
        return _Conn()
    monkeypatch.setattr(socket, "create_connection", conn)

    class FakeSMTP:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def login(self, user, pw):
            if login_error:
                raise login_error
    monkeypatch.setattr(main.smtplib, "SMTP_SSL", FakeSMTP)


def test_blocked_ports_reported(monkeypatch):
    _setup(monkeypatch, ports_open=False)
    r = TestClient(main.app).get("/debug/mail").json()
    assert r["port_465"].startswith("blocked") and r["port_587"].startswith("blocked")
    assert "login" not in r


def test_wrong_password_reported_without_leaking_it(monkeypatch):
    _setup(monkeypatch, login_error=smtplib.SMTPAuthenticationError(535, b"bad credentials"))
    res = TestClient(main.app).get("/debug/mail")
    r = res.json()
    assert r["login"] == "rejected by Gmail: 535" and r["password_length"] == 16
    assert PW not in res.text


def test_ok(monkeypatch):
    _setup(monkeypatch)
    assert TestClient(main.app).get("/debug/mail").json()["login"] == "ok"


def test_admin_only(monkeypatch):
    monkeypatch.setattr(main, "AUTH_ON", True)
    assert TestClient(main.app).get("/debug/mail").status_code == 401
