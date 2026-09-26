"""משחק שהפתיחה שלו עברה אבל לא מסומן כגמור: הדפדפן מרענן את הליגה בעצמו
(גם מ"לפי יום"), במקום לשלוח את המשתמש לטאב הליגה."""
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

import main


def _insert(db, mid, when, status="SCHEDULED", league="laliga"):
    db.execute("INSERT INTO matches (id, league_key, home_team, away_team, date_utc, time_utc, status) "
               "VALUES (?, ?, 'Espanyol', 'Osasuna', ?, ?, ?)",
               (mid, league, when.strftime("%Y-%m-%d"), when.strftime("%H:%M:%S"), status))
    db.commit()


def test_old_stale_match_goes_straight_to_highlights(db, monkeypatch):
    """ליג 1 (13.9): משחק מאתמול עדיין SCHEDULED במקור — אחרי 6 שעות מחפשים תקציר."""
    monkeypatch.setattr(main, "search_youtube", lambda *a, **k: [])
    monkeypatch.setattr(main, "resolve_web_link", lambda *a, **k: None)
    _insert(db, "old", datetime.now(timezone.utc) - timedelta(hours=20))
    r = TestClient(main.app).get("/highlights/old").json()
    assert r["available"] is True and not r.get("needs_refresh")


def test_postponed_match_is_not_treated_as_over(db):
    _insert(db, "pp", datetime.now(timezone.utc) - timedelta(hours=20), status="POSTPONED")
    assert TestClient(main.app).get("/highlights/pp").json()["available"] is False


def test_stale_sportsdb_match_asks_browser_to_refresh(db):
    _insert(db, "m1", datetime.now(timezone.utc) - timedelta(hours=3))
    r = TestClient(main.app).get("/highlights/m1").json()
    assert r["available"] is False
    assert r["needs_refresh"] is True and r["league_key"] == "laliga"
    assert "טאב הליגה" not in r["reason"]          # לא שולחים לעמוד אחר


def test_future_match_does_not_ask_refresh(db):
    _insert(db, "m2", datetime.now(timezone.utc) + timedelta(days=2))
    r = TestClient(main.app).get("/highlights/m2").json()
    assert r["available"] is False and not r.get("needs_refresh")


def test_by_date_flags_stale_matches_only(db):
    kick = datetime.now(timezone.utc) - timedelta(hours=20)
    local = kick.astimezone(main.ISRAEL_TZ)
    if local.hour == 23 and local.minute >= 50:      # שני המשחקים באותו יום בישראל
        kick -= timedelta(minutes=15)
    _insert(db, "stale", kick)
    _insert(db, "done", kick + timedelta(minutes=5), status="FINISHED")
    il_day = kick.astimezone(main.ISRAEL_TZ).strftime("%Y-%m-%d")
    res = TestClient(main.app).get(f"/matches/by_date/{il_day}").json()
    flags = {m["id"]: m["needs_refresh"] for m in res["matches"]}
    assert flags["stale"] is True and flags["done"] is False


# ── ביקורת מוצר (26.9.26): "רענן" מוצע גם כשהוא לא יכול לעזור ───────
HTML = open("index.html", encoding="utf-8").read()


def test_an_old_matchday_gets_a_button_that_can_actually_load_it():
    """מחזור 2 באמצע העונה: ההנחיה אמרה "לחץ רענן כדי לטעון", אבל
    ↻ רענון מושך רק את חלון המחזורים האחרון (max-1..max+3) ולעולם לא
    יביא אותו. הכפתור כאן מושך בדיוק את המחזור שעל המסך."""
    assert "function renderEmptyMatchday(league, md)" in HTML
    assert "renderEmptyMatchday(league, md); return;" in HTML
    retry = HTML[HTML.index("function retryMatchday(league, md)"):]
    assert "mdTried.delete(" in retry[:200] and "loadMatchday(league, md)" in retry[:260]


def test_the_hint_names_the_button_that_is_on_the_screen():
    """ההנחיה ציטטה "רענן"; על הכפתור כתוב "↻ רענון"."""
    import re
    hints = re.findall(r'"no_matches_hint": "(.*?)"', HTML)
    assert len(hints) == 4
    assert all(h.startswith("↻") for h in hints), hints


def test_an_empty_refresh_does_not_blame_the_refresh():
    """גביע בין שלבים / MLS בחורף: "נסה שוב" יחזיר בדיוק אותו דבר,
    ויבזבז עוד שבע בקשות ל-TheSportsDB."""
    import re
    msgs = re.findall(r'"refresh_empty": "(.*?)"', HTML)
    assert len(msgs) == 4
    for m in msgs:
        assert "נסה שוב" not in m and "try again" not in m.lower()
        assert "inténtalo" not in m and "réessayez" not in m
