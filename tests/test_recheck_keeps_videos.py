"""בדיקה חוזרת לא מוחקת תקציר שכבר נמצא.

ברייטון–ארסנל, 19.9.26 בלילה: הפיד הציג "▶ תקציר", ובפתיחת החלון נאמר
"התקציר עדיין לא הועלה ליוטיוב". הקאש החזיק תקציר קצר, הפתיחה הפעילה
בדיקה שמחפשת את הגרסה המורחבת (כלל 12 השעות), החיפוש לא החזיר כלום —
והתוצאה הריקה נכתבה על מה שכבר היה.
"""
import json
from datetime import datetime, timedelta, timezone

import main

SHORT = [{"video_id": "abc", "label": "תקציר", "extended": False, "published": ""}]


def _row(db, hours_ago=20):
    kick = datetime.now(timezone.utc) - timedelta(hours=hours_ago)
    db.execute("INSERT INTO matches (id, league_key, home_team, away_team, date_utc, "
               "time_utc, status) VALUES ('r1', 'premier', 'Brighton', 'Arsenal', ?, ?, "
               "'FINISHED')", (kick.strftime("%Y-%m-%d"), kick.strftime("%H:%M:%S")))
    db.commit()
    return db.execute("SELECT * FROM matches WHERE id='r1'").fetchone()


def _cache(db, videos, hours_ago):
    when = (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat()
    db.execute("INSERT OR REPLACE INTO highlight_cache VALUES ('r1', 'src', ?, ?)",
               (json.dumps(videos), when))
    db.commit()


def _stored(db):
    r = db.execute("SELECT videos_json FROM highlight_cache WHERE match_id='r1'").fetchone()
    return json.loads(r["videos_json"]) if r else None


SRC = {"id": "src", "name": "מקור", "channel_id": "UC123", "allow_embed": False}


def test_a_recheck_that_finds_nothing_keeps_what_we_had(db, monkeypatch):
    row = _row(db)
    _cache(db, SHORT, hours_ago=20)        # נמצא לפני 20 שעות, בלי גרסה מורחבת
    monkeypatch.setattr(main, "search_youtube", lambda **kw: [])
    out = main._source_highlights(row, SRC)
    assert [v["video_id"] for v in out["videos"]] == ["abc"]
    assert _stored(db) == SHORT            # הקאש לא נדרס


def test_a_recheck_that_finds_more_replaces_it(db, monkeypatch):
    row = _row(db)
    _cache(db, SHORT, hours_ago=20)
    better = SHORT + [{"video_id": "xyz", "label": "תקציר מורחב",
                       "extended": True, "published": ""}]
    monkeypatch.setattr(main, "search_youtube", lambda **kw: better)
    out = main._source_highlights(row, SRC)
    assert len(out["videos"]) == 2
    assert len(_stored(db)) == 2


def test_a_first_search_that_finds_nothing_is_still_recorded(db, monkeypatch):
    """"לא נמצא" ראשון כן נשמר — עליו נשען החיווי "אין עדיין תקציר"."""
    row = _row(db)
    monkeypatch.setattr(main, "search_youtube", lambda **kw: [])
    out = main._source_highlights(row, SRC)
    assert out["videos"] == [] and out["status"] == "not_found"
    assert _stored(db) == []


def test_an_api_error_never_touches_the_cache(db, monkeypatch):
    row = _row(db)
    _cache(db, SHORT, hours_ago=20)
    monkeypatch.setattr(main, "search_youtube", lambda **kw: None)
    out = main._source_highlights(row, SRC)
    assert out["status"] == "api_error"
    assert _stored(db) == SHORT
