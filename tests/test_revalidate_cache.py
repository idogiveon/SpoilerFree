"""A2: ניקוי שורות קאש שנכתבו לפני תיקוני ההתאמה.

9.10.26 התגלו שלושה באגים באותו יום — תקציר של קבוצת הנשים, של קבוצת
הנוער, ותווית שגויה. התיקונים נכנסו, אבל מה שכבר שמור בקאש המשיך
להחזיק את הסרטון השגוי, ו"חפש שוב" ידני פר משחק היה הדרך היחידה.

אפשרי רק כי הכותרת נשמרת בקאש לצד המזהה: אותם כללים בדיוק רצים מחדש
בלי אף קריאת רשת ובלי יחידת מכסה.
"""
import json

from fastapi.testclient import TestClient

import main

def _match(db, mid="m1", date="2026-09-19"):
    """בפרמייר המקורות הם ערוצי המועדונים, והזורע מוחק ומזריע מחדש את
    הטבלה — ולכן לוקחים שני מועדונים אמיתיים מה-DB במקום להמציא."""
    home, away = db.execute(
        "SELECT * FROM clubs WHERE league_key='premier' AND yt_channel_id != '' "
        "ORDER BY id LIMIT 2").fetchall()
    db.execute("INSERT INTO matches (id, league_key, home_team, away_team, "
               "home_team_id, away_team_id, date_utc, time_utc, status) "
               "VALUES (?,'premier',?,?,?,?,?,'18:00','FINISHED')",
               (mid, home["name"], away["name"], home["fd_team_id"],
                away["fd_team_id"], date))
    return home["name"], away["name"]


def _cache(db, mid, source, videos):
    db.execute("INSERT INTO highlight_cache (match_id, source_id, videos_json, found_at) "
               "VALUES (?,?,?,?)",
               (mid, source, json.dumps(videos, ensure_ascii=False),
                main._now().isoformat()))


def _src(db, mid):
    """המקור הראשון שהמשחק מקבל בפועל — לא ניחוש של שם."""
    m = db.execute("SELECT * FROM matches WHERE id=?", (mid,)).fetchone()
    return main.get_sources_for_match(m)[0]["id"]


PUB = "2026-09-19T20:00:00+00:00"


def _womens(home):
    return f"{home} 2-1 Man Utd | Women's Super League | Highlights"


def _real(home, away):
    return f"{home} 2-0 {away} | Premier League | Highlights"


def test_a_womens_highlight_is_dropped(db):
    home, _ = _match(db)
    _cache(db, "m1", _src(db, "m1"),
           [{"video_id": "bad", "title": _womens(home), "published": PUB}])
    db.commit()
    rep = main.revalidate_cache(apply=True)
    assert rep["checked"] == 1 and rep["kept"] == 0
    assert rep["dropped"][0]["row_deleted"] is True
    # השורה נמחקה ולא נשמרה כ-[]: המשחק נחשב "לא נבדק" וייכנס לתור מיד
    assert db.execute("SELECT COUNT(*) FROM highlight_cache WHERE match_id='m1'"
                      ).fetchone()[0] == 0


def test_a_good_highlight_survives(db):
    home, away = _match(db)
    _cache(db, "m1", _src(db, "m1"),
           [{"video_id": "ok", "title": _real(home, away), "published": PUB}])
    db.commit()
    rep = main.revalidate_cache(apply=True)
    assert rep["kept"] == 1 and rep["dropped"] == []
    assert db.execute("SELECT COUNT(*) FROM highlight_cache").fetchone()[0] == 1


def test_only_the_bad_entry_leaves_the_row(db):
    home, away = _match(db)
    _cache(db, "m1", _src(db, "m1"), [
        {"video_id": "ok", "title": _real(home, away), "published": PUB},
        {"video_id": "bad", "title": _womens(home), "published": PUB},
    ])
    db.commit()
    rep = main.revalidate_cache(apply=True)
    assert rep["kept"] == 1 and rep["dropped"][0]["row_deleted"] is False
    left = json.loads(db.execute("SELECT videos_json FROM highlight_cache "
                                 "WHERE match_id='m1'").fetchone()["videos_json"])
    assert [v["video_id"] for v in left] == ["ok"]


def test_a_dry_run_touches_nothing(db):
    """מחיקה היא פעולה שאין ממנה חזרה, ולכן ברירת המחדל מדווחת בלבד."""
    home, _ = _match(db)
    _cache(db, "m1", _src(db, "m1"), [{"video_id": "bad", "title": _womens(home)}])
    db.commit()
    rep = main.revalidate_cache()
    assert rep["applied"] is False and len(rep["dropped"]) == 1
    assert db.execute("SELECT COUNT(*) FROM highlight_cache").fetchone()[0] == 1


def test_an_entry_without_a_title_is_never_deleted(db):
    """שורות מלפני שהתחלנו לשמור כותרות — אין על מה לשפוט, ולא מנחשים."""
    _match(db)
    _cache(db, "m1", _src(db, "m1"), [{"video_id": "old"}])
    db.commit()
    rep = main.revalidate_cache(apply=True)
    assert rep["untitled"] == 1 and rep["checked"] == 0 and rep["dropped"] == []
    assert db.execute("SELECT COUNT(*) FROM highlight_cache").fetchone()[0] == 1


def test_a_web_link_row_is_left_alone(db):
    """שורות web_* מחזיקות {"url": ...} ולא רשימת סרטונים."""
    _match(db)
    _cache(db, "m1", "web_ספורט 5", {"url": "https://vod.sport5.co.il/?Vi=1"})
    db.commit()
    rep = main.revalidate_cache(apply=True)
    assert rep["checked"] == 0 and rep["dropped"] == []
    assert db.execute("SELECT COUNT(*) FROM highlight_cache").fetchone()[0] == 1


def test_a_row_whose_match_is_gone_is_only_counted(db):
    _cache(db, "ghost", "sport1", [{"video_id": "x", "title": "whatever"}])
    db.commit()
    rep = main.revalidate_cache(apply=True)
    assert rep["orphans"] == 1
    assert db.execute("SELECT COUNT(*) FROM highlight_cache").fetchone()[0] == 1


def test_the_endpoint_defaults_to_reporting_only(db):
    home, _ = _match(db)
    _cache(db, "m1", _src(db, "m1"), [{"video_id": "bad", "title": _womens(home)}])
    db.commit()
    c = TestClient(main.app)
    assert c.get("/admin/api/recheck_cache").json()["applied"] is False
    assert db.execute("SELECT COUNT(*) FROM highlight_cache").fetchone()[0] == 1
    assert c.get("/admin/api/recheck_cache?apply=1").json()["applied"] is True
    assert db.execute("SELECT COUNT(*) FROM highlight_cache").fetchone()[0] == 0
