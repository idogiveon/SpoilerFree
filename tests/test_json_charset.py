"""עברית בתשובות JSON — ג'יבריש בפתיחה ישירה בדפדפן.

מצילום מסך (2.10.26): פתיחת /debug/match בספארי החזירה
{"detail":"× ×"×¨×©×ª ×"×ª×—×'×¨×•×ª"} — כלומר "נדרשת התחברות" ב-UTF-8
שנקרא כ-Latin-1. הסיבה: Starlette מחזיר application/json בלי charset,
ו-fetch יודע לפי התקן שזה UTF-8 — אבל ניווט ישיר לא.
"""
from fastapi.testclient import TestClient

import main

CT = "application/json; charset=utf-8"


def _client():
    return TestClient(main.app)


def test_a_normal_answer_declares_utf8(db):
    assert _client().get("/matches/israel").headers["content-type"] == CT


def test_an_error_declares_it_too(monkeypatch):
    """דווקא השגיאות הן אלה שמישהו פותח ישירות בדפדפן."""
    monkeypatch.setattr(main, "AUTH_ON", True)
    r = _client().get("/debug/match?q=x")
    assert r.status_code == 401
    assert r.headers["content-type"] == CT
    assert r.json()["detail"] == "נדרשת התחברות"
    assert "נדרשת".encode("utf-8") in r.content


def test_the_detail_still_matches_what_the_login_page_translates(monkeypatch):
    """serverMsg ממפה detail לפי השוואת מחרוזות — קידוד שבור היה שובר
    גם את התרגום."""
    monkeypatch.setattr(main, "ALLOWED_EMAILS", {"owner@example.com"})
    monkeypatch.setattr(main, "AUTH_ON", True)
    r = _client().post("/auth/register",
                       json={"email": "someone@else.com", "password": "goodpass1"})
    assert r.status_code == 403
    assert r.json()["detail"] == main.LOGIN_I18N["he"]["err_closed"]
