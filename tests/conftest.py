"""בדיקות SpoilerFree: DB מבודד לכל בדיקה, בלי רשת, בלי מיילים.

הרצה: venv/bin/pytest -q   (רץ גם אוטומטית ב-GitHub Actions על כל PR)
"""
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# לפני import main: בלי Turso, בלי מפתחות, בלי כניסה (כל בדיקה מפעילה מה שצריך)
for _k in ("TURSO_DATABASE_URL", "TURSO_AUTH_TOKEN", "APP_PASSWORD", "GMAIL_USER",
           "GMAIL_APP_PASSWORD", "ADMIN_EMAILS", "YOUTUBE_API_KEY",
           "FOOTBALL_DATA_KEY", "AUTH_DEV", "BREVO_API_KEY", "BREVO_SENDER",
           "GMAIL_CLIENT_ID", "GMAIL_CLIENT_SECRET", "GMAIL_REFRESH_TOKEN"):
    os.environ[_k] = ""
os.chdir(ROOT)  # index.html / static/ נטענים בנתיב יחסי

import main  # noqa: E402


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.chdir(ROOT)
    monkeypatch.setattr(main, "DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setattr(main, "TURSO_DATABASE_URL", "")
    monkeypatch.setattr(main, "YOUTUBE_API_KEY", "")
    monkeypatch.setattr(main, "AUTH_ON", False)
    monkeypatch.setattr(main, "APP_PASSWORD", "")
    monkeypatch.setattr(main, "ADMIN_EMAILS", set())
    main._rss_cache.clear()
    main.init_db()
    yield


@pytest.fixture
def mails(monkeypatch):
    """לוכד מיילים במקום לשלוח: [(to, subject, body)]."""
    sent = []

    def fake_send(to, subject, body):
        sent.append((to, subject, body))
        return True

    monkeypatch.setattr(main, "send_email", fake_send)
    return sent


@pytest.fixture
def db():
    conn = main.get_db()
    yield conn
    conn.close()
