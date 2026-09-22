"""ליגת העל: ערוצי יוטיוב לא רשמיים — רק "תקציר" + שתי הקבוצות בשם מלא."""
import main

PIRATE_IDS = ["UC5TtVDq_BSplSOHf7lb2AGQ", "UCm8OkQc5lHJE29ADWkbB7CQ", "UCUEeo-8_3zovErCSQb58dnw"]


def ok(title, home, away, published="", match_date=""):
    return main.is_il_both_teams(title, main.to_hebrew_team(home), main.to_hebrew_team(away),
                                 published, match_date)


def test_sources_after_official_ones():
    src = main.LEAGUES["israel"]["sources"]
    assert [s["id"] for s in src[:3]] == ["sport1", "sport5", "ipfl"]
    pirate = src[3:]
    assert [s["channel_id"] for s in pirate] == PIRATE_IDS
    # ההטמעה נקבעת מרכזית (EMBED_IN_APP), לא לכל מקור בנפרד
    assert all(s["il_both_teams"] and "allow_embed" not in s for s in pirate)


def test_real_titles():
    """כותרות אמיתיות מה-RSS של שלושת הערוצים (13.9.26)."""
    assert ok("הפועל באר שבע נגד מכבי תל אביב 4-1 תקציר המשחק", "Hapoel Be'er Sheva", "Maccabi Tel Aviv")
    assert ok("מכבי חיפה נגג הפועל פתח תקווה 1-2 תקציר המשחק", "Maccabi Haifa", "Hapoel Petah Tikva")
    assert ok("הפועל תל אביב נגד ביתר ירושלים 0-3 תקציר המשחק", "Hapoel Tel-Aviv", "Beitar Jerusalem")
    assert ok('תקציר המשחק בני סכנין מול בית"ר ירושלים 1-0', "Bnei Sakhnin", "Beitar Jerusalem")
    assert ok("הפועל תל אביב נגד בית''ר ירושלים תקציר", "Hapoel Tel-Aviv", "Beitar Jerusalem")
    assert ok("עירוני קרית שמונה נגד עירוני טבריה תקציר", "Hapoel Ironi Kiryat Shmona", "Ironi Tiberias")
    # בלי המילה "תקציר" — התוצאה מספיקה
    assert ok("הפועל תל אביב נגד בית''ר ירושלים 0-3", "Hapoel Tel-Aviv", "Beitar Jerusalem")


def test_reversed_order_is_fine():
    assert ok("מכבי תל אביב נגד הפועל באר שבע תקציר", "Hapoel Be'er Sheva", "Maccabi Tel Aviv")


def test_rejects_wrong_or_partial():
    # מכבי ת"א ≠ הפועל ת"א
    assert not ok("הפועל באר שבע נגד מכבי תל אביב 4-1 תקציר המשחק", "Hapoel Be'er Sheva", "Hapoel Tel-Aviv")
    # קבוצה אחת בלבד (משחק אירופי)
    assert not ok("הפועל תל אביב נגד אטאלנטה תקציר", "Hapoel Tel-Aviv", "Maccabi Haifa")
    # בלי "תקציר" — שערים / ראיון
    assert not ok("כל השערים: הפועל באר שבע נגד מכבי תל אביב", "Hapoel Be'er Sheva", "Maccabi Tel Aviv")


def test_rematch_weeks_later_not_taken():
    t = "מכבי חיפה נגד הפועל פתח תקווה תקציר"
    assert ok(t, "Maccabi Haifa", "Hapoel Petah Tikva", "2026-09-14T20:00:00+00:00", "2026-09-13")
    assert not ok(t, "Maccabi Haifa", "Hapoel Petah Tikva", "2026-11-02T20:00:00+00:00", "2026-09-13")


def test_search_youtube_uses_strict_rule(monkeypatch):
    feed = [("v1", "הפועל תל אביב נגד מכבי חיפה תקציר", "2026-09-13T21:00:00+00:00"),
            ("v2", "מכבי תל אביב נגד מכבי חיפה תקציר", "2026-09-13T21:30:00+00:00")]
    monkeypatch.setattr(main, "_rss_feed", lambda cid: feed)
    monkeypatch.setattr(main, "_video_durations", lambda ids: {})
    res = main.search_youtube("Maccabi Tel Aviv", "Maccabi Haifa", "2026-09-13", PIRATE_IDS[0],
                              home_alt=main.to_hebrew_team("Maccabi Tel Aviv"),
                              away_alt=main.to_hebrew_team("Maccabi Haifa"), il_both=True)
    assert [v["video_id"] for v in res] == ["v2"]
