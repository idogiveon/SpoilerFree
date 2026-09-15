"""בחירת התקציר הנכון — מקרים אמיתיים מ-15.9.26 (ONE, LALIGA, בונדסליגה)."""
import main

REAL_PROBE = main._probe_short          # לפני שה-conftest מחליף
REAL_SCRAPE = main._scrape_durations


def _search(monkeypatch, feed, home, away, date, shorts=(), durs=None, **kw):
    monkeypatch.setattr(main, "_rss_feed", lambda cid: feed)
    monkeypatch.setattr(main, "_probe_short", lambda vid: vid in shorts)
    monkeypatch.setattr(main, "_video_durations", lambda ids: durs or {})
    return main.search_youtube(home, away, date, "UCx", **kw)


def test_one_real_highlight_found_and_news_short_dropped(monkeypatch):
    feed = [("D7T54aB-jX4", "אנתוני גורדון סיפר על ההתעניינות מברצלונה: “הסוכן אמר לי ואמרתי ‘כן כן, בסדר’",
             "2026-09-15T04:44:00+00:00"),
            ("fu0ja6UGV8E", "לאמין ובארסה חוגגים על חשבונה של לבאנטה שהצליחה רק לצמק |תקציר מורחב",
             "2026-09-14T02:30:00+00:00")]
    res = _search(monkeypatch, feed, "Levante", "Barcelona", "2026-09-13", shorts={"D7T54aB-jX4"},
                  durs={"fu0ja6UGV8E": 858}, home_alt=main.to_hebrew_team("Levante"),
                  away_alt=main.to_hebrew_team("Barcelona"), headline=True)
    assert [v["video_id"] for v in res] == ["fu0ja6UGV8E"]


def test_one_news_short_alone_is_not_a_highlight(monkeypatch):
    feed = [("D7T54aB-jX4", "אנתוני גורדון סיפר על ההתעניינות מברצלונה", "2026-09-15T04:44:00+00:00")]
    assert _search(monkeypatch, feed, "Levante", "Barcelona", "2026-09-13", shorts={"D7T54aB-jX4"},
                   headline=True) == []


def test_laliga_prefers_official_over_reel(monkeypatch):
    t = "LEVANTE UD 2 - 4 FC BARCELONA | RESUMEN LALIGA EA SPORTS"
    feed = [("J3MOWKbKWBQ", t, "2026-09-13T22:00:00+00:00"),        # רילז, עלה אחר כך
            ("te6eWlim9yU", t, "2026-09-13T16:35:00+00:00")]
    res = _search(monkeypatch, feed, "Levante", "Barcelona", "2026-09-13", shorts={"J3MOWKbKWBQ"},
                  durs={"te6eWlim9yU": 194})
    assert [v["video_id"] for v in res] == ["te6eWlim9yU"]


def test_only_a_reel_is_still_better_than_nothing(monkeypatch):
    feed = [("J3MOWKbKWBQ", "LEVANTE UD 2 - 4 FC BARCELONA | RESUMEN LALIGA EA SPORTS",
             "2026-09-13T22:00:00+00:00")]
    res = _search(monkeypatch, feed, "Levante", "Barcelona", "2026-09-13", shorts={"J3MOWKbKWBQ"})
    assert [v["video_id"] for v in res] == ["J3MOWKbKWBQ"]


BUNDES = [("h-BXJf4NXos", "Important Win for Bayern | SV ELVERSBERG - FC BAYERN | Highlights | Matchday 3",
           "2026-09-13T22:00:00+00:00"),
          ("Y-o6QafeHHw", "SV Elversberg vs. FC Bayern München | Matchday 3 - Bundesliga 2026/27",
           "2026-09-13T18:14:00+00:00"),
          ("foGJLCrMpjY", "First Goal of the Season for Kane | SV ELVERSBERG - FC BAYERN | Highlights | Matchday 3",
           "2026-09-13T18:04:00+00:00")]
BUNDES_DURS = {"h-BXJf4NXos": 244, "Y-o6QafeHHw": 8350, "foGJLCrMpjY": 64}


def test_bundesliga_short_and_full_both_offered(monkeypatch):
    res = _search(monkeypatch, BUNDES, "SV Elversberg", "Bayern Munich", "2026-09-13", durs=BUNDES_DURS)
    assert [(v["video_id"], v["label"]) for v in res] == [("foGJLCrMpjY", "תקציר קצר"),
                                                         ("h-BXJf4NXos", "תקציר מלא")]


def test_bundesliga_full_match_replay_never_picked(monkeypatch):
    early = BUNDES[1:]                                   # רק הקצר + שידור חוזר (לפני המלא)
    early = [(v, t.replace("Highlights", "") if v == "foGJLCrMpjY" else t, p) for v, t, p in early]
    res = _search(monkeypatch, early, "SV Elversberg", "Bayern Munich", "2026-09-13", durs=BUNDES_DURS)
    assert "Y-o6QafeHHw" not in [v["video_id"] for v in res]


def test_short_probe_and_cache(monkeypatch):
    class R:
        def __init__(self, code):
            self.status_code = code
    codes = {"s": 200, "r": 303}
    monkeypatch.setattr(main.requests, "head", lambda url, **k: R(codes[url.rsplit("/", 1)[1]]))
    assert REAL_PROBE("s") is True and REAL_PROBE("r") is False

    def boom(url, **k):
        raise TimeoutError()
    monkeypatch.setattr(main.requests, "head", boom)
    assert REAL_PROBE("x") is None
    monkeypatch.setattr(main, "_probe_short", lambda vid: None)
    assert main._is_short("x") is False and "x" not in main._short_cache   # לא נשמר — ינוסה שוב


def test_durations_without_api_key_come_from_the_video_page(monkeypatch):
    class R:
        text = '..."lengthSeconds":"64",...'
    monkeypatch.setattr(main.requests, "get", lambda url, **k: R())
    monkeypatch.setattr(main, "_scrape_durations", REAL_SCRAPE)
    assert main._video_durations(["foGJLCrMpjY"]) == {"foGJLCrMpjY": 64}
