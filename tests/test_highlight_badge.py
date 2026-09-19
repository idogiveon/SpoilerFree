"""החיווי על הכרטיס (פידבק חיצוני, 19.9.26). קודם הופיע "תקציר" על כל
משחק שנגמר — גם כשלא היה מה להציג, וגילית את זה רק אחרי לחיצה."""
from fastapi.testclient import TestClient

import main

HTML = open("index.html", encoding="utf-8").read()


def _match(db, mid, league="premier"):
    db.execute("INSERT INTO matches (id, league_key, home_team, away_team, date_utc, "
               "time_utc, status) VALUES (?, ?, 'Arsenal FC', 'Chelsea FC', "
               "'2026-09-18', '19:00:00', 'FINISHED')", (mid, league))
    db.commit()


def _cache(db, mid, source, videos_json):
    db.execute("INSERT INTO highlight_cache VALUES (?, ?, ?, '2026-09-18T22:00:00')",
               (mid, source, videos_json))
    db.commit()


def _state(mid, league="premier"):
    data = TestClient(main.app).get(f"/matches/{league}").json()
    return next(m["highlight"] for m in data["matches"] if m["id"] == mid)


def test_a_found_highlight_says_so(db):
    _match(db, "b1")
    _cache(db, "b1", "club_x", '[{"video_id": "abc", "label": "תקציר"}]')
    assert _state("b1") == "yes"


def test_checked_and_empty_says_there_is_none(db):
    _match(db, "b2")
    _cache(db, "b2", "club_x", "[]")
    assert _state("b2") == "none"


def test_one_source_with_a_video_is_enough(db):
    _match(db, "b3")
    _cache(db, "b3", "club_x", "[]")
    _cache(db, "b3", "sky", '[{"video_id": "z"}]')
    assert _state("b3") == "yes"


def test_a_website_link_counts_as_a_highlight(db):
    _match(db, "b4")
    _cache(db, "b4", "web_ספורט 1", '{"url": "https://sport1.example/x"}')
    assert _state("b4") == "yes"


def test_a_match_nobody_checked_promises_nothing(db):
    """בלי בדיקה אין מה להבטיח — לא "יש" ולא "אין"."""
    _match(db, "b5")
    assert _state("b5") is None


def test_the_day_view_carries_the_same_state(db):
    _match(db, "b6", league="israel")
    _cache(db, "b6", "sport1", "[]")
    data = TestClient(main.app).get("/matches/by_date/2026-09-18").json()
    assert next(m["highlight"] for m in data["matches"] if m["id"] == "b6") == "none"


def test_the_card_shows_all_three_states():
    assert "m.highlight === 'none'" in HTML
    assert "t('badge_none')" in HTML
    assert "m.highlight === 'yes' ? '' : ' is-unknown'" in HTML
    assert HTML.count('"badge_none":') == 4          # ארבע השפות


def test_the_badge_is_not_hidden_on_a_phone():
    """קודם `.highlight-badge { display:none }` במסך צר — כל הפיד בטלפון
    היה בלי חיווי בכלל, וזה בדיוק המכשיר שבו משתמשים."""
    mobile = HTML[HTML.index("@media (max-width:600px)"):]
    mobile = mobile[:mobile.index("</style>")]
    assert ".venue { display:none; }" in mobile
    assert ".highlight-badge { position:static" in mobile
    assert ".highlight-badge,.live-badge { display:none; }" not in mobile


def test_the_debug_view_compares_the_badge_with_what_the_window_finds(db):
    """הפיד הבטיח תקציר לטוטנהאם–אסטון וילה והחלון אמר "עדיין לא עלה"
    (19.9.26). כאן רואים בבת אחת מי מהשניים צודק ולמה."""
    db.execute("INSERT INTO matches (id, league_key, home_team, away_team, date_utc, "
               "time_utc, status) VALUES ('dbg1', 'israel', 'Maccabi Haifa', "
               "'Ironi Tiberias', '2026-09-18', '19:00:00', 'FINISHED')")
    _cache(db, "dbg1", "sport1", '[{"video_id": "v1"}]')      # מקור קיים
    _cache(db, "dbg1", "club_gone", '[{"video_id": "v2"}]')   # מזהה נטוש
    db.commit()
    m = TestClient(main.app).get("/debug/match?q=Maccabi Haifa").json()["matches"][0]
    assert m["badge"]["feed_says"] == "yes"
    assert m["badge"]["orphan_rows"] == ["club_gone"]
    assert m["badge"]["usable_now"] == ["sport1"]
