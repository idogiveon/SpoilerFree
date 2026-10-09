"""הבונדסליגה מעלה תקציר של דקה בערב המשחק, ואת המלא יום-יומיים אחרי.

מהמשתמש (26.9.26): באיירן–אוניון ברלין ממחזור 4 הציע רק את הקצר. בערוץ
יש "The Kane and Olise Late Night Show 🔥 | FC BAYERN - UNION BERLIN |
Highlights" באורך 4:04, שעלה יומיים אחרי המשחק.

הסיבה: הרקע לא חזר לעולם למשחק שכבר נמצא בו תקציר (`needs_check`
החזיר False ברגע שנמצא), והבדיקה החוזרת שכן מחפשת גרסה מלאה חלה רק על
מי שבמקרה פתח את המשחק בשלושת הימים שאחרי המציאה.
"""
import json
from datetime import datetime, timedelta, timezone

import main

SHORT = [{"video_id": "SHORT1", "label": "תקציר", "extended": False}]
BOTH = [{"video_id": "SHORT1", "label": "תקציר קצר", "extended": False},
        {"video_id": "LONG1", "label": "תקציר מלא", "extended": True}]


def _match(db, mid="bl1", days_ago=2):
    kick = datetime.now(timezone.utc) - timedelta(days=days_ago)
    db.execute("INSERT INTO matches (id, league_key, home_team, away_team, date_utc, "
               "time_utc, status) VALUES (?, 'bundesliga', 'Bayern Munich', "
               "'Union Berlin', ?, ?, 'FINISHED')",
               (mid, kick.strftime("%Y-%m-%d"), kick.strftime("%H:%M:%S")))
    db.commit()


