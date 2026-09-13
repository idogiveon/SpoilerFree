"""קישורים ישירים לספורט 1 / ספורט 5 — מעמודי האתר, בלי מנוע חיפוש."""
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

import main

SPORT1_HTML = """
<a href="/israeli-soccer/ligat-haal/video/1943700/">צפו: ברוניניו בישל וכבש שער אדיר, מכבי חיפה ניצחה 1:2 את הפועל פ&quot;ת</a>
<a href="/israeli-soccer/ligat-haal/video/1943650/">05:51 תקציר: הפועל באר שבע – מכבי תל אביב 4:1</a>
<a href="/israeli-soccer/ligat-haal/video/1943640/">צפו: שער אדיר של באר שבע מול מכבי תל אביב</a>
<a href="/other/">הפועל באר שבע מכבי תל אביב</a>
"""
SPORT5_HTML = """
<a href="https://vod.sport5.co.il/?Vc=893&amp;Vi=560293">מנצ`סטר יונייטד חזרה לאלופות עם 0:4 על סבאח</a>
<a href="https://vod.sport5.co.il/?Vc=893&amp;Vi=560294">לא כוחות: 0:5 ענק לבאיירן על בודה גלימט</a>
"""


def test_slash_names_match_by_part(monkeypatch):
    """ספורט 5 כותבים "בודה גלימט"; אצלנו "בודו/גלימט" — "גלימט" מספיק."""
    _pages(monkeypatch, {"sport5": SPORT5_HTML})
    cfg = main.LEAGUES["ucl"]["web_sources"][0]
    url = main.find_web_highlight(cfg["scrape_pages"], cfg["link_pattern"],
                                  main._he_names("Bayern Munich"), main._he_names("Bodø/Glimt"))
    assert url == "https://vod.sport5.co.il/?Vc=893&Vi=560294"


class Resp:
    def __init__(self, text):
        self.status_code, self.text = 200, text


def _pages(monkeypatch, html_by_host):
    main._site_cache.clear()

    def fake_get(url, **k):
        for host, html in html_by_host.items():
            if host in url:
                return Resp(html)
        return Resp("")
    monkeypatch.setattr(main.requests, "get", fake_get)


def test_sport1_quote_entity_no_longer_breaks_match(monkeypatch):
    """הבאג שנמצא: 'הפועל פ&quot;ת' לא פוענח, והתקציר של חיפה–פ"ת לא נמצא."""
    _pages(monkeypatch, {"sport1": SPORT1_HTML})
    url = main.scrape_sport1_vod("מכבי חיפה", "הפועל פתח תקווה")
    assert url == "https://sport1.maariv.co.il/israeli-soccer/ligat-haal/video/1943700/"


def test_sport1_prefers_highlights_over_clip(monkeypatch):
    _pages(monkeypatch, {"sport1": SPORT1_HTML})
    url = main.scrape_sport1_vod("הפועל באר שבע", "מכבי תל אביב")
    assert url.endswith("/video/1943650/")


def test_israeli_names_are_strict(monkeypatch):
    """"הפועל"/"אביב" לבד לא מזהים קבוצה — מכבי ת"א–מכבי חיפה ≠ הפועל ת"א–מכבי חיפה."""
    _pages(monkeypatch, {"sport1": '<a href="/x/video/1/">תקציר: מכבי תל אביב - מכבי חיפה 2:1</a>'
                                   '<a href="/x/video/2/">צפו: הפועל ת&quot;א גברה על מכבי חיפה</a>'})
    assert main.scrape_sport1_vod("הפועל תל אביב", "מכבי חיפה").endswith("/video/2/")
    assert main.scrape_sport1_vod("הפועל באר שבע", "מכבי חיפה") is None


def test_sport5_backtick_geresh_and_display_names(monkeypatch):
    _pages(monkeypatch, {"sport5": SPORT5_HTML})
    cfg = main.LEAGUES["ucl"]["web_sources"][0]
    url = main.find_web_highlight(cfg["scrape_pages"], cfg["link_pattern"],
                                  main._he_names("Manchester United"), main._he_names("Sabah Baku"))
    assert url == "https://vod.sport5.co.il/?Vc=893&Vi=560293"


