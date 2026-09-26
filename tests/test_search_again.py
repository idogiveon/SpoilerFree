"""הכפתור "חפש שוב" בחלון המשחק — מה הוא מוחק.

QA (26.9.26): הוא מחק את כל שורות הקאש של המשחק, כולל תקציר שנמצא. אם
החיפוש שאחריו נכשל (מכסה נגמרה, יוטיוב מחזיר שגיאה), התקציר שהיה על המסך
לפני הלחיצה נעלם — גם מהחלון וגם מהחיווי על הכרטיס. לכן נמחקות רק שורות
"נבדק ולא נמצא".
"""
import json
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

import main


def _match(db, mid="s1", hours_ago=30):
    kick = datetime.now(timezone.utc) - timedelta(hours=hours_ago)
    db.execute("INSERT INTO matches (id, league_key, home_team, away_team, date_utc, "
               "time_utc, status) VALUES (?, 'israel', 'Maccabi Haifa', "
               "'Hapoel Petah Tikva', ?, ?, 'FINISHED')",
               (mid, kick.strftime("%Y-%m-%d"), kick.strftime("%H:%M:%S")))
    db.commit()


def _cache(db, mid, source, payload, minutes_ago=60):
    when = (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).isoformat()
    db.execute("INSERT OR REPLACE INTO highlight_cache VALUES (?,?,?,?)",
               (mid, source, json.dumps(payload), when))
    db.commit()


def _rows(db, mid):
    return {r["source_id"]: r["videos_json"] for r in db.execute(
        "SELECT source_id, videos_json FROM highlight_cache WHERE match_id=?", (mid,))}


def test_a_found_highlight_survives_the_button(db, monkeypatch):
    _match(db)
    _cache(db, "s1", "sport1", [{"video_id": "GOOD", "label": "תקציר",
                                 "extended": False}])
    _cache(db, "s1", "sport5", [])
    c = TestClient(main.app)
    assert c.delete("/cache/s1").status_code == 200
    rows = _rows(db, "s1")
    assert "GOOD" in rows["sport1"]      # נשאר
    assert "sport5" not in rows          # "לא נמצא" — נמחק, ייבדק שוב


def test_and_a_failed_search_afterwards_does_not_lose_it(db, monkeypatch):
    """זה המצב שבו הבאג נראה: החיפוש שאחרי הלחיצה נכשל."""
    _match(db, "s2")
    _cache(db, "s2", "sport1", [{"video_id": "GOOD", "label": "תקציר",
                                 "extended": False}])
    c = TestClient(main.app)
    c.delete("/cache/s2")
    monkeypatch.setattr(main, "search_youtube", lambda **kw: None)   # מכסה/תקלה
    out = c.get("/highlights/s2?client=2").json()
    assert "GOOD" in [v["video_id"] for s in out["sources"] for v in s["videos"]]
    data = c.get("/matches/israel").json()
    assert next(m["highlight"] for m in data["matches"] if m["id"] == "s2") == "yes"
