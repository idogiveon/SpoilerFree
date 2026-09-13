"""לוחות ידניים (ליגת העל, צ'מפיונס) ושעון ישראל כולל מעבר לשעון חורף."""
from collections import Counter

import pytest

import main


@pytest.mark.parametrize("date_utc, time_utc, il_time", [
    ("2026-09-13", "17:30:00", "20:30"),   # קיץ: +3
    ("2026-11-01", "18:00:00", "20:00"),   # חורף: +2 (מעבר ב-25.10.26)
])
def test_israel_time_dst(date_utc, time_utc, il_time):
    assert main.to_israel_time(date_utc, time_utc)["time"] == il_time


def test_il_to_utc_dst():
    assert main._il_to_utc("2026-10-24", "20:00") == ("2026-10-24", "17:00:00")
    assert main._il_to_utc("2026-11-01", "20:00") == ("2026-11-01", "18:00:00")


def _check_round_robin(fixtures, teams_per_round):
    by_md = {}
    for md, _d, _t, home, away, *_ in fixtures:
        by_md.setdefault(md, []).extend([home, away])
    for md, teams in by_md.items():
        assert len(teams) == teams_per_round, f"round {md}"
        assert len(set(teams)) == teams_per_round, f"round {md}: team twice"


def test_ucl_calendar_shape():
    fx = main.MANUAL_FIXTURES["ucl"]
    assert len(fx) == 144
    assert Counter(f[0] for f in fx) == {md: 18 for md in range(1, 9)}
    _check_round_robin(fx, 36)
    home = Counter(f[3] for f in fx)
    away = Counter(f[4] for f in fx)
    assert len(home) == 36 and set(home.values()) == {4} and set(away.values()) == {4}
    assert max(Counter(frozenset((f[3], f[4])) for f in fx).values()) == 1


def test_israel_calendar_shape():
    _check_round_robin(main.MANUAL_FIXTURES["israel"], 14)


def test_manual_fixtures_merge_with_sportsdb(db):
    # שני משחקים ש-sportsdb כבר מכיר (מחזור 1) + הלוח הידני משלים את השאר
    main._store_sportsdb_events(db, "ucl", [
        {"idEvent": "e1", "intRound": "1", "dateEvent": "2026-09-08", "strTime": "16:45:00",
         "strHomeTeam": "AEK Athens", "strAwayTeam": "LASK", "strVenue": "OPAP Arena"},
        {"idEvent": "e2", "intRound": "1", "dateEvent": "2026-09-08", "strTime": "16:45:00",
         "strHomeTeam": "Club Brugge", "strAwayTeam": "Aston Villa", "strVenue": "Jan Breydel"},
    ])
    db.commit()
    main.apply_manual_fixtures("ucl")
    main.apply_manual_fixtures("ucl")   # פעם שנייה — בלי כפילויות
    rows = db.execute("SELECT id, venue FROM matches WHERE league_key='ucl'").fetchall()
    assert len(rows) == 144
    assert sum(str(r["id"]).startswith("manual-") for r in rows) == 142
    venues = {r["id"]: r["venue"] for r in rows}
    assert venues["e1"] == "OPAP Arena"   # אצטדיון ריק בלוח לא דורס


def test_ucl_winter_kickoff_in_israel_time(db):
    main.apply_manual_fixtures("ucl")
    r = db.execute("SELECT date_utc, time_utc FROM matches WHERE league_key='ucl' "
                   "AND home_team='Atlético Madrid' AND away_team='Bayern Munich'").fetchone()
    # 3.11, 21:00 CET = 20:00 UTC = 22:00 שעון ישראל
    assert (r["date_utc"], r["time_utc"]) == ("2026-11-03", "20:00:00")
    assert main.to_israel_time(r["date_utc"], r["time_utc"])["time"] == "22:00"
