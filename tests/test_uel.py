"""ליגה אירופית: לוח מ-TheSportsDB, ערוצי מועדונים, ספורט 5, שמות בעברית."""
import main

# 36 הקבוצות של שלב הליגה (TheSportsDB, מחזורים 1–2, 13.9.26)
UEL_TEAMS = [
    "AC Milan", "AZ Alkmaar", "Anderlecht", "Ararat-Armenia", "Bayer Leverkusen", "Benfica", "Beşiktaş",
    "Bournemouth", "Celje", "Celta Vigo", "Celtic", "Crystal Palace", "Dinamo Zagreb", "Ferencváros",
    "Hapoel Be'er Sheva", "Hoffenheim", "Jagiellonia Białystok", "Juventus", "Lech Poznań", "Levski Sofia",
    "Lillestrøm", "Lyon", "Marseille", "NEC Nijmegen", "OFI", "Olympiacos", "Omonia Nicosia",
    "Real Sociedad", "Red Bull Salzburg", "Rennes", "Sparta Prague", "Sturm Graz", "Sunderland",
    "Torreense", "Union Saint-Gilloise", "Viktoria Plzeň",
]


def test_uel_config():
    cfg = main.LEAGUES["uel"]
    assert cfg["sportsdb_ids"] == ["4481"] and cfg["min_date"] == "2026-09-01"
    assert all(t in UEL_TEAMS for t in cfg["club_channels"])


def test_every_uel_team_has_a_hebrew_name():
    english = [t for t in UEL_TEAMS if main.display_team(t, "he") == t]
    assert english == []
    assert main.display_team("Lillestrøm", "he") == "לילסטרום"     # לא "ליל" (התאמה חלקית)


def _row(home, away):
    return {"league_key": "uel", "home_team": home, "away_team": away,
            "home_team_id": None, "away_team_id": None}


def test_sources():
    assert main.get_sources_for_match(_row("Hapoel Be'er Sheva", "Dinamo Zagreb")) == []
    assert [s["club_team"] for s in main.get_sources_for_match(_row("Celtic", "Ferencváros"))] == ["Celtic"]


def test_beer_sheva_sport5_link(monkeypatch):
    class Resp:
        status_code = 200
        text = ('<a href="https://www.sport5.co.il/articles.aspx?FolderID=400&amp;docID=1">'
                'לילה אירופי: הפועל ב&quot;ש ניצחה 1:2 את דינמו זאגרב</a>')
    main._site_cache.clear()
    monkeypatch.setattr(main.requests, "get", lambda url, **k: Resp())
    w = main.LEAGUES["uel"]["web_sources"][0]
    url = main.find_web_highlight(w["scrape_pages"], w["link_pattern"],
                                  main._he_names("Hapoel Be'er Sheva"), main._he_names("Dinamo Zagreb"),
                                  base=w["base"])
    assert url == "https://www.sport5.co.il/articles.aspx?FolderID=400&docID=1"
