"""חיפוש הרקע חייב להגיע לכל המשחקים, לא לאותם עשרים בכל סבב.

הלולאה נעצרת אחרי PREFETCH_MAX_MATCHES ושולפת בלי ORDER BY — כלומר
בסדר הטבלה. ברוב המצבים זה מסתדר מעצמו: משחק שנבדק מקבל קאש טרי,
יוצא מהתור, והתור מתקדם. אבל כשהתוקף פג לכולם יחד (שבת עמוסה, 17
ליגות) הראשונים בטבלה תפסו את המקומות שוב ושוב.
"""
from datetime import datetime, timedelta, timezone

import main


def _many(db, n):
    kick = datetime.now(timezone.utc) - timedelta(hours=3)
    for i in range(n):
        db.execute("INSERT INTO matches (id, league_key, home_team, away_team, date_utc, "
                   "time_utc, status) VALUES (?, 'laliga', ?, 'Getafe', ?, ?, 'FINISHED')",
                   (f"m{i:03d}", f"Team {i}", kick.strftime("%Y-%m-%d"),
                    kick.strftime("%H:%M:%S")))
    db.commit()


def _round(monkeypatch):
    """סבב אחד. מחזיר את המשחקים שנבדקו בו."""
    seen = []
    monkeypatch.setattr(main, "search_youtube", lambda home, *a, **k: seen.append(home) or [])
    monkeypatch.setattr(main, "_web_link", lambda row, w: None)
    main.prefetch_highlights_once()
    return {h for h in seen}


def test_two_rounds_reach_more_than_one_round_can(db, monkeypatch):
    """הרוטציה הרגילה — זו שעובדת גם בלי סדר מפורש: הקאש הטרי מוציא
    את מי שנבדק מהתור, והסבב הבא מגיע לאחרים."""
    _many(db, main.PREFETCH_MAX_MATCHES + 12)
    first = _round(monkeypatch)
    second = _round(monkeypatch)
    assert first and second
    assert second - first, "הסבב השני חזר על אותם משחקים בדיוק"
    assert len(first | second) > len(first)


def test_nobody_is_left_behind_for_good(db, monkeypatch):
    """אחרי מספיק סבבים כל משחק נבדק לפחות פעם אחת."""
    total = main.PREFETCH_MAX_MATCHES + 12
    _many(db, total)
    reached = set()
    for _ in range(4):
        reached |= _round(monkeypatch)
    assert len(reached) == total


def test_the_never_checked_go_first(db, monkeypatch):
    """משחק שלא נבדק מעולם קודם למי שכבר נבדק — גם אם הוא מאוחר בטבלה."""
    _many(db, 3)
    old = (datetime.now(timezone.utc) - timedelta(hours=5)).isoformat()
    for mid in ("m000", "m001"):
        for s in main.get_sources_for_match(
                db.execute("SELECT * FROM matches WHERE id=?", (mid,)).fetchone()):
            db.execute("INSERT INTO highlight_cache VALUES (?, ?, '[]', ?)", (mid, s["id"], old))
    db.commit()
    monkeypatch.setattr(main, "PREFETCH_MAX_MATCHES", 1)
    assert _round(monkeypatch) == {"Team 2"}          # היחיד שלא נבדק מעולם


def test_the_cap_still_holds(db, monkeypatch):
    """התקרה קיימת כדי לא להציף את המקורות בסבב אחד."""
    _many(db, main.PREFETCH_MAX_MATCHES + 12)
    assert len(_round(monkeypatch)) == main.PREFETCH_MAX_MATCHES
