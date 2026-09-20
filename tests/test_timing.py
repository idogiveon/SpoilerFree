"""#10 מי מעלה ראשון: הפעם הראשונה שכל מקור נמצא, בדיקה חוזרת ברקע, דוח בניהול."""
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

import main
from test_web_links import SPORT1_HTML, _pages


def _match(db, mid, kickoff, league="israel", home="Maccabi Haifa", away="Hapoel Petah Tikva"):
    db.execute("INSERT INTO matches (id, league_key, home_team, away_team, date_utc, time_utc, status) "
               "VALUES (?, ?, ?, ?, ?, ?, 'FINISHED')",
               (mid, league, home, away, kickoff.strftime("%Y-%m-%d"), kickoff.strftime("%H:%M:%S")))
    db.commit()
    return db.execute("SELECT * FROM matches WHERE id=?", (mid,)).fetchone()


def _first_seen(db, mid):
    return {r["source_id"]: r for r in
            db.execute("SELECT * FROM highlight_first_seen WHERE match_id=?", (mid,)).fetchall()}


def test_first_seen_keeps_the_first_upload(db, monkeypatch):
    row = _match(db, "t1", datetime.now(timezone.utc) - timedelta(hours=20))
    src = main.LEAGUES["israel"]["sources"][0]
    pub = "2026-09-13T21:05:00+00:00"
    monkeypatch.setattr(main, "search_youtube", lambda *a, **k: [
        {"video_id": "a", "label": "תקציר", "extended": False, "published": pub}])
    main._source_highlights(row, src)
    main._mark_first_seen(db, "t1", src["id"], "later", "2026-09-14T00:00:00+00:00")   # מתעלם
    db.commit()
    got = _first_seen(db, "t1")[src["id"]]
    assert got["published"] == pub


def test_not_found_leaves_no_timing_row(db, monkeypatch):
    row = _match(db, "t2", datetime.now(timezone.utc) - timedelta(hours=20))
    monkeypatch.setattr(main, "search_youtube", lambda *a, **k: [])
    main._source_highlights(row, main.LEAGUES["israel"]["sources"][0])
    assert _first_seen(db, "t2") == {}


def test_web_link_records_first_seen(db, monkeypatch):
    _pages(monkeypatch, {"sport1": SPORT1_HTML})
    row = _match(db, "t3", datetime.now(timezone.utc) - timedelta(hours=5))
    w = main.LEAGUES["israel"]["web_sources"][0]
    assert main._web_link(row, w)
    assert f"web_{w['name']}" in _first_seen(db, "t3")


def _prefetch_calls(db, monkeypatch):
    calls = []
    monkeypatch.setattr(main, "search_youtube", lambda home, *a, **k: calls.append(home) or [])
    monkeypatch.setattr(main, "_web_link", lambda row, w: None)
    main.prefetch_highlights_once()
    return calls


def test_an_expired_not_found_is_rechecked_in_every_league(db, monkeypatch):
    """התקציר של משחק אחר הצהריים עולה בלילה. בלי בדיקה חוזרת ברקע,
    מקור שהוחזר ריק פעם אחת לא נבדק שוב לעולם — ומשחקי פרמייר ליג
    מאתמול נשארו בלי תקציר עד שמישהו פתח אותם ידנית (20.9.26)."""
    il = _match(db, "t4", datetime.now(timezone.utc) - timedelta(hours=5))
    es = _match(db, "t5", datetime.now(timezone.utc) - timedelta(hours=5),
                league="laliga", home="Barcelona", away="Getafe")
    old = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    for row in (il, es):
        for s in main.get_sources_for_match(row):
            db.execute("INSERT INTO highlight_cache VALUES (?, ?, '[]', ?)", (row["id"], s["id"], old))
    db.commit()
    assert set(_prefetch_calls(db, monkeypatch)) == {"Maccabi Haifa", "Barcelona"}


def test_a_fresh_not_found_is_not_searched_again(db, monkeypatch):
    """גם ליגת העל, שבה הרקע פונה בכל סבב, לא מגיעה ליוטיוב: שכבת
    הקאש מכבדת את חלון 30 הדקות של _not_found_retry."""
    il = _match(db, "t4", datetime.now(timezone.utc) - timedelta(hours=5))
    es = _match(db, "t5", datetime.now(timezone.utc) - timedelta(hours=5),
                league="laliga", home="Barcelona", away="Getafe")
    fresh = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    for row in (il, es):
        for s in main.get_sources_for_match(row):
            db.execute("INSERT INTO highlight_cache VALUES (?, ?, '[]', ?)", (row["id"], s["id"], fresh))
    db.commit()
    assert _prefetch_calls(db, monkeypatch) == []


def test_a_found_highlight_is_not_searched_again(db, monkeypatch):
    es = _match(db, "t5", datetime.now(timezone.utc) - timedelta(hours=5),
                league="laliga", home="Barcelona", away="Getafe")
    old = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    for s in main.get_sources_for_match(es):
        db.execute("INSERT INTO highlight_cache VALUES (?, ?, ?, ?)",
                   (es["id"], s["id"], '[{"video_id": "x"}]', old))
    db.commit()
    assert _prefetch_calls(db, monkeypatch) == []


def test_timing_report(db):
    k = datetime(2026, 9, 12, 17, 0, tzinfo=timezone.utc)      # סיום משוער 18:55
    _match(db, "t6", k)
    rows = [("sport1", "2026-09-12T19:15:00+00:00", None),              # 20 דק'
            ("yt_almog218", "2026-09-12T19:05:00+00:00", None),         # 10 דק'
            ("web_ספורט 1", None, "2026-09-12T20:00:00+00:00")]          # 65 דק'
    for sid, pub, seen in rows:
        db.execute("INSERT INTO highlight_first_seen VALUES ('t6', ?, ?, ?)",
                   (sid, seen or "2026-09-12T22:00:00+00:00", pub))
    db.commit()
    monkey_now = datetime(2026, 9, 13, 12, 0, tzinfo=timezone.utc)
    orig = main._now
    main._now = lambda: monkey_now
    try:
        res = TestClient(main.app).get("/admin/api/timing?league=israel&days=7").json()
    finally:
        main._now = orig
    assert res["summary"][0] == {"source": "@almog218", "found": 1, "first": 1, "median_min": 10}
    m = res["matches"][0]
    assert m["first"] == "@almog218"
    assert list(m["delays"].values()) == [10, 20, 65]
    assert "מי מעלה ראשון" in TestClient(main.app).get("/admin/users").text
