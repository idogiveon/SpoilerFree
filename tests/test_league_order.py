"""סדר הליגות בתצוגה (מהבעלים, 2.10.26).

ברירת מחדל: ליגת העל (רק כשהחיבור מישראל), אנגלית, ספרדית, איטלקית,
גרמנית, צרפתית. אחרי חמישה ימי שימוש *שונים* — לא חמישה תקצירים ולא
חמש פתיחות באותו ערב — הסדר מתאים את עצמו למה שהמשתמש באמת פותח.
"""
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

import main
from test_auth import ADMIN, auth_on, client, login  # noqa: F401

HTML = open("index.html", encoding="utf-8").read()


def _events(db, email, days, league_matches):
    """יום אחד לכל ערך ב-days, ובכל אחד פתיחות משחק לפי league_matches."""
    for i, d in enumerate(days):
        ts = (datetime.now(timezone.utc) - timedelta(days=d)).isoformat()
        db.execute("INSERT INTO events (email, ts, type, league, match_id) "
                   "VALUES (?,?,'app_open',NULL,NULL)", (email, ts))
        for league, n in league_matches.items():
            for j in range(n if i == 0 else 0):
                mid = f"{league}-{j}"
                db.execute("INSERT OR IGNORE INTO matches (id, league_key, home_team, "
                           "away_team, date_utc, time_utc, status) VALUES "
                           "(?,?,'A','B','2026-09-20','18:00:00','FINISHED')",
                           (mid, league))
                db.execute("INSERT INTO events (email, ts, type, league, match_id) "
                           "VALUES (?,?,'match_open',NULL,?)", (email, ts, mid))
    db.commit()


def _order(c):
    return c.get("/favorites").json()


def test_four_days_of_use_earn_nothing(db, auth_on):
    c = login(auth_on, ADMIN)
    _events(db, ADMIN, [2, 3, 4], {"seriea": 9})    # ועוד היום עצמו = 4
    r = _order(c)
    assert r["active_days"] == 4
    assert r["league_order"] is None      # עדיין ברירת המחדל


def test_five_different_days_do(db, auth_on):
    """חמש פתיחות באותו ערב הן לא חמישה ימים — התנאי הוא ימים שונים."""
    c = login(auth_on, ADMIN)
    _events(db, ADMIN, [1, 2, 3, 4, 5], {"seriea": 9, "premier": 2})
    r = _order(c)
    assert r["active_days"] >= 5
    assert r["league_order"][0] == "seriea"       # מה שהוא באמת פותח
    assert r["league_order"].index("seriea") < r["league_order"].index("premier")


def test_the_order_does_not_reshuffle_on_every_visit(db, auth_on):
    """הסדר מחושב מחדש רק כשמספר הימים חוצה כפולה של חמש. בלי זה שורת
    הליגות הייתה מסתדרת מחדש מתחת לאצבע בכל כניסה."""
    c = login(auth_on, ADMIN)
    _events(db, ADMIN, [1, 2, 3, 4, 5], {"seriea": 9, "premier": 2})
    first = _order(c)["league_order"]
    # עכשיו הוא פותח הרבה פרמייר ליג — אותו יום, אותו דלי
    _events(db, ADMIN, [1], {"premier": 30})
    assert _order(c)["league_order"] == first


def test_the_default_order_is_the_one_that_was_asked_for():
    assert main.DEFAULT_LEAGUE_ORDER == ["israel", "premier", "laliga", "seriea",
                                         "bundesliga", "ligue1"]
    order = HTML[HTML.index("const DEFAULT_ORDER = ["):]
    for key in ("israel", "premier", "laliga", "seriea", "bundesliga", "ligue1"):
        assert f"'{key}'" in order[:200], key


def test_israel_shows_first_only_for_an_israeli_connection():
    """הלקוח מחליט, כי רק לו יש את הנתון — ובלי לשלוח IP לשום שירות."""
    fn = HTML[HTML.index("function fromIsrael()"):]
    fn = fn[:fn.index("\n  }")]
    assert "Asia/Jerusalem" in fn and "LANG === 'he'" in fn
    eff = HTML[HTML.index("function effectiveOrder()"):]
    assert "filter(l => l !== 'israel')" in eff[:400]


def test_an_explicit_favourite_still_comes_first():
    rank = HTML[HTML.index("function leagueRank(key)"):]
    assert "FAV_LEAGUES.has(key)) return -1" in rank[:200]


def test_both_views_use_the_same_order():
    """הפיד לא יכול לסתור את שורת הטאבים שמעליו."""
    assert "const rank = t => leagueRank(t.dataset.league);" in HTML
    assert "seen.sort((a, b) => leagueRank(a) - leagueRank(b))" in HTML
