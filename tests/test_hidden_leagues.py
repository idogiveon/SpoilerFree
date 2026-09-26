"""הסתרת ליגה: לא מוצגת ב"לפי יום"; הסתרה מוציאה מהמועדפות; נמחקת עם החשבון."""
import pytest

import main
from test_auth import ADMIN, FRIEND, client


@pytest.fixture
def auth_on(monkeypatch, mails):
    monkeypatch.setattr(main, "AUTH_ON", True)
    monkeypatch.setattr(main, "ADMIN_EMAILS", {ADMIN})
    return mails


def _register():
    c = client()
    assert c.post("/auth/register", json={"email": FRIEND, "password": "goodpass1"}).status_code == 200
    return c


def test_hide_and_unhide_league(auth_on):
    c = _register()
    assert c.post("/favorites", json={"hide_league": "ligue1", "on": True}).json()["ok"]
    assert c.get("/favorites").json()["hidden"] == ["ligue1"]
    assert c.post("/favorites", json={"hide_league": "nope", "on": True}).status_code == 400
    c.post("/favorites", json={"hide_league": "ligue1", "on": False})
    assert c.get("/favorites").json()["hidden"] == []


def test_hiding_a_favorite_league_removes_it_from_favorites(auth_on):
    c = _register()
    c.post("/favorites", json={"league": "ligue1", "on": True})
    c.post("/favorites", json={"hide_league": "ligue1", "on": True})
    f = c.get("/favorites").json()
    assert f["leagues"] == [] and f["hidden"] == ["ligue1"]


def test_delete_account_removes_hidden_leagues(auth_on):
    c = _register()
    c.post("/favorites", json={"hide_league": "ligue1", "on": True})
    c.post("/auth/delete_account", json={"confirm": FRIEND})
    conn = main.get_db()
    assert conn.execute("SELECT COUNT(*) AS n FROM hidden_leagues").fetchone()["n"] == 0
    conn.close()


def test_day_view_filters_hidden_leagues_in_app():
    html = open("index.html", encoding="utf-8").read()
    assert "HIDDEN_LEAGUES.has(m.league_key)" in html


# ── ביקורת מוצר (26.9.26): אין שום סימן שליגות מוסתרות ───────────────
HTML = open("index.html", encoding="utf-8").read()
def test_the_day_view_says_how_many_leagues_are_hidden():
    """הטאב יורד ב-display:none והמונה סופר רק את הנראים — מי שבחר שלוש
    ליגות במסך הפתיחה ותוהה חודש אחרי "איפה הבונדסליגה" לא קיבל רמז."""
    assert "function hiddenNoteHTML(matches)" in HTML
    assert "container.innerHTML = html + hiddenNoteHTML(matches)" in HTML
    assert 'class="hidden-note" onclick="openLeaguePicker()"' in HTML


def test_it_is_written_in_four_languages_and_counts_one_properly():
    for key in ('"hidden_n":', '"hidden_1":'):
        assert HTML.count(key) == 4, key
    assert "hidden.size === 1 ? 'hidden_1' : 'hidden_n'" in HTML
    assert '"hidden_tab"' not in HTML          # המחרוזת המתה שהייתה כאן


def test_a_day_whose_leagues_are_all_hidden_is_not_a_blank_screen():
    """כל הליגות של היום מוסתרות: html יוצא ריק, והמסך היה ריק לגמרי."""
    assert "if (!html) html = `<div class=\"empty\">${t('no_matches_day')}</div>`" in HTML