def test_short_hebrew_names_match_whole_words_only():
    assert main._he_contains("ניס", "ניצחון ענק לניס על מונאקו")
    assert not main._he_contains("ניס", "ניסיון ראשון של המאמן")
    assert not main._he_contains("ליל", "ערב מטורף בלילה של האלופות")
    assert main._he_contains("ליל", "תיקו בליל, 1:1")
    assert main._he_contains("ראן", "0:1 קשה לראן על מארסיי")
    assert main._he_contains("מארסיי", "0:1 קשה לראן על מארסיי")      # ארוך — הכלה רגילה


def test_paris_fc_is_not_psg():
    assert main.display_team("Paris FC", "he") == "פריז FC"
    assert main.to_hebrew_team("Paris FC") == "פריז FC"
    assert main._he_names("Paris FC") == ["פריז FC"]
    assert "פריז FC" not in main._he_names("Paris Saint-Germain")


def test_ligue1_sport5_article_link(monkeypatch):
    _pages(monkeypatch, {"sport5": '<a href="https://www.sport5.co.il/articles.aspx?FolderID=496&amp;docID=560450">'
                                   'עלתה זמנית לפסגה: 0:1 קשה לראן על מארסיי</a>'
                                   '<a href="/articles.aspx?FolderID=1&amp;docID=2">כתבה אחרת על ליון</a>'})
    cfg = main.LEAGUES["ligue1"]["web_sources"][0]
    url = main.find_web_highlight(cfg["scrape_pages"], cfg["link_pattern"],
                                  main._he_names("Rennes"), main._he_names("Marseille"), base=cfg["base"])
    assert url == "https://www.sport5.co.il/articles.aspx?FolderID=496&docID=560450"


def test_page_without_charset_is_read_as_utf8(monkeypatch):
    """דף הבית של ספורט 5: בלי charset — requests מפענח latin-1 (ג'יבריש)."""
    html = '<a href="https://vod.sport5.co.il/?Vc=1&amp;Vi=9">מנצ`סטר יונייטד חזרה לאלופות עם 0:4 על סבאח</a>'

    class Latin1Resp:
        status_code = 200
        content = html.encode("utf-8")
        text = content.decode("latin-1")          # מה ש-requests היה נותן

    main._site_cache.clear()
    monkeypatch.setattr(main.requests, "get", lambda url, **k: Latin1Resp())
    url = main.find_web_highlight(["https://www.sport5.co.il/"], main.SPORT5_LINK,
                                  main._he_names("Manchester United"), main._he_names("Sabah Baku"))
    assert url == "https://vod.sport5.co.il/?Vc=1&Vi=9"


def test_no_direct_link_means_no_button(monkeypatch, db):
    _pages(monkeypatch, {})
    monkeypatch.setattr(main, "search_youtube", lambda *a, **k: [])
    past = datetime.now(timezone.utc) - timedelta(hours=20)
    db.execute("INSERT INTO matches (id, league_key, home_team, away_team, date_utc, time_utc, status) "
               "VALUES ('i1', 'israel', 'Maccabi Haifa', 'Hapoel Petah Tikva', ?, ?, 'FINISHED')",
               (past.strftime("%Y-%m-%d"), past.strftime("%H:%M:%S")))
    db.commit()
    res = TestClient(main.app).get("/highlights/i1").json()
    assert res["web_links"] == []
    assert "duckduckgo" not in str(res)


def test_direct_link_shown_and_cached(monkeypatch, db):
    _pages(monkeypatch, {"sport1": SPORT1_HTML})
    monkeypatch.setattr(main, "search_youtube", lambda *a, **k: [])
    past = datetime.now(timezone.utc) - timedelta(hours=20)
    db.execute("INSERT INTO matches (id, league_key, home_team, away_team, date_utc, time_utc, status) "
               "VALUES ('i2', 'israel', 'Maccabi Haifa', 'Hapoel Petah Tikva', ?, ?, 'FINISHED')",
               (past.strftime("%Y-%m-%d"), past.strftime("%H:%M:%S")))
    db.commit()
    c = TestClient(main.app)
    links = c.get("/highlights/i2").json()["web_links"]
    assert links == [{"name": "ספורט 1",
                      "url": "https://sport1.maariv.co.il/israeli-soccer/ligat-haal/video/1943700/"}]
    _pages(monkeypatch, {})                                   # האתר "נעלם" — מהקאש
    assert c.get("/highlights/i2").json()["web_links"] == links
