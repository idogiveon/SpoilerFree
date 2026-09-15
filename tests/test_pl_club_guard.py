"""פרמייר ליג: ערוץ מועדון רק אם הוא של אחת מקבוצות המשחק (טוטנהאם–אברטון 15.9.26)."""
from fastapi.testclient import TestClient

import main


def _row(db, mid, home, away, hid, aid):
    db.execute("INSERT INTO matches (id, league_key, home_team, away_team, home_team_id, away_team_id, "
               "date_utc, time_utc, status) VALUES (?, 'premier', ?, ?, ?, ?, '2026-09-13', '14:00:00', 'FINISHED')",
               (mid, home, away, hid, aid))
    db.commit()
    return db.execute("SELECT * FROM matches WHERE id=?", (mid,)).fetchone()


def _clubs(sources):
    return [s["club_team"] for s in sources if s.get("club_team")]


def test_right_clubs_for_the_match(db):
    row = _row(db, "t1", "Tottenham Hotspur FC", "Everton FC", "73", "62")
    assert sorted(_clubs(main.get_sources_for_match(row))) == ["Everton FC", "Tottenham Hotspur FC"]


def test_wrong_team_ids_never_bring_other_clubs(db):
    """השורה אומרת טוטנהאם–אברטון אבל המזהים של ליברפול ופולהאם."""
    row = _row(db, "t2", "Tottenham Hotspur FC", "Everton FC", "64", "63")
    assert _clubs(main.get_sources_for_match(row)) == []


def test_debug_match_shows_ids_sources_and_cache(db):
    _row(db, "t3", "Tottenham Hotspur FC", "Everton FC", "73", "62")
    db.execute("INSERT INTO highlight_cache VALUES ('t3', 'club_PL-fd73', '[]', '2026-09-13T20:00:00')")
    db.commit()
    m = TestClient(main.app).get("/debug/match?q=Tottenham").json()["matches"][0]
    assert (m["home_team_id"], m["away_team_id"]) == ("73", "62")
    assert {c["short_name"] for c in m["clubs_by_team_id"]} == {"Spurs", "Everton"}
    assert m["cache"][0]["source_id"] == "club_PL-fd73"
    assert any(s["id"] == "club_PL-fd73" for s in m["sources"])
