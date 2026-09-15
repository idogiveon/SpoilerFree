"""ליגה ריקה ב-Render: תשובה מיידית (הדפדפן מרענן), בלי ניסיון חסום ל-TheSportsDB."""
from fastapi.testclient import TestClient

import main


def test_empty_sportsdb_league_on_render_answers_without_server_fetch(monkeypatch):
    monkeypatch.setenv("RENDER", "true")

    def blocked(*a, **k):
        raise AssertionError("server must not fetch TheSportsDB on Render")
    monkeypatch.setattr(main, "fetch_and_store", blocked)
    r = TestClient(main.app).get("/matches/bundesliga").json()
    assert r["matches"] == []                    # הדפדפן יראה ריק וירענן בעצמו


def test_old_cache_without_translated_names_is_ignored():
    """קאש ישן במכשיר (בלי home_name) הציג שמות באנגלית עד תשובת השרת."""
    html = open("index.html", encoding="utf-8").read()
    assert "!('home_name' in d.matches[0])) return null" in html


def test_empty_league_still_fetched_locally(monkeypatch):
    monkeypatch.delenv("RENDER", raising=False)
    calls = []
    monkeypatch.setattr(main, "fetch_and_store", lambda lg, **k: calls.append(lg))
    TestClient(main.app).get("/matches/bundesliga")
    assert calls == ["bundesliga"]
