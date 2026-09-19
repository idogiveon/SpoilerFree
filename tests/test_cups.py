"""גביעים: קאראבאו, אנגלי, גרמני, ספרדי וצרפתי.
הכותרות כאן אמיתיות, מהערוצים עצמם (19.9.26)."""
import re

import main

CUPS = ("carabao", "facup", "dfbpokal", "copadelrey", "coupedefrance")


def _src(league_key, source_id):
    return next(s for s in main.LEAGUES[league_key]["sources"] if s["id"] == source_id)


def _keeps(league_key, source_id, title, home, away):
    """האם המקור הזה היה מקבל את הכותרת הזו למשחק הזה."""
    src = _src(league_key, source_id)
    tl = title.lower()
    if any(x.lower() in tl for x in src.get("title_exclude", [])):
        return False
    if not any(x.lower() in tl for x in src.get("title_include", [])):
        return False
    return main.is_match_highlight(title, home, away)


def test_every_cup_is_configured():
    for key in CUPS:
        lg = main.LEAGUES[key]
        assert lg["cup"] is True, key
        assert lg["source"] == "sportsdb" and lg["sportsdb_ids"], key


def test_cup_rounds_are_stages_not_matchdays():
    """המספר הוא כמה קבוצות נשארו, ולכן הדפדוף חייב סדר כרונולוגי
    מפורש: אחרי שלב 32 בא 16, ואז 125 (רבע), 150 (חצי), 200 (גמר)."""
    html = open("index.html", encoding="utf-8").read()
    block = html[html.index("const SPORTSDB_LEAGUES"):]
    block = block[:block.index("};")]
    for key in CUPS:
        m = re.search(key + r":\s*\{.*?rounds:\s*\[([^\]]*)\]", block, re.S)
        assert m, key
        rounds = [int(x) for x in re.findall(r"\d+", m.group(1))]
        assert rounds[-3:] == [125, 150, 200], key
        assert rounds == sorted(set(rounds), key=rounds.index), key
    # ליגה רגילה נשארת בלי שלבים — היא נבנית כ-1..N
    assert "rounds:" not in re.search(r"championship:.*?\n", block).group(0)


def test_english_cups_reuse_the_club_channels_we_already_verified():
    for key in ("carabao", "facup"):
        cc = main.LEAGUES[key]["club_channels"]
        assert len(cc) >= 40, key
        # מהפרמייר ומהצ'מפיונשיפ, בלי שכפול מזהי ערוצים
        assert cc["Manchester City"] == "UCkzCjdRMrW2vXLx8mvPVLdQ", key
        assert cc["Norwich City"] == main.LEAGUES["championship"]["club_channels"]["Norwich City"]


def test_club_channel_is_found_despite_a_different_spelling(db):
    """sportsdb כותב "Brighton and Hove Albion", אצלנו "Brighton & Hove Albion FC"."""
    db.execute("INSERT INTO matches (id, league_key, home_team, away_team, date_utc, "
               "time_utc, status) VALUES ('c1', 'carabao', 'Brighton and Hove Albion', "
               "'Bournemouth', '2026-09-17', '20:00:00', 'FINISHED')")
    db.commit()
    row = db.execute("SELECT * FROM matches WHERE id='c1'").fetchone()
    srcs = main.get_sources_for_match(row)
    assert sorted(s["club_team"] for s in srcs if s.get("club_team")) == \
        ["Bournemouth", "Brighton and Hove Albion"]
    # ואחרי ערוצי המועדונים — הערוץ של הגביע
    assert srcs[-1]["id"] == "efl_cup"


def test_real_cup_titles_are_matched():
    assert _keeps("carabao", "efl_cup",
                  "DEBUTANTS SHINE! | Manchester City v Norwich City Carabao Cup Extended Highlights",
                  "Manchester City", "Norwich City")
    assert _keeps("facup", "fa_cup",
                  "INCREDIBLE Late Drama! 🤯 | Knowle FC v Worcester City | Key Moments | Emirates FA Cup 2027",
                  "Knowle FC", "Worcester City")
    assert _keeps("dfbpokal", "german_football",
                  "Kane & Olise counter screamer! | VfL Osnabrück vs FC Bayern München 1-4 | Highlights | DFB-Pokal",
                  "Osnabrück", "Bayern Munich")
    assert _keeps("copadelrey", "rfef",
                  "Resumen Final #CopaDelReyMAPFRE | Atlético de Madrid - Real Sociedad",
                  "Atlético Madrid", "Real Sociedad")


def test_the_same_channel_league_videos_are_not_taken_as_cup():
    """ערוץ ה-EFL מעלה גם ליגה. בלי שם הגביע בכותרת, משחק ליגה בין אותן
    שתי קבוצות היה מוצג כתקציר של משחק הגביע."""
    assert not _keeps("carabao", "efl_cup", "Bristol City v Watford Highlights",
                      "Bristol City", "Watford")
    assert not _keeps("copadelrey", "rfef",
                      "Resumen #PrimeraFederación | UD Logroñés 1-1 Pontevedra CF | Jornada 4",
                      "Logroñés", "Pontevedra")


def test_other_competitions_on_the_fa_cup_channel_are_excluded():
    """מגן הקהילה והמשחק המלא עולים באותו ערוץ, עם אותן שתי קבוצות."""
    for title in ("Christos Tzolis: The Assist King 👑 | Arsenal v Manchester City | FA Community Shield 2026",
                  "FULL MATCH | Arsenal v Manchester City | FA Community Shield 2026"):
        assert not _keeps("facup", "fa_cup", title, "Arsenal", "Manchester City")


def test_cup_rounds_never_spend_paid_quota_in_the_background():
    """סיבוב מוקדם בגביע = עד 50 משחקי חובבים. התקציב שייך לליגות."""
    src = open("main.py", encoding="utf-8").read()
    guard = src[src.index("is_cup = LEAGUES.get"):]
    assert "paid_ok = _yt_units_today() < PREFETCH_UNIT_BUDGET and not is_cup" in guard[:400]


def test_france_has_no_central_channel_only_clubs():
    """נבדק: ההתאחדות הצרפתית מעלה נבחרות בלבד. מארסיי ורן מעלים בעצמם."""
    assert not main.LEAGUES["coupedefrance"].get("sources")
    cc = main.LEAGUES["coupedefrance"]["club_channels"]
    assert cc["Marseille"] == main.LEAGUES["uel"]["club_channels"]["Marseille"]
    assert cc["Rennes"] == main.LEAGUES["uel"]["club_channels"]["Rennes"]
