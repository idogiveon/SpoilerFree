"""רענון לוח: כותבים רק מה שהשתנה, purge לא מוחק היסטוריה או לוח ידני."""
import main


def row(status="SCHEDULED", date="2026-09-20"):
    return {"home_team": "A", "away_team": "B", "home_team_id": None, "away_team_id": None,
            "date_utc": date, "time_utc": "14:00:00", "venue": "", "matchday": 5,
            "status": status}


def ids(db, league="t"):
    return {r["id"] for r in db.execute("SELECT id FROM matches WHERE league_key=?", (league,)).fetchall()}


def seed(db):
    main._sync_league_rows(db, "t", {"1": row("FINISHED", "2026-08-01"), "2": row(), "3": row()})
    db.execute("INSERT INTO matches (id, league_key, status) VALUES ('manual-t-x', 't', 'SCHEDULED')")


def test_first_write_then_idempotent(db):
    inc = {"1": row("FINISHED", "2026-08-01"), "2": row(), "3": row()}
    assert main._sync_league_rows(db, "t", inc) == {"written": 3, "deleted": 0}
    assert main._sync_league_rows(db, "t", dict(inc), purge=True) == {"written": 0, "deleted": 0}


def test_partial_response_keeps_history_and_manual(db):
    seed(db)
    assert main._sync_league_rows(db, "t", {"2": row()}, purge=True) == {"written": 0, "deleted": 1}
    assert ids(db) == {"1", "2", "manual-t-x"}


def test_empty_response_deletes_nothing(db):
    seed(db)
    assert main._sync_league_rows(db, "t", {}, purge=True) == {"written": 0, "deleted": 0}
    assert ids(db) == {"1", "2", "3", "manual-t-x"}


def test_status_never_downgraded(db):
    seed(db)
    db.execute("UPDATE matches SET status='FINISHED' WHERE id='2'")
    assert main._sync_league_rows(db, "t", {"2": row()}, guard_status=True)["written"] == 0


def test_hard_purge_removes_everything_not_incoming(db):
    seed(db)
    res = main._sync_league_rows(db, "t", {"2": row()}, purge=True, hard=True)
    assert res["deleted"] == 3
    assert ids(db) == {"2"}


def test_sportsdb_duplicate_keeps_finished_status():
    rows = main._sportsdb_rows([
        {"idEvent": "9", "strStatus": "Match Finished", "intHomeScore": "1", "intAwayScore": "0"},
        {"idEvent": "9", "strStatus": ""},   # eventsround מחזיר סטטוס ריק
    ])
    assert rows["9"]["status"] == "FINISHED"


def test_league_freshness_recorded(db):
    main._sync_league_rows(db, "t", {"1": row()})
    assert main._league_fetched_at(db, "t") is not None


def test_min_date_drops_qualifiers(db):
    n = main._store_sportsdb_events(db, "ucl", [
        {"idEvent": "q", "dateEvent": "2026-07-14", "strHomeTeam": "A", "strAwayTeam": "B"},
        {"idEvent": "l", "dateEvent": "2026-10-13", "strHomeTeam": "Lens", "strAwayTeam": "Sporting CP"},
    ])
    assert n == 1
    assert ids(db, "ucl") == {"l"}


def test_min_date_cleanup_on_startup(db):
    db.execute("INSERT INTO matches (id, league_key, date_utc, status) "
               "VALUES ('old', 'ucl', '2026-07-07', 'FINISHED')")
    db.commit()
    main.init_db()
    assert "old" not in ids(db, "ucl")
