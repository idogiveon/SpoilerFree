"""ערוץ המנהלת: רק המשחק שנפתח. 16.9.26 הוצגו שם תקצירים של משחקים אחרים."""
import main

IPFL = next(s for s in main.LEAGUES["israel"]["sources"] if s["id"] == "ipfl")

# כותרות אמיתיות מהערוץ (16.9.26)
FEED = [("full", 'מחזור 4 | המשחק המלא: בית"ר ירושלים - מכבי פ"ת 1-3', "2026-09-16T20:00:00+00:00"),
        ("short", 'מחזור 4 | תקציר: בית"ר ירושלים - מכבי פ"ת 1-3', "2026-09-16T20:05:00+00:00"),
        ("ext", 'מחזור 4 | תקציר מורחב: בית"ר ירושלים - מכבי פ"ת 1-3', "2026-09-16T20:10:00+00:00"),
        ("other", 'מחזור 4 | תקציר: מכבי ת"א - הפועל ת"א 1-4', "2026-09-15T20:00:00+00:00")]


def _search(monkeypatch, home, away, date="2026-09-16"):
    monkeypatch.setattr(main, "_rss_feed", lambda cid: FEED)
    monkeypatch.setattr(main, "_video_durations", lambda ids: {"short": 120, "ext": 400, "full": 5400})
    return main.search_youtube(home, away, date, IPFL["channel_id"],
                               title_exclude=IPFL.get("title_exclude"),
                               home_alt=main.to_hebrew_team(home), away_alt=main.to_hebrew_team(away),
                               il_both=IPFL["il_both_teams"])


def test_official_sources_require_both_teams():
    src = {s["id"]: s for s in main.LEAGUES["israel"]["sources"]}
    assert all(src[i].get("il_both_teams") for i in ("sport1", "sport5", "ipfl"))


def test_only_the_right_match_and_not_the_full_game(monkeypatch):
    res = _search(monkeypatch, "Beitar Jerusalem", "Maccabi Petah Tikva")
    assert [v["video_id"] for v in res] == ["short", "ext"]      # קצר + מורחב, בלי המשחק המלא


def test_another_match_gets_nothing(monkeypatch):
    """הפועל ב"ש–הפועל פ"ת קיבל את התקצירים של חיפה–סכנין ומכבי ת"א–הפועל ת"א."""
    assert _search(monkeypatch, "Hapoel Be'er Sheva", "Hapoel Petah Tikva") == []


def test_wrong_saved_results_are_cleared_once(db):
    db.execute("INSERT INTO matches (id, league_key, home_team, away_team, date_utc, time_utc, status) "
               "VALUES ('il9', 'israel', 'Hapoel Be''er Sheva', 'Hapoel Petah Tikva', "
               "'2026-09-16', '18:00:00', 'FINISHED')")
    db.execute("INSERT INTO highlight_cache VALUES ('il9', 'ipfl', '[{\"video_id\": \"wrong\"}]', '2026-09-16')")
    db.execute("DELETE FROM meta WHERE key='israel_cache_v2'")
    db.commit()
    main.init_db()
    assert db.execute("SELECT COUNT(*) AS n FROM highlight_cache").fetchone()["n"] == 0
    assert db.execute("SELECT 1 FROM meta WHERE key='israel_cache_v2'").fetchone()
