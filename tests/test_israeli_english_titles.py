"""הערוצים הישראליים עברו לכותרות באנגלית — עדיין שתי הקבוצות, עדיין לא משחק מלא.
כותרות אמיתיות מהערוצים (18.9.26)."""
import main

PIRATE = next(s for s in main.LEAGUES["israel"]["sources"] if s["id"] == "yt_footballyom1")
IPFL = next(s for s in main.LEAGUES["israel"]["sources"] if s["id"] == "ipfl")

FEED = [
    ("en_right", "Hapoel Be'er Sheva vs. Hapoel Petah Tikva 2-0 Match Highlights",
     "2026-09-16T21:00:00+00:00"),
    ("en_other", "Beitar Jerusalem vs. Maccabi Petah Tikva 3-1 Match Highlights",
     "2026-09-16T21:00:00+00:00"),
    ("he_old", "מכבי נתניה נגד הפועל רמת גן 2-0 תקציר המשחק", "2026-09-16T21:00:00+00:00"),
    ("goals_only", "Only Goals: All the goals from Matchday 4 of the Winner League",
     "2026-09-16T21:00:00+00:00"),
]


def _search(monkeypatch, home, away, src=PIRATE, feed=FEED, date="2026-09-16"):
    monkeypatch.setattr(main, "_rss_feed", lambda cid: feed)
    monkeypatch.setattr(main, "_video_durations", lambda ids: {})
    return main.search_youtube(home, away, date, src["channel_id"],
                               title_exclude=src.get("title_exclude"),
                               home_alt=main.to_hebrew_team(home), away_alt=main.to_hebrew_team(away),
                               il_both=True)


def test_english_title_is_found(monkeypatch):
    res = _search(monkeypatch, "Hapoel Be'er Sheva", "Hapoel Petah Tikva")
    assert [v["video_id"] for v in res] == ["en_right"]


def test_hebrew_titles_still_work(monkeypatch):
    res = _search(monkeypatch, "Maccabi Netanya", "Hapoel Ramat Gan")
    assert [v["video_id"] for v in res] == ["he_old"]


def test_another_match_is_never_taken(monkeypatch):
    assert _search(monkeypatch, "Maccabi Haifa", "Hapoel Tel-Aviv") == []


def test_goals_roundup_is_not_a_match_highlight(monkeypatch):
    """"Only Goals" מכסה את כל המחזור — לא תקציר של משחק מסוים."""
    res = _search(monkeypatch, "Hapoel Be'er Sheva", "Hapoel Petah Tikva")
    assert "goals_only" not in [v["video_id"] for v in res]


def test_official_channel_english_full_match_is_excluded(monkeypatch):
    feed = [("full_en", "Matchday 4 | Full Match: Ironi Tiberias vs. Hapoel Jerusalem 2-2",
             "2026-09-16T21:00:00+00:00"),
            ("hl_en", "Matchday 4 | Highlights: Ironi Tiberias - Hapoel Jerusalem 2-2",
             "2026-09-16T21:05:00+00:00")]
    res = _search(monkeypatch, "Ironi Tiberias", "Hapoel Jerusalem", src=IPFL, feed=feed)
    assert [v["video_id"] for v in res] == ["hl_en"]
    assert "full match" in [x.lower() for x in IPFL["title_exclude"]]
