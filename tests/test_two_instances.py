"""קוד אחד, שתי כתובות.

החלטה עסקית-משפטית (26.9.26): האתר הציבורי רק מפנה החוצה ולא נוגע
בתוכן שאין לו רישיון. הגרסה עם הנגן המוטמע נשארת, בכתובת נפרדת וסגורה.
פיצול לענפים היה מבטיח שהשתיים יתפצלו לאט; במקום זה — שלושה דגלים.
"""
import pytest
from fastapi.testclient import TestClient

import main
from test_auth import ADMIN, FRIEND, client


def _row(db):
    db.execute("INSERT INTO matches (id, league_key, home_team, away_team, date_utc, "
               "time_utc, status) VALUES ('i1', 'israel', 'Maccabi Haifa', "
               "'Hapoel Petah Tikva', '2026-09-20', '18:00:00', 'FINISHED')")
    db.commit()
    return db.execute("SELECT * FROM matches WHERE id='i1'").fetchone()


def test_the_unofficial_channels_are_on(db):
    """החלטת הבעלים (26.9.26) — הם מקדימים את הרשמיים."""
    assert main.UNOFFICIAL_SOURCES is True
    names = [s["name"] for s in main.get_sources_for_match(_row(db))]
    assert "@FootballYom1" in names


def test_one_variable_takes_them_all_out(db, monkeypatch):
    """אם יגיע מכתב, הכיבוי חייב להיות מיידי ובלי deploy."""
    monkeypatch.setattr(main, "UNOFFICIAL_SOURCES", False)
    names = [s["name"] for s in main.get_sources_for_match(_row(db))]
    assert names == ["ספורט 1", "ערוץ הספורט", "ליגת העל"]


def test_the_three_are_marked_in_the_config():
    unofficial = [s["id"] for s in main.LEAGUES["israel"]["sources"] if s.get("unofficial")]
    assert unofficial == ["yt_footballyom1", "yt_almog218", "yt_itsfootball44"]


def test_an_open_site_lets_anyone_in():
    assert main.ALLOWED_EMAILS == set()          # ברירת המחדל: ציבורי


def test_a_closed_site_turns_away_everyone_else(db, monkeypatch, mails):
    """חוסם גם כניסה ולא רק הרשמה: שתי הכתובות חולקות DB, ובלי זה כל
    משתמש של האתר הציבורי היה נכנס לפרטי עם הסיסמה שלו."""
    monkeypatch.setattr(main, "AUTH_ON", True)
    monkeypatch.setattr(main, "ADMIN_EMAILS", {ADMIN})
    c = client()
    assert c.post("/auth/register",
                  json={"email": FRIEND, "password": "goodpass1"}).status_code == 200
    monkeypatch.setattr(main, "ALLOWED_EMAILS", {"owner@example.com"})
    for path, body in [("/auth/register", {"email": FRIEND, "password": "goodpass1"}),
                       ("/auth/login", {"email": FRIEND, "password": "goodpass1"}),
                       ("/auth/request_code", {"email": FRIEND})]:
        r = client().post(path, json=body)
        assert r.status_code == 403, path
        assert r.json()["detail"] == "האתר הזה סגור"


def test_the_owner_still_gets_in(db, monkeypatch, mails):
    monkeypatch.setattr(main, "AUTH_ON", True)
    monkeypatch.setattr(main, "ADMIN_EMAILS", {ADMIN})
    monkeypatch.setattr(main, "ALLOWED_EMAILS", {FRIEND})
    assert client().post("/auth/register",
                         json={"email": FRIEND, "password": "goodpass1"}).status_code == 200


def test_the_page_says_which_one_you_are_looking_at(db, monkeypatch, mails):
    monkeypatch.setattr(main, "AUTH_ON", True)
    monkeypatch.setattr(main, "ADMIN_EMAILS", {ADMIN})
    c = client()
    c.post("/auth/register", json={"email": FRIEND, "password": "goodpass1"})
    assert c.get("/auth/me").json()["private"] is False
    monkeypatch.setattr(main, "ALLOWED_EMAILS", {FRIEND})
    assert c.get("/auth/me").json()["private"] is True
    html = open("index.html", encoding="utf-8").read()
    assert 'id="lab-tag"' in html
    assert "document.getElementById('lab-tag').hidden = !(me.embed || me.private);" in html


def test_each_switch_has_one_place_that_decides():
    src = open("main.py", encoding="utf-8").read()
    assert 'os.environ.get("UNOFFICIAL_SOURCES", "1") != "0"' in src
    assert 'os.environ.get("ALLOWED_EMAILS", "")' in src
    # היחיד שדלוק כברירת מחדל — והוא זה שהכתובת הציבורית תכבה
    assert 'os.environ.get("EMBED_IN_APP", "1") != "0"' in src


# ── ביקורת מוצר (26.9.26) + שאלה מהמשתמש: שתי התקנות במסך הבית ──────
def test_the_private_install_has_its_own_name(monkeypatch):
    """הכתובת הפרטית היא origin נפרד, כלומר PWA נפרד — ועד עכשיו בשם
    ובאייקון זהים לציבורית: שני ריבועים שאי אפשר להבדיל ביניהם."""
    from fastapi.testclient import TestClient
    c = TestClient(main.app)
    monkeypatch.setattr(main, "EMBED_IN_APP", False)
    monkeypatch.setattr(main, "ALLOWED_EMAILS", set())
    assert c.get("/manifest.webmanifest").json()["short_name"] == "SpoilerFree"
    monkeypatch.setattr(main, "EMBED_IN_APP", True)
    assert c.get("/manifest.webmanifest").json()["short_name"] == "SpoilerFree LAB"
    monkeypatch.setattr(main, "EMBED_IN_APP", False)
    monkeypatch.setattr(main, "ALLOWED_EMAILS", {"owner@example.com"})
    assert c.get("/manifest.webmanifest").json()["name"] == "SpoilerFree LAB"


def test_the_lab_tag_follows_what_the_user_feels():
    """התג נגזר מ-private ("כתובת מוגבלת"), אבל מה שמבדיל את המופע בפועל
    הוא הנגן המוטמע — והוא נקבע בדגל נפרד ובלתי נראה."""
    html = open("index.html", encoding="utf-8").read()
    assert "!(me.embed || me.private)" in html
    assert '"embed": EMBED_IN_APP' in open("main.py", encoding="utf-8").read()
