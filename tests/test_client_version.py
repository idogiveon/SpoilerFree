"""לקוח ישן לא מקבל הרשאה להטמיע.

22.9.26: השרת התחיל לשלוח allow_embed=true, וה-PWA עדיין הריץ את הקוד
הישן — שאין לו מגן. הוא הזריק iframe חשוף, הניגון האוטומטי נחסם בטלפון,
והתמונה הממוזערת עם "5 : 3" נשארה על המסך. הדגל היה בשרת, היכולת
להשתמש בו נמצאת בלקוח, ובלי לקשור ביניהם זה ייפול שוב.
"""
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

import main

HTML = open("index.html", encoding="utf-8").read()


def _match(db):
    kick = datetime.now(timezone.utc) - timedelta(hours=3)
    db.execute("INSERT INTO matches (id, league_key, home_team, away_team, date_utc, "
               "time_utc, status) VALUES ('v1', 'israel', 'Maccabi Haifa', "
               "'Hapoel Petah Tikva', ?, ?, 'FINISHED')",
               (kick.strftime("%Y-%m-%d"), kick.strftime("%H:%M:%S")))
    db.execute("INSERT INTO highlight_cache VALUES ('v1', 'sport1', "
               "'[{\"video_id\": \"abc\", \"label\": \"תקציר\"}]', ?)",
               (datetime.now(timezone.utc).isoformat(),))
    db.commit()


def _embeds(client_param=""):
    r = TestClient(main.app).get(f"/highlights/v1?lang=he{client_param}").json()
    return [s["allow_embed"] for s in r["sources"]]


def test_a_client_that_did_not_say_gets_no_embedding(db):
    """בלי פרמטר = הקוד הישן, זה שאין לו מגן."""
    _match(db)
    assert any(_embeds()) is False


def test_the_new_client_gets_embedding(db):
    _match(db)
    assert any(_embeds("&client=2")) is True


def test_the_client_actually_asks_with_its_version():
    assert "/highlights/${matchId}?lang=${LANG}&client=2" in HTML


def test_the_kill_switch_still_wins(db, monkeypatch):
    _match(db)
    monkeypatch.setattr(main, "EMBED_IN_APP", False)
    assert any(_embeds("&client=2")) is False


def test_the_cached_page_is_dropped_when_the_client_must_change():
    """בלי הקפצת הקאש, הקוד החדש מגיע רק בפתיחה שאחרי — ובינתיים
    השרת והלקוח לא מסכימים."""
    import re
    sw = open("static/sw.js", encoding="utf-8").read()
    ver = re.search(r"const CACHE = 'sf-shell-v(\d+)';", sw)
    assert ver and int(ver.group(1)) >= 2, "הקפצת גרסה מוחקת את הדף השמור"
