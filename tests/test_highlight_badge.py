"""החיווי על הכרטיס (פידבק חיצוני, 19.9.26). קודם הופיע "תקציר" על כל
משחק שנגמר — גם כשלא היה מה להציג, וגילית את זה רק אחרי לחיצה."""
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

import main

HTML = open("index.html", encoding="utf-8").read()


def _match(db, mid, league="ucl", hours_ago=3,
           home="Arsenal", away="Chelsea"):
    """משחק ששוחק לפני כמה שעות — בן פחות מיומיים, כמו בפיד האמיתי.

    ליגה עם ערוצי מועדונים: המזהים שהפיד באמת מגיש נגזרים מהקבוצות,
    ולא צריך שורות ב-clubs."""
    kick = datetime.now(timezone.utc) - timedelta(hours=hours_ago)
    db.execute("INSERT INTO matches (id, league_key, home_team, away_team, date_utc, "
               "time_utc, status) VALUES (?, ?, ?, ?, ?, ?, 'FINISHED')",
               (mid, league, home, away,
                kick.strftime("%Y-%m-%d"), kick.strftime("%H:%M:%S")))
    db.commit()


def _cache(db, mid, source, videos_json, minutes_ago=1):
    when = (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).isoformat()
    db.execute("INSERT OR REPLACE INTO highlight_cache VALUES (?, ?, ?, ?)",
               (mid, source, videos_json, when))
    db.commit()


def _servable(db, mid):
    """המקורות שהמופע הזה באמת יגיש למשחק — מהקוד עצמו, לא משוכפלים כאן."""
    row = db.execute("SELECT * FROM matches WHERE id=?", (mid,)).fetchone()
    ids = {s["id"] for s in main.get_sources_for_match(row) if s.get("channel_id")}
    return sorted(ids | {f"web_{w['name']}" for w in
                         main.LEAGUES[row["league_key"]].get("web_sources", [])})


def _all_empty(db, mid, minutes_ago=1):
    """כל מקור נבדק והוחזר ריק — רק ככה "אין עדיין תקציר" הוא אמת."""
    for sid in _servable(db, mid):
        _cache(db, mid, sid, "[]", minutes_ago)


def _state(mid, league="ucl"):
    data = TestClient(main.app).get(f"/matches/{league}").json()
    return next(m["highlight"] for m in data["matches"] if m["id"] == mid)


def test_a_found_highlight_says_so(db):
    _match(db, "b1")
    _cache(db, "b1", _servable(db, "b1")[0],
           '[{"video_id": "abc", "label": "תקציר"}]')
    assert _state("b1") == "yes"


def test_checked_and_empty_says_there_is_none(db):
    _match(db, "b2")
    _all_empty(db, "b2")
    assert _state("b2") == "none"


def test_one_source_with_a_video_is_enough(db):
    _match(db, "b3")
    _all_empty(db, "b3")
    _cache(db, "b3", _servable(db, "b3")[1], '[{"video_id": "z"}]')
    assert _state("b3") == "yes"


def test_a_website_link_counts_as_a_highlight(db):
    _match(db, "b4", league="israel", home="Maccabi Haifa", away="Ironi Tiberias")
    _cache(db, "b4", "web_ספורט 1", '{"url": "https://sport1.example/x"}')
    assert _state("b4", league="israel") == "yes"


def test_a_match_nobody_checked_promises_nothing(db):
    """בלי בדיקה אין מה להבטיח — לא "יש" ולא "אין"."""
    _match(db, "b5")
    assert _state("b5") is None


def test_the_day_view_carries_the_same_state(db):
    _match(db, "b6", league="israel", home="Maccabi Haifa", away="Ironi Tiberias")
    _all_empty(db, "b6")
    day = main.to_israel_time(
        (datetime.now(timezone.utc) - timedelta(hours=3)).strftime("%Y-%m-%d"),
        "12:00:00")["date"]
    iso = "-".join(reversed(day.split("/")))
    data = TestClient(main.app).get(f"/matches/by_date/{iso}").json()
    assert any(m["id"] == "b6" and m["highlight"] == "none" for m in data["matches"])


def test_a_stale_no_promises_nothing(db):
    """"לא נמצא" במשחק טרי תקף 30 דקות בלבד — אחריהן החלון בודק שוב,
    ולכן הפיד לא יכול להכריז "אין". ברייטון–ארסנל, 20.9.26 בבוקר:
    הפיד אמר "אין עדיין תקציר", והחלון הציג מיד שני תקצירים."""
    _match(db, "b7")
    _all_empty(db, "b7", minutes_ago=90)
    assert _state("b7") is None


def test_one_stale_source_is_enough_to_stop_promising(db):
    _match(db, "b8")
    _all_empty(db, "b8", minutes_ago=1)
    _cache(db, "b8", _servable(db, "b8")[0], "[]", minutes_ago=90)
    assert _state("b8") is None


def test_an_old_match_keeps_its_no_for_longer(db):
    """משחק בן שבועות לא נבדק שוב כל חצי שעה — שם "אין" נשאר נכון."""
    _match(db, "b9", hours_ago=24 * 10)
    _all_empty(db, "b9", minutes_ago=60 * 24)
    assert _state("b9") == "none"


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


def test_a_source_this_instance_does_not_serve_is_not_a_promise(db, monkeypatch):
    """הקאש משותף לכתובת הציבורית ולפרטית. המופע הפרטי מצא תקציר במקור לא
    רשמי ושמר; הציבורי, שלא מגיש אותו, הבטיח "▶ תקציר" — והחלון הראה
    "התקציר עדיין לא הועלה"."""
    _match(db, "b10", league="israel", home="Maccabi Haifa",
           away="Hapoel Petah Tikva")
    _cache(db, "b10", "yt_footballyom1",
           '[{"video_id": "PIRATE1", "label": "תקציר"}]')
    monkeypatch.setattr(main, "UNOFFICIAL_SOURCES", False)
    assert _state("b10", league="israel") is None
    monkeypatch.setattr(main, "UNOFFICIAL_SOURCES", True)
    assert _state("b10", league="israel") == "yes"


def test_one_source_out_of_many_is_not_an_answer(db):
    """"אין עדיין תקציר" נאמר כשמקור אחד מתוך שבעה נבדק. זה "לא בדקנו"."""
    _match(db, "b11", league="israel", home="Maccabi Haifa",
           away="Hapoel Petah Tikva")
    _cache(db, "b11", "sport1", "[]", minutes_ago=5)
    assert _state("b11", league="israel") is None
    _all_empty(db, "b11", minutes_ago=5)
    assert _state("b11", league="israel") == "none"