def _cache(db, mid, videos, hours_ago):
    when = (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat()
    db.execute("INSERT OR REPLACE INTO highlight_cache VALUES (?,?,?,?)",
               (mid, "bundesliga_official", json.dumps(videos), when))
    db.commit()


def _cached(db, mid="bl1"):
    row = db.execute("SELECT videos_json FROM highlight_cache WHERE match_id=?",
                     (mid,)).fetchone()
    return json.loads(row["videos_json"]) if row else None


def _round(monkeypatch, found):
    calls = []
    monkeypatch.setattr(main, "search_youtube",
                        lambda **kw: calls.append(kw) or found)
    monkeypatch.setattr(main, "_web_link", lambda row, w: None)
    main.prefetch_highlights_once()
    return calls


def test_the_background_goes_back_for_the_full_version(db, monkeypatch):
    _match(db)
    _cache(db, "bl1", SHORT, hours_ago=20)
    assert _round(monkeypatch, BOTH), "הרקע לא חזר למשחק שיש בו רק תקציר קצר"
    assert [v["video_id"] for v in _cached(db)] == ["SHORT1", "LONG1"]


def test_it_does_not_go_back_once_the_full_version_is_there(db, monkeypatch):
    _match(db)
    _cache(db, "bl1", BOTH, hours_ago=20)
    assert _round(monkeypatch, BOTH) == []


def test_it_does_not_check_twice_in_twelve_hours(db, monkeypatch):
    """הבדיקה היא חינם (RSS), אבל לא סיבה לבדוק בכל סבב."""
    _match(db)
    _cache(db, "bl1", SHORT, hours_ago=2)
    assert _round(monkeypatch, BOTH) == []


def test_it_gives_up_when_the_highlight_can_no_longer_appear(db, monkeypatch):
    _match(db, days_ago=main.HIGHLIGHT_MAX_DAYS + 2)
    _cache(db, "bl1", SHORT, hours_ago=24 * (main.HIGHLIGHT_MAX_DAYS + 1))
    assert _round(monkeypatch, BOTH) == []


def test_the_recheck_is_free_only(db, monkeypatch):
    """בדיקה חוזרת היא RSS/רשימת העלאות בלבד — לא חיפוש ב-100 יחידות."""
    _match(db)
    _cache(db, "bl1", SHORT, hours_ago=20)
    calls = _round(monkeypatch, BOTH)
    assert calls and all(c.get("free_only") for c in calls)


def test_a_user_opening_it_later_in_the_week_also_gets_the_full_one(db, monkeypatch):
    """החלון בפתיחה של משתמש היה שלושה ימים; התקציר המלא של מחזור שנפתח
    בסוף השבוע נשאר מחוץ לו."""
    _match(db, days_ago=5)
    _cache(db, "bl1", SHORT, hours_ago=24 * 4)
    monkeypatch.setattr(main, "search_youtube", lambda **kw: BOTH)
    row = db.execute("SELECT * FROM matches WHERE id='bl1'").fetchone()
    src = main.LEAGUES["bundesliga"]["sources"][0]
    out = main._source_highlights(row, src)
    assert [v["video_id"] for v in out["videos"]] == ["SHORT1", "LONG1"]


# ── התווית: מהצילום של המשתמש (2.10.26) ─────────────────────────────
TITLE = "The Kane and Olise Late Night Show | FC BAYERN - UNION BERLIN | Highlights"


def _search(monkeypatch, feed, durs):
    monkeypatch.setattr(main, "_rss_feed", lambda cid: feed)
    monkeypatch.setattr(main, "_video_durations", lambda ids: durs)
    monkeypatch.setattr(main, "_is_short", lambda vid: False)
    return main.search_youtube("Bayern Munich", "Union Berlin", "2026-09-18",
                               "UC6UL29enLNe4mqwTfAyeNuw") or []


def _item(vid):
    return (vid, TITLE, "2026-09-20T20:00:00+00:00")


def test_a_single_candidate_is_just_highlights(monkeypatch):
    """ניסיתי לתייג מועמד יחיד לפי המשך ("קצר"/"ארוך"), כדי שהמשתמש
    ידע מה הוא מקבל. בפועל זה בלבל: תקציר יחיד של ערוץ ישראלי הופיע
    כ"תקציר ארוך" בלי שקיימת גרסה שנייה בכלל (הבעלים, 9.10.26).
    כשאין במה לבחור, התווית לא מוסיפה מידע."""
    for dur in (244, 62):
        assert [v["label"] for v in _search(monkeypatch, [_item("X")], {"X": dur})] \
            == ["תקציר"], dur


def test_without_a_duration_it_does_not_guess(monkeypatch):
    """הגרידה מדף הסרטון יכולה להיכשל — ואז אנחנו לא יודעים, ולא ממציאים."""
    assert [v["label"] for v in _search(monkeypatch, [_item("X")], {})] == ["תקציר"]


def test_when_both_are_there_nothing_changed(monkeypatch):
    out = _search(monkeypatch, [_item("SHORT"), _item("LONG")],
                  {"SHORT": 62, "LONG": 244})
    assert [v["label"] for v in out] == ["תקציר קצר", "תקציר מלא"]
    assert [v["extended"] for v in out] == [False, True]


def test_an_old_cached_label_does_not_survive_on_screen():
    """התווית נשמרת ב-videos_json, ולכן משחקים שנבדקו לפני השינוי
    נושאים עדיין "תקציר מלא" — והמשתמש ראה "תקציר ארוך" על מקור עם
    אפשרות אחת (הבעלים, 9.10.26). ההכרעה עברה לרגע התצוגה, כך שגם
    שורות ישנות מתוקנות בלי לגעת בקאש."""
    html = open("index.html", encoding="utf-8").read()
    assert "const kindLabel = (v, alone) => (alone && !v.extended) ? t('kind_regular')" in html
    assert "kindLabel(v, source.videos.length === 1)" in html


def test_a_lone_extended_video_still_says_long():
    """כשהמנהלת העלתה רק "תקציר מורחב", הכפתור אמר "תקציר" והפנה
    לגרסה הארוכה. הכלל "אחד = תקציר" חל רק כשההבחנה הוסקה מהמשך;
    כותרת שאומרת "מורחב" היא עובדה מהמקור (הבעלים, 9.10.26)."""
    html = open("index.html", encoding="utf-8").read()
    assert "(alone && !v.extended)" in html


def test_the_server_marks_an_extended_title(monkeypatch):
    out = _search(monkeypatch,
                  [("LONG", 'מחזור 5 | תקציר מורחב: מכבי חיפה - עירוני טבריה 2-3',
                    "2026-09-22T10:00:00+00:00")], {"LONG": 400})
    assert [(v["label"], v["extended"]) for v in out] == [("תקציר מורחב", True)]
