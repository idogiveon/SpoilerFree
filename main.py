import sqlite3
from urllib.parse import quote, unquote

try:
    import libsql  # Turso — נטען רק אם מותקן; בלעדיו נופלים ל-sqlite מקומי
except ImportError:
    libsql = None
import requests
import re
import os
import json
import time
import hashlib
import hmac
import secrets
import smtplib
import threading
from email.message import EmailMessage
import unicodedata
from html import unescape as _unescape, escape as _html_escape
from fastapi import FastAPI, HTTPException, Request, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def _timing(request, call_next):
    """Server-Timing לכל תשובה (נראה ב-DevTools) + לוג לבקשות איטיות."""
    t0 = time.perf_counter()
    resp = await call_next(request)
    ms = (time.perf_counter() - t0) * 1000
    resp.headers["Server-Timing"] = f"app;dur={ms:.0f}"
    if ms > 1000:
        print(f"[slow] {request.method} {request.url.path} {ms:.0f}ms")
    return resp

DB_PATH = "database.db"
# שעון ישראל אמיתי (קיץ +3 / חורף +2, מעבר ב-25.10.26). היה offset קבוע +3 —
# מהחורף כל המשחקים היו מוצגים שעה מאוחר מדי.
ISRAEL_TZ = ZoneInfo("Asia/Jerusalem")

YOUTUBE_API_KEY   = os.environ.get("YOUTUBE_API_KEY", "")
FOOTBALL_DATA_KEY = os.environ.get("FOOTBALL_DATA_KEY", "")
APP_PASSWORD      = os.environ.get("APP_PASSWORD", "")

# Turso (DB בענן) — כששני המשתנים מוגדרים, ה-DB מסונכרן לענן ושורד deploys.
# בלעדיהם: sqlite מקומי רגיל (התנהגות ישנה) — האתר לעולם לא נשבר בגלל Turso.
TURSO_DATABASE_URL = os.environ.get("TURSO_DATABASE_URL", "")
TURSO_AUTH_TOKEN   = os.environ.get("TURSO_AUTH_TOKEN", "")

# ── League config ──────────────────────────────────────
# season 2026-27 (התחילה אוגוסט 2026). ארגנטינה — עונה קלנדרית 2026.
# allow_embed: False כברירת מחדל — רוב הערוצים חוסמים embed, פותחים בטאב חדש.
# channel_id ריק = מקור מוגדר אך ממתין לאיתור הערוץ (שלב 3).
# עמודי אתרים לקישורים ישירים (משמשים את web_sources למטה — חייבים להיות לפני LEAGUES)
SPORT1_PAGES = ["https://sport1.maariv.co.il/israeli-soccer/ligat-haal/video/",
                "https://sport1.maariv.co.il/vod/"]
SPORT1_LINK  = r"/video/\d+"
SPORT5_LINK  = r"vod\.sport5\.co\.il/\?[^'\"]*Vi=\d+"
# ליגות בלי VOD ייעודי באתר (ליג 1) — גם כתבות סיכום המחזור
SPORT5_LINK_OR_ARTICLE = SPORT5_LINK + r"|articles\.aspx\?FolderID=\d+&docID=\d+"

LEAGUES = {
    "premier": {
        "name": "פרמייר ליג",
        "source": "football-data",
        "fd_code": "PL",
        "fd_season": "2026",
        "default_yt_search": "{home} {away}",
    },
    "championship": {
        "name": "צ'מפיונשיפ",
        "source": "sportsdb",
        "sportsdb_ids": ["4329"],
        "sportsdb_season": "2026-2027",
        # Sky Sports Football מעלה תקציר לכל משחקי ה-EFL (שלוש הליגות), בפורמט
        # "... | Southampton 4-1 Bristol City | EFL Highlights" (אומת 13.9.26).
        # ערוץ עמוס ורב-ליגתי: title_include מגביל לכותרות EFL, והתאמת שתי
        # הקבוצות מסננת את ליג 1/ליג 2. משחק בן יום-יומיים+ → search.list.
        # ערוצי המועדונים קודם (כמו בפרמייר ובצ'מפיונס), Sky אחריהם כגיבוי.
        # אומתו 13.9.26 מול ה-RSS הציבורי: כל ערוץ כאן העלה תקציר ממחזור 6–7.
        # רקסהאם, לינקולן, נוריץ' ו-וולבס — ערוצים שהמשתמש מצא (handles לא
        # סטנדרטיים: @WxmAFCofficial, @lincolncityfc1685, @CanariesTV,
        # @OfficialWolvesVideo), אומתו באותה דרך (וולבס: מחזורים 4–5 — מחזור 6
        # נדחה ל-20.10 ומחזור 7 טרם שוחק). כל 24 המועדונים מכוסים.
        "club_channels": {
            "Wolverhampton Wanderers": "UCQ7Lqg5Czh5djGK6iOG53KQ",
            "Wrexham":              "UCS7BAYpqOSaYy-pZp6oO4PA",
            "Lincoln City":         "UCCLmGW0zE-1Gdagxg52G7sA",
            "Norwich City":         "UCzdkZv6--BWsUQ9rKUtQ1TQ",
            "Birmingham City":      "UCW1HMToSBse9JgQtsm2vMsQ",
            "Blackburn Rovers":     "UCg4185wSpo9swSCSUEYUGTg",
            "Bolton Wanderers":     "UC6oTkDRXLR6GO53l44i0LFw",
            "Bristol City":         "UCq_5VYwAoOvaL4lyGkwoboQ",
            "Burnley":              "UChvUXuSDeEFSQZS8GcPMtkg",
            "Cardiff City":         "UCfBVy8PAMwyNbac6D0Mk8gQ",
            "Charlton Athletic":    "UC99akEsugT_s4tv_r2oxuOQ",
            "Derby County":         "UCsOKCDfSRPwRhnbCqBO8CQw",
            "Middlesbrough":        "UCdXWsJhkXzx5hFJGcxjy_5Q",
            "Millwall":             "UCPyLfjCylafteypHYuYvGbQ",
            "Portsmouth":           "UC2pUjr6WECIEprPQxcD51OA",
            "Preston North End":    "UCWSRYI78ApCEDssqg5UjXKw",
            "Queens Park Rangers":  "UCiegSQxYwraPK5efklvTO5w",
            "Sheffield United":     "UCVER_UoBt84YUrA6s402Q-g",
            "Southampton":          "UCxvXjfiIHQ2O6saVx_ZFqnw",
            "Stoke City":           "UCmFPjHUFr0hyE6eFGvCm7IA",
            "Swansea City":         "UCSMZZFBE92Yn-_XYdDiiANA",
            "Watford":              "UCptKljTrbdMTgmuekGKhRug",
            "West Bromwich Albion": "UCnDBNo0zLm11TTXPVXvEN1g",
            "West Ham United":      "UCCNOsmurvpEit9paBOzWtUg",
        },
        "sources": [
            {"id": "sky_efl", "name": "Sky Sports",
             "channel_id": "UCZ7wY7MRDSygp63HIEfdQZA",
             "search_template": "{home} {away} EFL highlights",
             "title_include": ["efl"]},
        ],
    },
    "israel": {
        "name": "ליגת העל",
        "source": "sportsdb",
        "sportsdb_ids": ["4644"],
        "sportsdb_season": "2026-2027",
        "sources": [
            # לפי סדר מהירות ההעלאה: ספורט 1 (אותו יום) → ערוץ הספורט
            # (אחרי חצות) → הערוץ הרשמי של הליגה (24-72 שעות, גיבוי)
            # il_both_teams: שתי הקבוצות חייבות להופיע בכותרת. בלי זה כל
            # סרטון עם המילה "תקציר" בערוץ התאים לכל משחק — והמשתמש קיבל
            # במשחק הפועל ב"ש–הפועל פ"ת תקצירים של משחקים אחרים (16.9.26)
            {"id": "sport1", "name": "ספורט 1",
             "channel_id": "UC_wkUEeEC4HlcfI5xanWjBQ",
             "search_template": "תקציר {home} {away}",
             "hebrew_names": True, "il_both_teams": True},
            {"id": "sport5", "name": "ערוץ הספורט",
             "channel_id": "UCyXf5cz6E9IIL40aivg7tOw",
             "search_template": "תקציר {home} {away}",
             "hebrew_names": True, "il_both_teams": True},
            # "מחזור 4 | תקציר: בית"ר ירושלים - מכבי פ"ת 1-3" — שתי הקבוצות
            # בכותרת (גם בקיצור). "המשחק המלא" = 90 דקות, לא תקציר
            {"id": "ipfl", "name": "ליגת העל",
             "channel_id": "UCxjaVFauWASy0CuJfHKZeiw",
             "search_template": "תקציר {home} {away}",
             "hebrew_names": True, "il_both_teams": True,
             # גם בגרסה האנגלית: "Matchday 4 | Full Match: ..." (90 דקות)
             "title_exclude": ["המשחק המלא", "full match"]},
            # ערוצים לא רשמיים (העלאות פיראטיות) — לפעמים מקדימים את
            # הרשמיים. unofficial=True: מוגשים רק כש-UNOFFICIAL_SOURCES=1.
            # הפניה מודעת לתוכן מפר היא חשיפה משפטית אמיתית, ולכן
            # ברירת המחדל מכבה אותם.
            # il_both_teams: רק "תקציר" + שתי הקבוצות בשם מלא (is_il_both_teams)
            {"id": "yt_footballyom1", "name": "@FootballYom1",
             "channel_id": "UC5TtVDq_BSplSOHf7lb2AGQ",
             "search_template": "תקציר {home} {away}",
             "hebrew_names": True, "il_both_teams": True, "unofficial": True},
            {"id": "yt_almog218", "name": "@almog218",
             "channel_id": "UCm8OkQc5lHJE29ADWkbB7CQ",
             "search_template": "תקציר {home} {away}",
             "hebrew_names": True, "il_both_teams": True, "unofficial": True},
            {"id": "yt_itsfootball44", "name": "@ItsFootball44",
             "channel_id": "UCUEeo-8_3zovErCSQb58dnw",
             "search_template": "תקציר {home} {away}",
             "hebrew_names": True, "il_both_teams": True, "unofficial": True},
        ],
        # קישורי אתר (same-day): קפיצה ישירה לתוצאה הראשונה, בלי גלילה
        "web_sources": [
            # scrape_pages: עמודי האתר שמהם נשלף קישור ישיר (בלי מנוע חיפוש)
            {"name": "ספורט 1", "domain": "sport1.maariv.co.il",
             "scrape_pages": SPORT1_PAGES, "link_pattern": SPORT1_LINK,
             "base": "https://sport1.maariv.co.il",
             "query": "תקציר {home} {away}"},
            # וואלה: אין עמוד תקצירים לקריאה — רק עם Google CSE (אם הוגדר)
            {"name": "וואלה",   "domain": "sports.walla.co.il",
             "query": "תקציר {home} {away}"},
            {"name": "ספורט 5", "domain": "sport5.co.il",
             "scrape_pages": ["https://www.sport5.co.il/",
                              "https://www.sport5.co.il/liga.aspx?FolderID=44"],
             "link_pattern": SPORT5_LINK,
             "query": "תקציר {home} {away}"},
        ],
    },
    "bundesliga": {
        "name": "בונדסליגה",
        "source": "sportsdb",
        "sportsdb_ids": ["4331"],
        "sportsdb_season": "2026-2027",
        "sources": [
            {"id": "bundesliga_official", "name": "Bundesliga",
             "channel_id": "UC6UL29enLNe4mqwTfAyeNuw",
             "search_template": "{home} {away} highlights"},
        ],
    },
    "laliga": {
        "name": "לה ליגה",
        "source": "sportsdb",
        "sportsdb_ids": ["4335"],
        "sportsdb_season": "2026-2027",
        "sources": [
            # ONE מעלים מהר מאוד, בכותרות חדשותיות בעברית (בלי "תקציר") —
            # headline_titles: כלל זיהוי ייעודי (is_headline_highlight)
            {"id": "one_laliga", "name": "ONE",
             "channel_id": "UCgbHJENV6UgIZl1Rp_GXCfw",
             "search_template": "{home} {away}",
             "hebrew_names": True,
             "headline_titles": True},
            {"id": "laliga_official", "name": "LALIGA",
             "channel_id": "UCTv-XvfzLX3i4IGWAm4sbmA",
             "search_template": "{home} {away} resumen"},
        ],
    },
    "seriea": {
        "name": "סריה A",
        "source": "sportsdb",
        "sportsdb_ids": ["4332"],
        "sportsdb_season": "2026-2027",
        "sources": [
            # ONE — גם את איטליה כותבים עכשיו בעברית ("2:2 אדיר בין לאציו
            # למילאן", 13.9.26): חיפוש בעברית + כלל הכותרות החדשותיות
            {"id": "one_seriea", "name": "ONE",
             "channel_id": "UCgbHJENV6UgIZl1Rp_GXCfw",
             "search_template": "{home} {away}",
             "hebrew_names": True,
             "headline_titles": True},
            {"id": "seriea_official", "name": "Serie A",
             "channel_id": "UCBJeMCIeLQos7wacox4hmLQ",
             "search_template": "{home} {away} highlights"},
        ],
    },
    "ligue1": {
        "name": "ליג 1",
        "source": "sportsdb",
        "sportsdb_ids": ["4334"],
        "sportsdb_season": "2026-2027",
        "sources": [
            {"id": "ligue1_official", "name": "Ligue 1",
             "channel_id": "UCQsH5XtIc9hONE1BQjucM0g",
             "search_template": "{home} {away} highlights"},
        ],
        # תקצירי יוטיוב של ליג 1 עולים מאוחר — ספורט 5 (משדרת בישראל) כגיבוי.
        # אין להם VOD ייעודי לליגה, אז גם כתבות סיכום המחזור (עם וידאו).
        "web_sources": [
            {"name": "ספורט 5", "domain": "sport5.co.il",
             "scrape_pages": ["https://www.sport5.co.il/",
                              "https://www.sport5.co.il/liga.aspx?FolderID=495"],
             "link_pattern": SPORT5_LINK_OR_ARTICLE,
             "base": "https://www.sport5.co.il",
             "query": "תקציר {home} {away}"},
        ],
    },
    "ucl": {
        "name": "צ'מפיונס ליג",
        "source": "sportsdb",
        "sportsdb_ids": ["4480"],
        "sportsdb_season": "2026-2027",
        # שלב הליגה התחיל 8.9 — משחקי המוקדמות (יולי–אוגוסט) לא מוצגים
        "min_date": "2026-09-01",
        # אין ערוץ יוטיוב רשמי שמעלה תקצירים של כולם (אומת ידנית 5/9/26) —
        # התקצירים מפוזרים בערוצי הקבוצות (באיחור יום-יומיים).
        # המקור: ספורט 5, המשדרת בישראל — כתבה/VOD ישירים.
        "sources": [
            # TV2 Sport (נורווגיה), מהמשתמש 16.9.26: מעלים תקצירים של
            # בודו/גלימט וויקינג, שאין להן ערוץ עם תקצירים. הכותרת היא
            # "Bodø/Glimt 2 - 2 Slavia" או "... - Høydepunkter" — שתי
            # הקבוצות + תוצאה/מילת תקציר
            {"id": "tv2_no", "name": "TV2 Sport",
             "channel_id": "UC9QZZRUajPEoo1Q-V3MfvnQ",
             "search_template": "{home} {away}",
             "require_team_match": True},
        ],
        # ערוצי המועדונים ביוטיוב — שם התקצירים עולים הכי מהר (לרוב באותו לילה).
        # מפתח = שם הקבוצה ב-TheSportsDB. אומתו 13.9.26 מול ה-RSS הציבורי של
        # כל ערוץ: הועלה תקציר של מחזור 1, או תקציר מליגה מקומית באותו פורמט.
        # בלי ערוץ (אין בו תקצירים / אין ערוץ פעיל): נאפולי, גלאטסראי, פורטו,
        # לאנס, שטוטגרט, PSG, AEK, שחטאר, סבאח, ויקינג, בודו, סלביה, לאסק, קומו.
        # עלות: חיפוש לכל ערוץ = 100 יחידות quota, פעם אחת למשחק (קאש).
        "club_channels": {
            "Arsenal":            "UCpryVRk_VDudG8SHXgWcG0w",
            "Aston Villa":        "UCICNP0mvtr0prFwGUQIABfQ",
            "Liverpool":          "UC9LQwHZoucFT94I2h6JOcjw",
            "Manchester City":    "UCkzCjdRMrW2vXLx8mvPVLdQ",
            "Manchester United":  "UC6yW44UGJJBvYTlfC7CRg2Q",
            "Atlético Madrid":    "UCuzKFwdh7z2GHcIOX_tXgxA",
            "Barcelona":          "UC14UlmYlSNiQCBe9Eookf_A",
            "Real Madrid":        "UCWV3obpZVGgJ3j9FVhEjF2Q",
            "Real Betis":         "UCeB7JZwcar2fVoK2w2f9OwA",
            "Villarreal":         "UC0MLWyQ0L7uEZY8wbkDSTkw",
            "Bayern Munich":      "UCZkcxFIsqW5htimoUQKA0iA",
            "Borussia Dortmund":  "UCK8rTVgp3-MebXkmeJcQb1Q",
            "RB Leipzig":         "UCkZwB4IGoNBvRmVT2gaO4XA",
            "Inter Milan":        "UCvXzEblUa0cfny4HAJ_ZOWw",
            "Roma":               "UCLttSYJ6kPtlcurY96kXkQw",
            "Lille":              "UCae9u1pNGzaklyZC8OKkeCQ",
            "Club Brugge":        "UCr4sbmZGQY9T4p4KcknxSNw",
            "Feyenoord":          "UCg_DGzRRIQlXpHxCrMMiAIQ",
            "PSV Eindhoven":      "UC_2ynsXrRrKP8zYrU7Hc06A",
            # מהמשתמש (13.9.26): PSG — "... I PSG 6-1 BRATISLAVA" (תוצאה בכותרת);
            # שחטאר — אוקראינית, עם תאריך המשחק (CLUB_TITLE_RULES), לפעמים באיחור
            "Paris Saint-Germain": "UCt9a_qP9CqHCNwilf-iULag",
            "Shakhtar Donetsk":   "UCmPCqUih--EyT2oxUn72MtA",
            # מהמשתמש (16.9.26): סלביה מעלים תקציר עם תוצאה בכותרת
            # ("Slavia - RC Lens 2:3"); לאנס ולאסק לא מעלים תקצירים כרגע —
            # הערוץ עולה לבדיקה חינם דרך ה-RSS, ליום שבו כן יעלו
            "Slavia Prague":      "UCPi3_GbTljPZ6b2Laiw-Z5g",
            "Lens":               "UCE-f1Taamum6q2S-Ve4koSw",
            "LASK":               "UC989Kq_d33oi_wwR5NsRZLw",
            "Sporting CP":        "UCnJj6L93JX3Jrhzv81ayywA",
            "Fenerbahçe":         "UCgqlho3-8a6FmDqQm7Q6gJw",
            "Slovan Bratislava":  "UC7ldMqVVX6CD6NMZaqsihTw",
        },
        "web_sources": [
            {"name": "ספורט 5", "domain": "sport5.co.il",
             "scrape_pages": ["https://www.sport5.co.il/",
                              "https://www.sport5.co.il/liga.aspx?FolderID=397"],
             "link_pattern": SPORT5_LINK,
             "query": "תקציר {home} {away}"},
        ],
    },
    "uel": {
        "name": "ליגה אירופית",
        "source": "sportsdb",
        "sportsdb_ids": ["4481"],
        "sportsdb_season": "2026-2027",
        # שלב הליגה מ-16.9 (באר שבע–דינמו זאגרב). מוקדמות — לא מוצגות.
        "min_date": "2026-09-01",
        "sources": [],
        # ערוצי מועדונים עם תקצירים בפורמט הרגיל (אומתו 13.9.26 מול ה-RSS —
        # תקצירי ליגה מקומית; שלב הליגה עוד לא התחיל). לרוב הקבוצות, כולל
        # הפועל באר שבע, לא נמצא ערוץ רשמי. מקור ישראלי (המשדרת) — ייבדק אחרי
        # מחזור 1, כשיהיו תקצירים (לא ספורט 5 — כנראה לא משדרים את הליגה).
        "club_channels": {
            "Sunderland":     "UCrw-7k6yJc0EMJdf-0BAkoQ",
            "Crystal Palace": "UCWB9N0012fG6bGyj486Qxmg",
            "Bournemouth":    "UCeOCuVSSweaEj6oVtJZEKQw",
            "Benfica":        "UC8zrah5cNf2c3jKKeD_Z3fw",
            "Celtic":         "UCBN-bb-hE7jYlcp4exwXRsQ",
            "AC Milan":       "UCKcx1uK38H4AOkmfv4ywlrg",
            # אומתו 18.9.26: הערוצים האלה באמת מעלים תקציר של משחק הליגה
            # האירופית ("HIGHLIGHTS | Europa League 26-27 | J1 | Real
            # Sociedad 1 - 2 AFC Bournemouth").
            # מהמשתמש (26.9.26): יובנטוס וליון כן מעלים — הסינון שלי חיפש
            # "highlights" באנגלית, וליון מעלים בצרפתית עם התוצאה בכותרת
            # ("Anderlecht - OL : 3 points pour démarrer la campagne
            # européenne ! (1-2)"). כלומר "אין תקצירים" בערוץ לא נקבע לפי
            # מילת מפתח באנגלית — צריך לקרוא את הכותרות בשפת המועדון.
            "Anderlecht":     "UCIr5bpTRrkwJprfaG1owIZw",
            "Celta Vigo":     "UCCJLVZYqRb_85b2Flpg04cg",
            "Real Sociedad":  "UCfeqewEKWQ8CXY8OiXoMxxw",
            "Sturm Graz":     "UCcReHK9o6bc5NT2cj4mpJKQ",
            "Marseille":      "UCoKweTwEeA-D9vuSVw_Z_DQ",
            "Red Bull Salzburg":     "UCNXjAsLzro7bnZVWqnnkgsg",
            "Rennes":                "UC96bdUrtQVEqx_OmKwFAgXg",
            "Sparta Prague":         "UCJcXzTZcKukYq9O4ZBtVxdw",
            "Viktoria Plzeň":        "UCemUcP3Rwmz6d9yrW1Vn3tw",
            "Union Saint-Gilloise":  "UCk9RAl0uUwjYbTaFQMFaX5g",
            "Bayer Leverkusen":      "UCSMZmPVql528Cph9WPvt0GA",
            # כבר מוגדרים אצלנו בליגה ההולנדית
            "AZ Alkmaar":     "UCTCO3NaW_heI8H6U7f43Now",
            "NEC Nijmegen":   "UCF4UEYKNui8ytU9vC9h58fg",
            "Juventus":       "UCLzKhsxrExAC6yAdtZ-BOWw",
            "Lyon":           "UCzHCZXmqIdjqRnpdp0l_T6g",
            # 26.9.26, סריקה של 15 הקבוצות שנשארו בלי מקור — הפעם קראתי
            # את הכותרות בשפת המועדון ולא חיפשתי "highlights":
            # ארארט-ארמניה מעלים את התקציר של הליגה האירופית עצמה
            # ("UEFA Europa League | FC Ararat-Armenia - Sparta Praha [1:4]"),
            # ודינמו זאגרב מעלים תקציר בפורמט הרגיל לליגה המקומית
            # ("HIGHLIGHTS | Dinamo 3-2 Lokomotiva") — באירופה עוד לא ראיתי
            # מהם אחד, והערוץ נבדק חינם ב-RSS ליום שבו כן יעלו
            "Ararat-Armenia": "UCFzwA2WTexgusRXuBLTGPgw",
            "Dinamo Zagreb":  "UC6vpARgHA0oSqtBgYcVWdHg",
        },
    },
    "mls": {
        "name": "MLS",
        "source": "sportsdb",
        "sportsdb_ids": ["4346"],
        "sportsdb_season": "2026",   # עונה קלנדרית
        # הערוץ הרשמי מעלה תקציר לכל משחק: "Home vs. Away | Full Match
        # Highlights" (אומת 13.9.26). ערוץ עמוס מאוד (15 סרטונים ב-3 שעות) —
        # משחק בן כמה שעות+ עובר ל-search.list (100 יחידות, פעם אחת למשחק).
        "sources": [
            {"id": "mls_official", "name": "MLS",
             "channel_id": "UCSZbXT5TLLW_i-5W8FZpFsg",
             "search_template": "{home} vs {away} highlights",
             "title_include": ["highlights"]},
        ],
    },
    "eredivisie": {
        "name": "ליגה הולנדית",
        "source": "sportsdb",
        "sportsdb_ids": ["4337"],
        "sportsdb_season": "2026-2027",
        # אין ערוץ ליגה שמעלה תקצירים (sportdigital כמעט ריק, אומת 16.9.26
        # מול המשתמש) — כל מועדון בערוץ שלו. אייאקס כותבים את שתי הקבוצות
        # ("Highlights Ajax - Willem II"), פ.ס.וו לא כותבים את היריבה
        # ("HIGHLIGHTS | A proper PSV night") — הכלל של ערוץ מועדון מכסה זאת
        "sources": [],
        "club_channels": {
            "Ajax":             "UCGpf7WX7R1one-NwOvg_PbQ",
            "PSV Eindhoven":    "UC_2ynsXrRrKP8zYrU7Hc06A",
            "Feyenoord":        "UCg_DGzRRIQlXpHxCrMMiAIQ",
            "AZ Alkmaar":       "UCTCO3NaW_heI8H6U7f43Now",
            "Twente":           "UCywIk9gmEzBbjE7cGT0FG8Q",
            "Utrecht":          "UC4dZheVrm6gwxta9HQwoaHg",
            "Go Ahead Eagles":  "UCViFZLCLYXB7vEURzFmqB1Q",
            "Groningen":        "UCq1wKt7hVuuOi83D4pvWKBA",
            "NEC Nijmegen":     "UCF4UEYKNui8ytU9vC9h58fg",
            "Excelsior":        "UC8GEwTPDCufQfF7j95WRq4w",
            "Willem II":        "UCl4YVKOIdzEMHymvgtdk96w",
            "Cambuur":          "UCHKOOZBmIHUYYRi-uX0ZFRA",
            "ADO Den Haag":     "UCJcHVyyO6Hio-NAQupty87Q",
            "Sparta Rotterdam": "UC8jk5fdSMwHt6-cLYXTAYuA",
            "Heerenveen":       "UCAm1W5LwDRIVo4sCfjsImWg",
            "Fortuna Sittard":  "UC7IboGldjNiCzPGHlkX9XXQ",
            "PEC Zwolle":       "UCQ9ElvawvfGZip6ZtUvo2hQ",
            "Telstar":          "UCGnPfJzkzqY1fVpqlURigjg",
        },
    },
    "argentina": {
        "name": "ליגה ארגנטינאית",
        "source": "sportsdb",
        # רק Primera División. Copa de la Liga (5428) הופסקה ב-2024 —
        # eventspast שלה החזיר משחקים ישנים וזיהם את הלוח.
        "sportsdb_ids": ["4406"],
        "sportsdb_season": "2026",
        "sources": [
            # title_exclude: מסנן את גרסת הקריינות באנגלית ("Game Highlights").
            # נשארת רק הגרסה בספרדית ("Match Highlights" / Resumen).
            {"id": "fanatiz", "name": "Fanatiz",
             "channel_id": "UCvEJrtUk0C2wh3P-9DOdblA",
             "search_template": "{home} {away} match highlights",
             "title_exclude": ["game highlights"]},
            {"id": "lpf_official", "name": "Liga Profesional",
             "channel_id": "UCJmCVoUfCBQb9lcfXIS8nXQ",
             "search_template": "{home} {away} resumen"},
        ],
    },
    # ── גביעים ─────────────────────────────────────────
    # "מחזור" בגביע הוא שלב, ולא רץ מ-1 ומעלה: קאראבאו 26/27 הוא
    # 128→64→32→16, ואחר כך 125=רבע גמר, 150=חצי, 200=גמר. אומת מול
    # העונה שעברה בכל חמשת הגביעים (18.9.26). לכן cup=True: הלקוח מציג
    # שם שלב במקום מספר מחזור, ומסדר לפי תאריך ולא לפי המספר.
    "carabao": {
        "name": "גביע קאראבאו",
        "source": "sportsdb",
        "sportsdb_ids": ["4570"],
        "sportsdb_season": "2026-2027",
        "cup": True,
        "sources": [
            # הערוץ הרשמי של ה-EFL מעלה גם ליגה וגם גביע, ולכן חייבים את
            # שם הגביע בכותרת: "DEBUTANTS SHINE! | Manchester City v
            # Norwich City Carabao Cup Extended Highlights" (17.9.26).
            # בלי זה, משחק ליגה בין אותן קבוצות היה מוצג כתקציר הגביע.
            {"id": "efl_cup", "name": "EFL",
             "channel_id": "UCCmo_NIuQR5eU4AvBa6sEQQ",
             "search_template": "{home} {away} Carabao Cup highlights",
             "title_include": ["carabao"]},
        ],
    },
    "facup": {
        "name": "הגביע האנגלי",
        "source": "sportsdb",
        "sportsdb_ids": ["4482"],
        "sportsdb_season": "2026-2027",
        "cup": True,
        "sources": [
            # "INCREDIBLE Late Drama! | Knowle FC v Worcester City |
            # Key Moments | Emirates FA Cup 2027" — שתי הקבוצות בכותרת,
            # אבל "Key Moments" במקום Highlights. מגן הקהילה (Community
            # Shield) עולה באותו ערוץ והוא תחרות אחרת.
            {"id": "fa_cup", "name": "The Emirates FA Cup",
             "channel_id": "UCChcWqwYXCEs657MQ00qVWA",
             "search_template": "{home} {away} Emirates FA Cup",
             "title_include": ["fa cup"],
             "title_exclude": ["community shield", "full match"]},
        ],
    },
    "dfbpokal": {
        "name": "הגביע הגרמני",
        "source": "sportsdb",
        "sportsdb_ids": ["4485"],
        "sportsdb_season": "2026-2027",
        "cup": True,
        "sources": [
            # "VfL Osnabrück vs FC Bayern München 1-4 | Highlights |
            # DFB-Pokal" — כותרות באנגלית, שתי הקבוצות, שם הגביע.
            # הערוץ מעלה גם בונדסליגה ונבחרת, ומכאן title_include.
            {"id": "german_football", "name": "German Football",
             "channel_id": "UC7am34-1rGU_ky1vWYnoOJQ",
             "search_template": "{home} {away} DFB-Pokal highlights",
             "title_include": ["pokal"]},
        ],
    },
    "copadelrey": {
        "name": "גביע המלך",
        "source": "sportsdb",
        "sportsdb_ids": ["4483"],
        "sportsdb_season": "2026-2027",
        "cup": True,
        "sources": [
            # ההתאחדות הספרדית: "Resumen Final #CopaDelReyMAPFRE |
            # Atlético de Madrid - Real Sociedad". הערוץ מעלה גם ליגות
            # נמוכות ("Resumen #PrimeraFederación"), ומכאן title_include.
            {"id": "rfef", "name": "RFEF",
             "channel_id": "UCQBxzdEPXjy05MtpfbdtMxQ",
             "search_template": "{home} {away} Copa del Rey resumen",
             "title_include": ["copa"]},
        ],
    },
    "coupedefrance": {
        "name": "הגביע הצרפתי",
        "source": "sportsdb",
        "sportsdb_ids": ["4484"],
        "sportsdb_season": "2026-2027",
        "cup": True,
        # אין ערוץ מרכזי: ההתאחדות הצרפתית מעלה רק נבחרות (נבדק 19.9.26).
        # המקור היחיד הוא ערוצי המועדונים — "OM 3-1 Rennes | Le résumé
        # de la victoire" ו-"8e CDF | ... face à ..." בערוץ של רן.
    },
}

# בגביע משחקות קבוצות מכמה ליגות, והערוצים שלהן כבר אומתו אצלנו. כאן הם
# מושאלים — מקור אמת אחד לכל ערוץ, בלי שכפול מזהים. השמות הם כפי
# ש-sportsdb כותב אותם; ההתאמה עצמה נעשית דרך team_key, שסופג הפרשי
# "FC"/"&"/ניקוד ("Brighton & Hove Albion FC" מול "Brighton and Hove Albion").
# מועדוני פרמייר ליג 2026-27 — ערוצים אומתו ידנית (29/8/26), 7 תוקנו
# אחרי אימות /debug/channels (1/9/26). הקוד הוא מקור האמת: בכל עלייה
# טבלת clubs נבנית מחדש מהרשימה הזו, והגביעים שואלים ממנה ערוצים.
PREMIER_CLUBS = [
    ("PL-fd57",   "Arsenal FC",                "Arsenal",        "premier", 1, "UCpryVRk_VDudG8SHXgWcG0w", "57"),
    ("PL-fd61",   "Chelsea FC",                "Chelsea",        "premier", 1, "UCU2PacFf99vhb3hNiYDmxww", "61"),
    ("PL-fd64",   "Liverpool FC",              "Liverpool",      "premier", 1, "UC9LQwHZoucFT94I2h6JOcjw", "64"),
    ("PL-fd65",   "Manchester City FC",        "Man City",       "premier", 1, "UCkzCjdRMrW2vXLx8mvPVLdQ", "65"),
    ("PL-fd66",   "Manchester United FC",      "Man United",     "premier", 1, "UC6yW44UGJJBvYTlfC7CRg2Q", "66"),
    ("PL-fd73",   "Tottenham Hotspur FC",      "Spurs",          "premier", 1, "UCEg25rdRZXg32iwai6N6l0w", "73"),
    ("PL-fd1044", "AFC Bournemouth",           "Bournemouth",    "premier", 2, "UCeOCuVSSweaEj6oVtJZEKQw", "1044"),
    ("PL-fd58",   "Aston Villa FC",            "Aston Villa",    "premier", 2, "UCICNP0mvtr0prFwGUQIABfQ", "58"),
    ("PL-fd402",  "Brentford FC",              "Brentford",      "premier", 2, "UCAalMUm3LIf504ItA3rqfug", "402"),
    ("PL-fd397",  "Brighton & Hove Albion FC", "Brighton",       "premier", 2, "UCf-cpC9WAdOsas19JHipukA", "397"),
    ("PL-fd1076", "Coventry City FC",          "Coventry",       "premier", 2, "UCch_NWdo3JWKngAyO9XlycA", "1076"),
    ("PL-fd354",  "Crystal Palace FC",         "Crystal Palace", "premier", 2, "UCWB9N0012fG6bGyj486Qxmg", "354"),
    ("PL-fd62",   "Everton FC",                "Everton",        "premier", 2, "UCtK4QAczAN2mt2ow_jlGinQ", "62"),
    ("PL-fd63",   "Fulham FC",                 "Fulham",         "premier", 2, "UC2VLfz92cTT8jHIFOecC-LA", "63"),
    ("PL-fd322",  "Hull City AFC",             "Hull",           "premier", 2, "UC8MRV5E-Bi5qWomGjOF0ZQg", "322"),
    ("PL-fd349",  "Ipswich Town FC",           "Ipswich",        "premier", 2, "UCjNwxJec96lMWgCXjEDhXgQ", "349"),
    ("PL-fd341",  "Leeds United FC",           "Leeds",          "premier", 2, "UCyQcJHDN4uYfPa1DHzKVSnw", "341"),
    ("PL-fd67",   "Newcastle United FC",       "Newcastle",      "premier", 2, "UCywGl_BPp9QhD0uAcP2HsJw", "67"),
    ("PL-fd351",  "Nottingham Forest FC",      "Forest",         "premier", 2, "UCyAxjuAr8f_BFDGCO3Htbxw", "351"),
    ("PL-fd71",   "Sunderland AFC",            "Sunderland",     "premier", 2, "UCrw-7k6yJc0EMJdf-0BAkoQ", "71"),
]


def _register_cup_club_channels() -> None:
    english = {re.sub(r"^AFC\s+|\s+A?FC$", "", c[1]).strip(): c[5]
               for c in PREMIER_CLUBS}
    english.update(LEAGUES["championship"]["club_channels"])
    LEAGUES["carabao"]["club_channels"] = english
    LEAGUES["facup"]["club_channels"] = dict(english)

    uel = LEAGUES["uel"]["club_channels"]
    def borrow(*names):
        return {n: uel[n] for n in names if n in uel}
    LEAGUES["copadelrey"]["club_channels"] = borrow("Celta Vigo", "Real Sociedad")
    LEAGUES["coupedefrance"]["club_channels"] = borrow("Marseille", "Rennes")
    LEAGUES["dfbpokal"]["club_channels"] = borrow("Bayer Leverkusen")


_register_cup_club_channels()

# ── Auth ───────────────────────────────────────────────
# כניסה אישית: מייל → קוד חד-פעמי (6 ספרות, 10 דקות) → session ל-90 יום.
# חשבון חדש ממתין לאישור ידני של אדמין (/admin/users). אדמינים: ADMIN_EMAILS
# (משתנה סביבה ב-Render — לא בקוד, הריפו ציבורי).
# הסיסמה המשותפת הישנה (APP_PASSWORD) עובדת במקביל עד שמסירים אותה מ-Render.
# בלי אף אחד מהמשתנים (פיתוח מקומי) — האתר פתוח. AUTH_DEV=1: כניסה פעילה
# מקומית, והקוד מודפס ללוג במקום להישלח.

GMAIL_USER         = os.environ.get("GMAIL_USER", "").strip()
# Google מציגה את סיסמת האפליקציה עם רווחים ("abcd efgh ijkl mnop") — מסירים
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "").replace(" ", "").strip()
# Gmail API (HTTPS) — Render החינמי חוסם SMTP (25/465/587) מספטמבר 2025.
# GMAIL_CLIENT_ID/SECRET מ-Google Cloud; ה-refresh token נשמר ב-DB אחרי
# "חיבור Gmail" בעמוד הניהול (או GMAIL_REFRESH_TOKEN ב-Render).
GMAIL_CLIENT_ID     = os.environ.get("GMAIL_CLIENT_ID", "").strip()
GMAIL_CLIENT_SECRET = os.environ.get("GMAIL_CLIENT_SECRET", "").strip()
GMAIL_SCOPES   = "https://www.googleapis.com/auth/gmail.send openid email"
GMAIL_CALLBACK = "/admin/gmail/callback"
_gmail_token = {"value": None, "exp": 0.0}   # access token בזיכרון (שעה תוקף)
# Brevo (HTTPS, חינם עד 300 ביום) — הדרך הפעילה: Google חוסמת חשבונות Gmail
# חדשים. BREVO_SENDER = כתובת שאומתה כשולח ב-Brevo (בלי דומיין משלנו
# Brevo מחליפה את הדומיין בכתובת @brevosend — צפוי יותר ספאם).
BREVO_API_KEY = os.environ.get("BREVO_API_KEY", "").strip()
BREVO_SENDER  = os.environ.get("BREVO_SENDER", "").strip()
ADMIN_EMAILS = {e.strip().lower()
                for e in os.environ.get("ADMIN_EMAILS", "").split(",") if e.strip()}
APP_URL  = os.environ.get("APP_URL", "https://spoilerfree.onrender.com").rstrip("/")
AUTH_DEV = os.environ.get("AUTH_DEV") == "1"
# כל דרך שליחה מוגדרת = האתר נעול. בלי זה, מחיקת APP_PASSWORD/GMAIL_USER
# מ-Render הייתה פותחת את האתר לכולם.
# ב-Render (RENDER=true מוגדר אוטומטית) הכניסה תמיד חובה — גם כשכל משתני
# הסיסמה/המייל נמחקו (הרשמה עם מייל+סיסמה לא צריכה אף אחד מהם).
AUTH_ON  = bool(APP_PASSWORD or GMAIL_USER or BREVO_API_KEY or GMAIL_CLIENT_ID or AUTH_DEV
                or os.environ.get("RENDER"))

SESSION_DAYS      = 90
CODE_MINUTES      = 10
CODE_MAX_ATTEMPTS = 5
CODE_RESEND_SEC   = 60
PW_MIN_LEN        = 8
PW_MAX_FAILS      = 5      # טעויות סיסמה רצופות → נעילה
PW_LOCK_MIN       = 15
PW_RESET_MIN      = 15     # אחרי כניסה עם קוד — חלון לקביעת/החלפת סיסמה
PW_ITER           = 200_000
# הרשמה: ברירת המחדל — מייל + סיסמה, מיד, בלי קוד. EMAIL_CODE_REQUIRED=1 ב-Render
# → הרשמה רק עם קוד למייל (אם תהיה תנועה חשודה). כתובות מנהל תמיד עם קוד.
EMAIL_CODE_REQUIRED = os.environ.get("EMAIL_CODE_REQUIRED") == "1"
# לאן נשלחת הודעה על כל הרשמה חדשה (ברירת מחדל: ADMIN_EMAILS)
NOTIFY_EMAILS = {e.strip().lower()
                 for e in os.environ.get("NOTIFY_EMAILS", "").split(",") if e.strip()}
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
EVENT_TYPES = {"app_open", "league_view", "day_view", "match_open",
               "highlight_play", "web_link"}


def _auth_token() -> str:
    """cookie של הסיסמה המשותפת הישנה."""
    return hashlib.sha256(APP_PASSWORD.encode()).hexdigest() if APP_PASSWORD else ""


def _sha(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _pw_hash(pw: str) -> str:
    """PBKDF2-SHA256 עם salt — הסיסמה עצמה לא נשמרת בשום מקום."""
    salt = secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac("sha256", pw.encode(), bytes.fromhex(salt), PW_ITER).hex()
    return f"pbkdf2${PW_ITER}${salt}${h}"


def _pw_check(pw: str, stored: str) -> bool:
    try:
        _, it, salt, h = stored.split("$")
        got = hashlib.pbkdf2_hmac("sha256", pw.encode(), bytes.fromhex(salt), int(it)).hex()
        return hmac.compare_digest(got, h)
    except Exception:
        return False


def current_user(request):
    """{"email", "is_admin", "legacy"} או None. נשמר על הבקשה — שאילתה אחת לבקשה."""
    if request is None:
        return None
    if hasattr(request.state, "sf_user"):
        return request.state.sf_user
    user = None
    token = request.cookies.get("sf_session", "")
    if token:
        conn = get_db()
        row = conn.execute(
            "SELECT u.email, u.is_admin, u.status FROM sessions s "
            "JOIN users u ON u.email = s.email "
            "WHERE s.token_hash=? AND s.expires_at>?",
            (_sha(token), _now().isoformat())).fetchone()
        conn.close()
        if row and row["status"] == "approved":
            user = {"email": row["email"], "legacy": False,
                    "is_admin": bool(row["is_admin"]) or row["email"] in ADMIN_EMAILS}
    if user is None and APP_PASSWORD and request.cookies.get("sf_auth", "") == _auth_token():
        # סיסמה משותפת ישנה — שומרת על ההרשאות של היום עד שמסירים אותה
        user = {"email": None, "is_admin": True, "legacy": True}
    request.state.sf_user = user
    return user


def is_authed(request: Request) -> bool:
    if not AUTH_ON:
        return True  # פיתוח מקומי — פתוח
    return current_user(request) is not None


def require_auth(request: Request):
    if not is_authed(request):
        raise HTTPException(401, "נדרשת התחברות")


def require_admin(request: Request):
    """נקודות דיבאג/אדמין — רק למנהלים (לא לכל משתמש מאושר)."""
    if not AUTH_ON:
        return
    u = current_user(request)
    if not u:
        raise HTTPException(401, "נדרשת התחברות")
    if not u["is_admin"]:
        raise HTTPException(403, "למנהלים בלבד")


def _meta_get(key: str):
    conn = get_db()
    row = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    conn.close()
    return row["value"] if row else None


def _meta_set(key: str, value: str):
    conn = get_db()
    conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (key, value))
    conn.commit()
    conn.close()


def _gmail_refresh_token():
    return os.environ.get("GMAIL_REFRESH_TOKEN", "").strip() or _meta_get("gmail_refresh_token")


def gmail_api_ready() -> bool:
    return bool(GMAIL_CLIENT_ID and GMAIL_CLIENT_SECRET and _gmail_refresh_token())


def _gmail_access_token():
    """access token מה-refresh token; נשמר בזיכרון עד 5 דק' לפני שפג."""
    if _gmail_token["value"] and time.time() < _gmail_token["exp"]:
        return _gmail_token["value"]
    rt = _gmail_refresh_token()
    if not (GMAIL_CLIENT_ID and GMAIL_CLIENT_SECRET and rt):
        return None
    r = requests.post("https://oauth2.googleapis.com/token", data={
        "client_id": GMAIL_CLIENT_ID, "client_secret": GMAIL_CLIENT_SECRET,
        "refresh_token": rt, "grant_type": "refresh_token"}, timeout=15)
    j = r.json()
    if r.status_code != 200 or "access_token" not in j:
        # invalid_grant = החיבור בוטל/פג — צריך "חיבור Gmail" מחדש בעמוד הניהול
        print(f"[mail] gmail token refresh failed: {j.get('error')}")
        return None
    _gmail_token.update(value=j["access_token"],
                        exp=time.time() + int(j.get("expires_in", 3600)) - 300)
    return j["access_token"]


def _gmail_api_send(msg: EmailMessage) -> bool:
    import base64
    token = _gmail_access_token()
    if not token:
        return False
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    r = requests.post("https://gmail.googleapis.com/gmail/v1/users/me/messages/send",
                      headers={"Authorization": f"Bearer {token}"}, json={"raw": raw}, timeout=15)
    if r.status_code != 200:
        print(f"[mail] gmail api send failed: {r.status_code} {r.text[:200]}")
        return False
    return True


def email_sender_ready() -> bool:
    """יש דרך אמיתית לשלוח מייל? (קובע אם להציג "שכחתי סיסמה" עם קוד).
    SMTP לא נחשב ב-Render — החינמי חוסם אותו."""
    return bool((BREVO_API_KEY and BREVO_SENDER) or gmail_api_ready() or AUTH_DEV
                or (GMAIL_USER and GMAIL_APP_PASSWORD and not os.environ.get("RENDER")))


def _brevo_send(to: str, subject: str, body: str) -> bool:
    r = requests.post("https://api.brevo.com/v3/smtp/email",
                      headers={"api-key": BREVO_API_KEY, "accept": "application/json"},
                      json={"sender": {"name": "SpoilerFree", "email": BREVO_SENDER},
                            "to": [{"email": to}], "subject": subject, "textContent": body},
                      timeout=15)
    if r.status_code not in (200, 201, 202):
        print(f"[mail] brevo send failed: {r.status_code} {r.text[:200]}")
        return False
    return True


def send_email(to: str, subject: str, body: str) -> bool:
    """שליחה ב-HTTPS (Render החינמי חוסם SMTP): Brevo כשמוגדר, אחרת Gmail API
    כשמחובר, אחרת SMTP עם סיסמת אפליקציה (מקומי / שרת בתשלום)."""
    if BREVO_API_KEY and BREVO_SENDER:
        try:
            return _brevo_send(to, subject, body)
        except Exception as ex:
            print(f"[mail] brevo send to {to} failed: {ex}")
            return False
    api = gmail_api_ready()
    if not (api or (GMAIL_USER and GMAIL_APP_PASSWORD)):
        if AUTH_DEV:
            print(f"[mail:dev] to={to} | {subject}\n{body}")
            return True
        print(f"[mail] not configured — cannot send to {to}")
        return False
    sender = (_meta_get("gmail_sender") if api else None) or GMAIL_USER
    msg = EmailMessage()
    if sender:
        msg["From"] = f"SpoilerFree <{sender}>"
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    try:
        if api:
            return _gmail_api_send(msg)
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=15) as s:
            s.login(GMAIL_USER, GMAIL_APP_PASSWORD)
            s.send_message(msg)
        return True
    except Exception as ex:
        print(f"[mail] send to {to} failed: {ex}")
        return False


def _notify_registration(email: str, lang: str = None):
    """כל הרשמה חדשה (אחרי שהמייל אומת בקוד) — הודעה למנהל.
    NOTIFY_EMAILS ב-Render; אם לא הוגדר — ADMIN_EMAILS."""
    conn = get_db()
    n = conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"]
    conn.close()
    for to in (NOTIFY_EMAILS or ADMIN_EMAILS):
        send_email(to, f"SpoilerFree — משתמש חדש: {email}",
                   f"{email} נרשם/ה ל-SpoilerFree.\n"
                   f"שפה: {lang or 'he'}\nסה\"כ משתמשים: {n}\n\n"
                   f"ניהול (וחסימה אם צריך): {APP_URL}/admin/users\n")


# תרגומי מסך הכניסה (השפה נשמרת במכשיר — אותה בחירה כמו באפליקציה).
# err_*: הודעות השרת (בעברית) → מפתח, כדי להציג אותן בשפת המשתמש.
LOGIN_I18N = {
    "he": {"cookie_settings": "הגדרות עוגיות", "skip_pw": "דלג — להיכנס עם קוד בכל פעם", "err_closed": "האתר הזה סגור", "err_rate": "יותר מדי בקשות — נסה שוב בעוד שעה", "err_no_account": "אין חשבון אישי", "title": "כניסה", "enter_email": "הכנס מייל וסיסמה", "password": "סיסמה", "enter": "כניסה",
           "new_user": "משתמש חדש? נשלח לך קוד למייל", "forgot": "שכחתי סיסמה",
           "code_intro": "נשלח קוד בן 6 ספרות אל המייל שלך", "send_code": "שלח קוד",
           "sent_to": "שלחנו קוד בן 6 ספרות אל", "other_email": "מייל אחר / שלח שוב", "back": "חזרה",
           "set_pw_title": "בחר סיסמה לכניסות הבאות", "new_password": "סיסמה (8 תווים לפחות)",
           "confirm_password": "הקלד אותה שוב", "save": "שמירה וכניסה", "pw_mismatch": "הסיסמאות לא זהות",
           "back_to_email": "חזרה לכניסה במייל",
           "legacy_link": "כניסה עם סיסמה (זמני)", "privacy_link": "פרטיות", "terms_link": "תנאי שימוש",
           "agree": "בהרשמה אתה מסכים ל{t} ול{p}.", "ok": "אישור", "generic_err": "שגיאה — נסה שוב",
           "code_len": "הקוד הוא 6 ספרות", "wrong_password": "סיסמה שגויה",
           "err_invalid_email": "כתובת מייל לא תקינה", "err_send_failed": "שליחת המייל נכשלה — נסה שוב בעוד דקה",
           "err_expired": "הקוד פג תוקף — בקש קוד חדש", "err_too_many": "יותר מדי ניסיונות — בקש קוד חדש",
           "err_wrong_code": "קוד שגוי", "err_blocked": "אין גישה לחשבון הזה",
           "err_bad_login": "מייל או סיסמה שגויים",
           "err_locked": "יותר מדי ניסיונות — נסה שוב בעוד 15 דקות או היכנס עם קוד",
           "err_pw_short": "הסיסמה צריכה 8 תווים לפחות", "err_pw_long": "הסיסמה ארוכה מדי",
           "err_pw_reset": "כדי להחליף סיסמה — היכנס עם קוד למייל",
           "have_account": "כבר יש לך חשבון? התחבר",
           "reset_title": "איפוס סיסמה",
           "reset_body": "כתוב לכתובת הזו ונאפס לך את הסיסמה:",
           "reset_no_addr": "פנה למי שנתן לך את הקישור לאתר.",
           "privacy_note": "נשמרים המייל שלך, הליגות והקבוצות שבחרת. הסיסמה נשמרת מעורבלת בלבד — גם לנו אין דרך לקרוא אותה.",
           "new_user_simple": "משתמש חדש? הרשמה", "register_title": "הרשמה — מייל וסיסמה",
           "register_btn": "הרשמה וכניסה", "forgot_admin": "שכחת סיסמה? בקש מהמנהל לאפס אותה",
           "err_exists": "המייל כבר רשום — היכנס עם הסיסמה",
           "err_code_required": "הרשמה דורשת קוד למייל",
           "err_admin_code": "כתובת מנהל דורשת את סיסמת המנהל", "admin_key": "סיסמת מנהל"},
    "en": {"cookie_settings": "Cookie settings", "skip_pw": "Skip — sign in with a code each time", "err_closed": "This site is closed", "err_rate": "Too many requests — try again in an hour", "err_no_account": "No personal account", "title": "Log in", "enter_email": "Enter your email and password", "password": "Password", "enter": "Log in",
           "new_user": "New here? We'll email you a code", "forgot": "Forgot password",
           "code_intro": "We'll send a 6-digit code to your email", "send_code": "Send code",
           "sent_to": "We sent a 6-digit code to", "other_email": "Different email / resend", "back": "Back",
           "set_pw_title": "Choose a password for next time", "new_password": "Password (at least 8 characters)",
           "confirm_password": "Type it again", "save": "Save and continue", "pw_mismatch": "Passwords don't match",
           "back_to_email": "Back to email login",
           "legacy_link": "Log in with password (temporary)", "privacy_link": "Privacy", "terms_link": "Terms",
           "agree": "By signing up you agree to the {t} and the {p} notice.", "ok": "OK", "generic_err": "Something went wrong — try again",
           "code_len": "The code has 6 digits", "wrong_password": "Wrong password",
           "err_invalid_email": "Invalid email address", "err_send_failed": "Couldn't send the email — try again in a minute",
           "err_expired": "The code has expired — request a new one", "err_too_many": "Too many attempts — request a new code",
           "err_wrong_code": "Wrong code", "err_blocked": "This account has no access",
           "err_bad_login": "Wrong email or password",
           "err_locked": "Too many attempts — try again in 15 minutes or log in with a code",
           "err_pw_short": "Password must be at least 8 characters", "err_pw_long": "Password is too long",
           "err_pw_reset": "To change your password, log in with an email code",
           "have_account": "Already have an account? Log in",
           "reset_title": "Password reset",
           "reset_body": "Write to this address and we'll reset your password:",
           "reset_no_addr": "Ask whoever sent you the link to this site.",
           "privacy_note": "We keep your email and the leagues and teams you pick. Your password is stored hashed — we cannot read it either.",
           "new_user_simple": "New here? Sign up", "register_title": "Sign up — email and password",
           "register_btn": "Sign up and log in", "forgot_admin": "Forgot your password? Ask the admin to reset it",
           "err_exists": "This email is already registered — log in with your password",
           "err_code_required": "Signing up requires an email code",
           "err_admin_code": "Admin addresses require the admin password", "admin_key": "Admin password"},
    "es": {"cookie_settings": "Configuración de cookies", "skip_pw": "Omitir — entrar con un código cada vez", "err_closed": "Este sitio está cerrado", "err_rate": "Demasiadas solicitudes — inténtalo en una hora", "err_no_account": "No hay cuenta personal", "title": "Entrar", "enter_email": "Escribe tu correo y contraseña", "password": "Contraseña", "enter": "Entrar",
           "new_user": "¿Nuevo? Te enviamos un código por correo", "forgot": "Olvidé mi contraseña",
           "code_intro": "Te enviaremos un código de 6 dígitos por correo", "send_code": "Enviar código",
           "sent_to": "Enviamos un código de 6 dígitos a", "other_email": "Otro correo / reenviar", "back": "Volver",
           "set_pw_title": "Elige una contraseña para la próxima vez", "new_password": "Contraseña (mínimo 8 caracteres)",
           "confirm_password": "Repítela", "save": "Guardar y entrar", "pw_mismatch": "Las contraseñas no coinciden",
           "back_to_email": "Volver al acceso por correo",
           "legacy_link": "Entrar con contraseña (temporal)", "privacy_link": "Privacidad", "terms_link": "Términos",
           "agree": "Al registrarte aceptas los {t} y la {p}.", "ok": "Aceptar", "generic_err": "Algo salió mal — inténtalo de nuevo",
           "code_len": "El código tiene 6 dígitos", "wrong_password": "Contraseña incorrecta",
           "err_invalid_email": "Correo no válido", "err_send_failed": "No se pudo enviar el correo — inténtalo en un minuto",
           "err_expired": "El código ha caducado — pide uno nuevo", "err_too_many": "Demasiados intentos — pide un código nuevo",
           "err_wrong_code": "Código incorrecto", "err_blocked": "Esta cuenta no tiene acceso",
           "err_bad_login": "Correo o contraseña incorrectos",
           "err_locked": "Demasiados intentos — inténtalo en 15 minutos o entra con un código",
           "err_pw_short": "La contraseña debe tener al menos 8 caracteres", "err_pw_long": "La contraseña es demasiado larga",
           "err_pw_reset": "Para cambiar la contraseña, entra con un código por correo",
           "have_account": "¿Ya tienes cuenta? Inicia sesión",
           "reset_title": "Restablecer contraseña",
           "reset_body": "Escribe a esta dirección y restableceremos tu contraseña:",
           "reset_no_addr": "Pregunta a quien te envió el enlace.",
           "privacy_note": "Guardamos tu correo y las ligas y equipos que elijas. La contraseña se guarda cifrada — nosotros tampoco podemos leerla.",
           "new_user_simple": "¿Nuevo? Regístrate", "register_title": "Registro — correo y contraseña",
           "register_btn": "Registrarme y entrar", "forgot_admin": "¿Olvidaste tu contraseña? Pide al administrador que la restablezca",
           "err_exists": "Este correo ya está registrado — entra con tu contraseña",
           "err_code_required": "El registro requiere un código por correo",
           "err_admin_code": "Las direcciones de administrador requieren la contraseña de administrador",
           "admin_key": "Contraseña de administrador"},
    "fr": {"cookie_settings": "Paramètres des cookies", "skip_pw": "Passer — se connecter avec un code chaque fois", "err_closed": "Ce site est fermé", "err_rate": "Trop de demandes — réessayez dans une heure", "err_no_account": "Pas de compte personnel", "title": "Connexion", "enter_email": "Saisissez votre e-mail et votre mot de passe", "password": "Mot de passe",
           "enter": "Se connecter", "new_user": "Nouveau ? Nous vous envoyons un code par e-mail",
           "forgot": "Mot de passe oublié", "code_intro": "Nous vous enverrons un code à 6 chiffres par e-mail",
           "send_code": "Envoyer le code",
           "sent_to": "Nous avons envoyé un code à 6 chiffres à", "other_email": "Autre e-mail / renvoyer", "back": "Retour",
           "set_pw_title": "Choisissez un mot de passe pour la prochaine fois",
           "new_password": "Mot de passe (8 caractères min.)", "confirm_password": "Retapez-le",
           "save": "Enregistrer et continuer", "pw_mismatch": "Les mots de passe ne correspondent pas",
           "back_to_email": "Retour à la connexion par e-mail",
           "legacy_link": "Connexion par mot de passe (temporaire)", "privacy_link": "Confidentialité", "terms_link": "Conditions",
           "agree": "En vous inscrivant vous acceptez les {t} et la {p}.", "ok": "OK", "generic_err": "Une erreur est survenue — réessayez",
           "code_len": "Le code comporte 6 chiffres", "wrong_password": "Mot de passe incorrect",
           "err_invalid_email": "Adresse e-mail invalide", "err_send_failed": "L'e-mail n'a pas pu être envoyé — réessayez dans une minute",
           "err_expired": "Le code a expiré — demandez-en un nouveau", "err_too_many": "Trop de tentatives — demandez un nouveau code",
           "err_wrong_code": "Code incorrect", "err_blocked": "Ce compte n'a pas accès",
           "err_bad_login": "E-mail ou mot de passe incorrect",
           "err_locked": "Trop de tentatives — réessayez dans 15 minutes ou connectez-vous avec un code",
           "err_pw_short": "Le mot de passe doit comporter au moins 8 caractères", "err_pw_long": "Mot de passe trop long",
           "err_pw_reset": "Pour changer de mot de passe, connectez-vous avec un code reçu par e-mail",
           "have_account": "Vous avez déjà un compte ? Connectez-vous",
           "reset_title": "Réinitialiser le mot de passe",
           "reset_body": "Écrivez à cette adresse et nous le réinitialiserons :",
           "reset_no_addr": "Demandez à la personne qui vous a envoyé le lien.",
           "privacy_note": "Nous conservons votre e-mail et les ligues et équipes choisies. Le mot de passe est stocké chiffré — nous ne pouvons pas le lire non plus.",
           "new_user_simple": "Nouveau ? Inscrivez-vous", "register_title": "Inscription — e-mail et mot de passe",
           "register_btn": "S'inscrire et se connecter", "forgot_admin": "Mot de passe oublié ? Demandez à l'administrateur de le réinitialiser",
           "err_exists": "Cet e-mail est déjà inscrit — connectez-vous avec votre mot de passe",
           "err_code_required": "L'inscription nécessite un code reçu par e-mail",
           "err_admin_code": "Les adresses administrateur exigent le mot de passe administrateur",
           "admin_key": "Mot de passe administrateur"},
}

# מייל הקוד בשפת המשתמש. הנושא מסתיים בקוד (רואים אותו בהתראה בטלפון).
CODE_EMAIL = {
    "he": ("קוד כניסה ל-SpoilerFree: {code}",
           "הקוד שלך: {code}\n\nתקף ל-{m} דקות. אם לא ביקשת — פשוט התעלם מהמייל.\n"),
    "en": ("Your SpoilerFree login code: {code}",
           "Your code: {code}\n\nValid for {m} minutes. If you didn't request it, just ignore this email.\n"),
    "es": ("Tu código de acceso a SpoilerFree: {code}",
           "Tu código: {code}\n\nVálido durante {m} minutos. Si no lo pediste, ignora este correo.\n"),
    "fr": ("Votre code de connexion SpoilerFree : {code}",
           "Votre code : {code}\n\nValable {m} minutes. Si vous ne l'avez pas demandé, ignorez cet e-mail.\n"),
}

LOGIN_PAGE = """<!DOCTYPE html>
<html lang="he" dir="rtl"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>SpoilerFree — כניסה</title>
<link rel="manifest" href="/manifest.webmanifest">
<link rel="apple-touch-icon" href="/icons/apple-touch-icon.png">
<meta name="theme-color" content="#0a0a0f">
<style>
body{background:#0a0a0f;color:#e8e8f0;font-family:sans-serif;display:flex;
align-items:center;justify-content:center;min-height:100vh;margin:0}
.box{background:#13131a;border:1px solid #2a2a3a;border-radius:16px;
padding:2.5rem;text-align:center;max-width:340px;width:90%}
h1{color:#00e5a0;font-size:1.4rem;letter-spacing:2px;margin:0 0 1.5rem}
p{color:#9a9ab0;font-size:0.9rem;line-height:1.6;margin:0 0 1rem}
input{width:100%;padding:0.7rem;border-radius:8px;border:1px solid #2a2a3a;
background:#1a1a24;color:#e8e8f0;font-size:1rem;box-sizing:border-box;
margin-bottom:1rem;text-align:center}
#code{letter-spacing:6px;font-size:1.3rem}
button{width:100%;padding:0.7rem;border-radius:100px;border:none;
background:#00e5a0;color:#000;font-weight:700;font-size:1rem;cursor:pointer}
button:disabled{opacity:0.5}
.link{background:none;color:#6b6b80;font-weight:400;font-size:0.8rem;
margin-top:0.8rem;width:auto;padding:0.2rem;text-decoration:underline}
.err{color:#ff4757;font-size:0.85rem;margin-top:0.8rem;min-height:1.2em}
.ok{color:#00e5a0}
.hint{font-size:0.78rem;color:#6b6b80;margin:0.8rem 0 0}
/* בלי זה הקישורים בתוך "בהרשמה אתה מסכים ל..." הם כחול/סגול של הדפדפן,
   על רקע שחור — הצבע היחיד בעמוד שאינו שלנו */
a{color:#00e5a0}
/* שורת הקישורים המשפטיים. הכלל היה על button בלבד, ולכן שני ה-<a>
   נשארו פריטי flex של body — קישורים כחולים 16px לצד כרטיס הכניסה,
   שדחקו אותו הצידה. את זה רואה כל מי שאינו מחובר, כלומר כל מבקר חדש. */
.legal{position:fixed;bottom:12px;left:0;right:0;display:flex;gap:1rem;
flex-wrap:wrap;align-items:center;justify-content:center}
.cookie-link{width:auto;background:none;border:none;color:#4a4a5a;
font-weight:400;font-size:0.7rem;padding:0.2rem;text-decoration:underline;
cursor:pointer}
.cookie-overlay{position:fixed;inset:0;background:rgba(0,0,0,0.85);display:flex;
align-items:center;justify-content:center;padding:1rem;z-index:10}
.cookie-box{background:#13131a;border:1px solid #2a2a3a;border-radius:12px;
max-width:460px;max-height:80vh;overflow:auto;padding:1.5rem;text-align:start}
.cookie-box h2{font-size:1rem;margin:0 0 0.8rem}
.cookie-box h3{font-size:0.8rem;color:#9a9ab0;margin:1rem 0 0.3rem}
.cookie-box p{font-size:0.78rem;color:#6b6b80;margin:0}
.cookie-box button{margin-top:1.2rem}
[hidden]{display:none!important}
.lang{position:fixed;top:12px;inset-inline-end:12px;background:#13131a;color:#9a9ab0;
border:1px solid #2a2a3a;border-radius:6px;padding:0.2rem 0.4rem;font-size:0.75rem}
</style></head><body>
<select class="lang" id="lang-select" aria-label="Language">
  <option value="he">🌐 עברית</option><option value="en">🌐 English</option>
  <option value="es">🌐 Español</option><option value="fr">🌐 Français</option>
</select>
<div class="box"><h1>SPOILERFREE</h1>

<div id="step-login">
  <p data-i18n="enter_email">הכנס מייל וסיסמה</p>
  <input type="email" id="email" placeholder="you@example.com" autocomplete="username" dir="ltr">
  <input type="password" id="login-pw" autocomplete="current-password" dir="ltr">
  <button id="login-btn" onclick="pwLogin()" data-i18n="enter">כניסה</button>
  <button class="link" id="new-user-btn" onclick="newUser()">משתמש חדש? הרשמה</button>
  <button class="link" id="forgot-btn" onclick="codeMode('reset')" data-i18n="forgot">שכחתי סיסמה</button>
  <button class="link" id="forgot-admin" data-i18n="forgot_admin" onclick="askReset()" hidden>שכחת סיסמה? בקש מהמנהל לאפס אותה</button>
</div>

<div id="step-register" hidden>
  <p data-i18n="register_title">הרשמה — מייל וסיסמה</p>
  <input type="email" id="reg-email" placeholder="you@example.com" autocomplete="username" dir="ltr">
  <input type="password" id="reg-pw" autocomplete="new-password" dir="ltr">
  <input type="password" id="reg-pw2" autocomplete="new-password" dir="ltr">
  <input type="password" id="reg-admin-key" autocomplete="off" dir="ltr" hidden>
  <button id="reg-btn" onclick="register()" data-i18n="register_btn">הרשמה וכניסה</button>
  <p class="hint" id="agree-note"></p>
  <button class="link" onclick="show('step-login')" data-i18n="have_account">כבר יש לך חשבון? התחבר</button>
</div>

<div id="step-email" hidden>
  <p data-i18n="code_intro">נשלח קוד בן 6 ספרות אל המייל שלך</p>
  <input type="email" id="code-email" placeholder="you@example.com" autocomplete="email" dir="ltr">
  <button id="send-btn" onclick="sendCode()" data-i18n="send_code">שלח קוד</button>
  <button class="link" onclick="back()" data-i18n="back">חזרה</button>
</div>

<div id="step-code" hidden>
  <p><span data-i18n="sent_to">שלחנו קוד בן 6 ספרות אל</span><br><b id="sent-to" dir="ltr"></b></p>
  <input id="code" inputmode="numeric" autocomplete="one-time-code" maxlength="6" placeholder="••••••" dir="ltr">
  <button id="verify-btn" onclick="verify()" data-i18n="enter">כניסה</button>
  <button class="link" onclick="show('step-email')" data-i18n="other_email">מייל אחר / שלח שוב</button>
</div>

<div id="step-setpw" hidden>
  <p data-i18n="set_pw_title">בחר סיסמה לכניסות הבאות</p>
  <input type="password" id="new-pw" autocomplete="new-password" dir="ltr">
  <input type="password" id="new-pw2" autocomplete="new-password" dir="ltr">
  <button id="setpw-btn" onclick="setPw()" data-i18n="save">שמירה וכניסה</button>
  <!-- בשלב הזה המשתמש כבר מחובר, ולא היה לו שום מסלול חוץ מרענון ידני -->
  <button class="link" onclick="go()" data-i18n="skip_pw">דלג — להיכנס עם קוד בכל פעם</button>
</div>

<div id="step-legacy" hidden>
  <input type="password" id="pw" placeholder="סיסמה">
  <button onclick="legacy()" data-i18n="enter">כניסה</button>
  <button class="link" onclick="back()" data-i18n="back_to_email">חזרה לכניסה במייל</button>
</div>

<div class="err" id="err"></div>
<p class="hint" data-i18n="privacy_note">נשמרים המייל שלך, הליגות והקבוצות שבחרת. הסיסמה נשמרת מעורבלת בלבד — גם לנו אין דרך לקרוא אותה.</p>
<!--LEGACY--><button class="link" id="legacy-link" onclick="show('step-legacy')" data-i18n="legacy_link">כניסה עם סיסמה (זמני)</button><!--/LEGACY-->
</div>
<div class="legal">
  <button class="cookie-link" onclick="openCookies()"
          data-i18n="cookie_settings">הגדרות עוגיות</button>
  <a class="cookie-link" id="privacy-link" href="/privacy" target="_blank" rel="noopener"
     data-i18n="privacy_link">פרטיות</a>
  <a class="cookie-link" id="terms-link" href="/terms" target="_blank" rel="noopener"
     data-i18n="terms_link">תנאי שימוש</a>
</div>
<div class="cookie-overlay" id="cookie-overlay" hidden
     onclick="if (event.target === this) closeCookies()">
  <div class="cookie-box"><div id="cookie-body"></div>
    <button onclick="closeCookies()" data-i18n="ok">אישור</button></div>
</div>
<script>
const $ = id => document.getElementById(id);
// ── שפה (אותה בחירה כמו באפליקציה — נשמרת במכשיר) ──
const L = __LOGIN_I18N__;
// code_required: הרשמה רק עם קוד למייל; can_send: יש שליחת מיילים ("שכחתי סיסמה")
const CFG = __LOGIN_CFG__;
if (!CFG.can_send) { $('forgot-btn').hidden = true; $('forgot-admin').hidden = false; }
// בלי בחירה שמורה — לפי שפת המכשיר. מכשיר בשפה שאין לנו → אנגלית
function deviceLang() {
  const tags = navigator.languages && navigator.languages.length
    ? navigator.languages : [navigator.language || 'en'];
  for (const tag of tags) {
    const code = String(tag).toLowerCase().split('-')[0];
    if (code === 'iw') return 'he';           // קוד ישן לעברית
    if (L[code]) return code;
  }
  return 'en';
}
let LANG = null;
try { LANG = localStorage.getItem('sf:lang'); } catch (e) {}
if (!LANG || !L[LANG]) LANG = deviceLang();
const t = k => (L[LANG] || {})[k] ?? L.he[k] ?? k;
function applyLang() {
  document.documentElement.lang = LANG;
  document.documentElement.dir = LANG === 'he' ? 'rtl' : 'ltr';
  document.title = 'SpoilerFree — ' + t('title');
  document.querySelectorAll('[data-i18n]').forEach(el => { el.textContent = t(el.dataset.i18n); });
  $('pw').placeholder = t('password');
  $('login-pw').placeholder = t('password');
  $('new-pw').placeholder = t('new_password');
  $('new-pw2').placeholder = t('confirm_password');
  $('reg-pw').placeholder = t('new_password');
  $('reg-pw2').placeholder = t('confirm_password');
  $('reg-admin-key').placeholder = t('admin_key');
  $('new-user-btn').textContent = t(CFG.code_required ? 'new_user' : 'new_user_simple');
  $('lang-select').value = LANG;
  $('privacy-link').href = '/privacy?lang=' + LANG;
  // ליד כפתור ההרשמה, כי שם נוצר החשבון — לא בתחתית העמוד
  $('agree-note').innerHTML = t('agree').replace('{t}',
      `<a href="/terms?lang=${LANG}" target="_blank" rel="noopener">${t('terms_link')}</a>`)
    .replace('{p}',
      `<a href="/privacy?lang=${LANG}" target="_blank" rel="noopener">${t('privacy_link')}</a>`);
  $('terms-link').href = '/terms?lang=' + LANG;
}
$('lang-select').addEventListener('change', e => {
  LANG = e.target.value;
  try { localStorage.setItem('sf:lang', LANG); } catch (err) {}
  applyLang();
});
// הודעות השרת מגיעות בעברית — מתורגמות לפי המפתח שלהן
function serverMsg(detail) {
  const k = Object.keys(L.he).find(k => k.startsWith('err_') && L.he[k] === detail);
  return k ? t(k) : (detail || t('generic_err'));
}
applyLang();
// מסכים: מייל+סיסמה (ברירת מחדל) · בקשת קוד (משתמש חדש / שכחתי) · קוד · קביעת סיסמה
let MODE = 'new';
function show(id) {
  for (const s of ['step-login','step-register','step-email','step-code','step-setpw','step-legacy']) $(s).hidden = s !== id;
  $('err').textContent = '';
}
function back() { show('step-login'); $('email').focus(); }
function go() { location.href = '/?fresh=' + Date.now(); }
function codeMode(m) {
  MODE = m;
  $('code-email').value = $('email').value.trim();
  show('step-email'); $('code-email').focus();
}
function newUser() {
  if (CFG.code_required) { codeMode('new'); return; }
  $('reg-email').value = $('email').value.trim();
  show('step-register'); $('reg-email').focus();
}
async function register() {
  const email = $('reg-email').value.trim(), a = $('reg-pw').value, b = $('reg-pw2').value;
  if (!email || !a) return;
  if (a !== b) { $('err').textContent = t('pw_mismatch'); return; }
  $('reg-btn').disabled = true; $('err').textContent = '';
  try {
    await post('/auth/register', {email, password: a, lang: LANG, admin_key: $('reg-admin-key').value});
    go();
  } catch (e) {
    $('err').textContent = e.message;
    // כתובת מנהל — השדה מופיע רק כשהשרת מבקש (לא חושפים מראש מי המנהל)
    if (e.message === t('err_admin_code')) { $('reg-admin-key').hidden = false; $('reg-admin-key').focus(); }
  }
  finally { $('reg-btn').disabled = false; }
}
async function pwLogin() {
  const email = $('email').value.trim(), password = $('login-pw').value;
  if (!email || !password) return;
  $('login-btn').disabled = true; $('err').textContent = '';
  try { await post('/auth/login', {email, password}); go(); }
  catch (e) { $('err').textContent = e.message; }
  finally { $('login-btn').disabled = false; }
}
async function setPw() {
  const a = $('new-pw').value, b = $('new-pw2').value;
  if (a !== b) { $('err').textContent = t('pw_mismatch'); return; }
  $('setpw-btn').disabled = true; $('err').textContent = '';
  try { await post('/auth/set_password', {password: a}); go(); }
  catch (e) { $('err').textContent = e.message; }
  finally { $('setpw-btn').disabled = false; }
}
async function post(url, body) {
  const r = await fetch(url, {method:'POST', headers:{'Content-Type':'application/json'},
                              body: JSON.stringify(body)});
  let j = {}; try { j = await r.json(); } catch (e) {}
  if (!r.ok) throw new Error(serverMsg(j.detail));
  return j;
}
async function sendCode() {
  const email = $('code-email').value.trim();
  if (!email) return;
  $('send-btn').disabled = true; $('err').textContent = '';
  try {
    await post('/auth/request_code', {email, lang: LANG});
    $('sent-to').textContent = email; $('code').value = ''; show('step-code'); $('code').focus();
  } catch (e) { $('err').textContent = e.message; }
  finally { $('send-btn').disabled = false; }
}
async function verify() {
  const code = $('code').value.trim();
  if (code.length !== 6) { $('err').textContent = t('code_len'); return; }
  $('verify-btn').disabled = true; $('err').textContent = '';
  try {
    const j = await post('/auth/verify', {email: $('code-email').value.trim(), code, lang: LANG});
    // כניסה ראשונה (אין סיסמה) או "שכחתי סיסמה" — קובעים סיסמה; אחרת נכנסים
    if (j.need_password || MODE === 'reset') { show('step-setpw'); $('new-pw').focus(); }
    else go();
  } catch (e) { $('err').textContent = e.message; }
  finally { $('verify-btn').disabled = false; }
}
async function legacy() {
  try { await post('/login', {password: $('pw').value}); location.href = '/?fresh=' + Date.now(); }
  catch (e) { $('err').textContent = t('wrong_password'); }
}
async function openCookies() {
  $('cookie-overlay').hidden = false;
  try { $('cookie-body').innerHTML = await (await fetch('/cookies?lang=' + LANG)).text(); } catch (e) {}
}
function closeCookies() { $('cookie-overlay').hidden = true; }
$('email').addEventListener('keydown', e => { if (e.key === 'Enter') $('login-pw').focus(); });
$('login-pw').addEventListener('keydown', e => { if (e.key === 'Enter') pwLogin(); });
$('code-email').addEventListener('keydown', e => { if (e.key === 'Enter') sendCode(); });
$('new-pw2').addEventListener('keydown', e => { if (e.key === 'Enter') setPw(); });
$('reg-pw2').addEventListener('keydown', e => { if (e.key === 'Enter') register(); });
$('code').addEventListener('keydown', e => { if (e.key === 'Enter') verify(); });
$('code').addEventListener('input', e => { if (e.target.value.trim().length === 6) verify(); });
$('pw').addEventListener('keydown', e => { if (e.key === 'Enter') legacy(); });
// עמוד ברירת המחדל הוא הרשמה — רוב מי שמגיע לכאן עוד לא רשום.
// כשהרשמה דורשת קוד למייל, המסך הזה לא רלוונטי ונשארים בכניסה.
if (CFG.closed) { $('new-user-btn').hidden = true; $('email').focus(); }
else if (CFG.code_required) { $('email').focus(); }
else { show('step-register'); $('reg-email').focus(); }

// "שכחתי סיסמה" בלי שליחת מיילים: מציגים למי לכתוב
async function askReset() {
  let addr = '';
  try { addr = (await fetch('/auth/contact').then(r => r.json())).email || ''; } catch (e) {}
  $('cookie-body').innerHTML = '<h2>' + t('reset_title') + '</h2><p>'
    + (addr ? t('reset_body') + '</p><p dir="ltr"><b><a href="mailto:' + addr
              + '?subject=SpoilerFree">' + addr + '</a></b>'
       : t('reset_no_addr'))
    + '</p>';
  $('cookie-overlay').hidden = false;
}
</script></body></html>"""


def render_login_page() -> str:
    page = LOGIN_PAGE.replace("__LOGIN_I18N__", json.dumps(LOGIN_I18N, ensure_ascii=False))
    # closed: ALLOWED_EMAILS מוגדר, ולכן הרשמה תיענה ב-403 לכל מייל אחר.
    # בלי הדגל הזה מסך ההרשמה היה ברירת המחדל דווקא שם
    page = page.replace("__LOGIN_CFG__", json.dumps({"code_required": EMAIL_CODE_REQUIRED,
                                                     "can_send": email_sender_ready(),
                                                     "closed": bool(ALLOWED_EMAILS)}))
    if not APP_PASSWORD:
        page = re.sub(r"<!--LEGACY-->.*?<!--/LEGACY-->", "", page, flags=re.S)
    return page


ADMIN_USERS_PAGE = """<!DOCTYPE html>
<html lang="he" dir="rtl"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>SpoilerFree — משתמשים</title>
<style>
body{background:#0a0a0f;color:#e8e8f0;font-family:sans-serif;margin:0;padding:1.5rem}
h1{color:#00e5a0;font-size:1.3rem;letter-spacing:2px;margin:0 0 0.3rem}
a{color:#00e5a0}
.sub{color:#6b6b80;font-size:0.85rem;margin-bottom:1.2rem}
.kpis{display:flex;gap:0.75rem;flex-wrap:wrap;margin-bottom:1.2rem}
.kpi{background:#13131a;border:1px solid #2a2a3a;border-radius:10px;padding:0.7rem 1rem;min-width:110px}
.kpi b{display:block;font-size:1.4rem;color:#00e5a0}
.kpi span{font-size:0.75rem;color:#6b6b80}
.wrap{overflow-x:auto}
table{border-collapse:collapse;width:100%;font-size:0.85rem;min-width:820px}
th,td{padding:0.55rem 0.6rem;border-bottom:1px solid #2a2a3a;text-align:right;white-space:nowrap}
th{color:#6b6b80;font-weight:400;font-size:0.75rem}
.st{padding:0.1rem 0.5rem;border-radius:100px;font-size:0.72rem}
.pending{background:rgba(255,193,7,0.15);color:#ffc107}
.approved{background:rgba(0,229,160,0.12);color:#00e5a0}
.blocked{background:rgba(255,71,87,0.15);color:#ff4757}
button{background:transparent;border:1px solid #2a2a3a;color:#e8e8f0;border-radius:6px;
padding:0.25rem 0.6rem;cursor:pointer;font-size:0.78rem;margin-left:0.3rem}
button.go{border-color:#00e5a0;color:#00e5a0}
button.no{border-color:#ff4757;color:#ff4757}
.muted{color:#6b6b80}
</style></head><body>
<h1>SPOILERFREE — משתמשים</h1>
<div class="sub"><a href="/">← חזרה לאפליקציה</a> ·
<a href="/admin/gmail/connect">חיבור Gmail לשליחת קודים</a> · <a href="/debug/mail">בדיקת מייל</a></div>
<div class="kpis" id="kpis"></div>
<div class="wrap"><table>
<thead><tr><th>מייל</th><th>סטטוס</th><th>נרשם</th><th>כניסה אחרונה</th>
<th>כניסות</th><th>פתיחות אפליקציה</th><th>משחקים שנפתחו</th><th>תקצירים שנצפו</th>
<th>ליגות מובילות</th><th>פעילות אחרונה</th><th></th></tr></thead>
<tbody id="rows"><tr><td colspan="11" class="muted">טוען...</td></tr></tbody>
</table></div>
<h1 style="margin-top:2rem">מי מעלה ראשון — ליגת העל (21 ימים)</h1>
<div class="sub muted">דקות מסיום המשחק (משוער: פתיחה + 115 דק') עד שהתקציר עלה.
יוטיוב — שעת ההעלאה בפועל; אתרים — מתי מצאנו את הקישור (דיוק של כחצי שעה).</div>
<div class="wrap"><table style="min-width:0">
<thead><tr><th>מקור</th><th>ראשון (פעמים)</th><th>נמצא</th><th>חציון (דק')</th></tr></thead>
<tbody id="timing"><tr><td colspan="4" class="muted">טוען...</td></tr></tbody>
</table></div>
<div class="wrap" style="margin-top:1rem"><table style="min-width:0">
<thead><tr><th>משחק</th><th>תאריך</th><th>ראשון</th><th>כל המקורות (דק' מהסיום)</th></tr></thead>
<tbody id="timing_m"></tbody>
</table></div>
<script>
const LEAGUES = {premier:'פרמייר', championship:"צ'מפיונשיפ", israel:'ליגת העל', bundesliga:'בונדסליגה', laliga:'לה ליגה',
  seriea:'סריה A', ligue1:'ליג 1', ucl:"צ'מפיונס", uel:'ליגה אירופית', mls:'MLS', argentina:'ארגנטינה'};
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function when(iso) {
  if (!iso) return '<span class="muted">—</span>';
  const d = new Date(iso);
  return d.toLocaleDateString('he-IL', {day:'2-digit', month:'2-digit'}) + ' ' +
         d.toLocaleTimeString('he-IL', {hour:'2-digit', minute:'2-digit'});
}
const ST = {pending:'ממתין', approved:'מאושר', blocked:'חסום'};
async function load() {
  const r = await fetch('/admin/api/users');
  if (!r.ok) { document.getElementById('rows').innerHTML = '<tr><td colspan="11">אין הרשאה</td></tr>'; return; }
  const {users, kpis} = await r.json();
  document.getElementById('kpis').innerHTML =
    [['משתמשים', kpis.total], ['ממתינים', kpis.pending], ['פעילים 7 ימים', kpis.active_7d],
     ['תקצירים שנצפו', kpis.plays],
     ['יוטיוב היום (בלם ב-9,000)', kpis.yt_units_today.toLocaleString()]].map(([k,v]) => `<div class="kpi"><b>${v}</b><span>${k}</span></div>`).join('');
  document.getElementById('rows').innerHTML = users.map(u => {
    const e = esc(u.email);
    const btns = u.status === 'approved'
      ? `<button class="no" onclick="setStatus('${e}','blocked')">חסום</button>`
      : `<button class="go" onclick="setStatus('${e}','approved')">אשר</button>` +
        (u.status === 'pending' ? `<button class="no" onclick="setStatus('${e}','blocked')">דחה</button>` : '');
    const reset = u.has_password ? `<button onclick="resetPw('${e}')">איפוס סיסמה</button>` : '';
    const lg = (u.top_leagues || []).map(l => LEAGUES[l] || esc(l)).join(', ') || '<span class="muted">—</span>';
    return `<tr><td dir="ltr">${e}${u.is_admin ? ' ⭐' : ''}</td>
      <td><span class="st ${u.status}">${ST[u.status] || u.status}</span></td>
      <td>${when(u.created_at)}</td><td>${when(u.last_login)}</td>
      <td>${u.login_count || 0}</td><td>${u.app_open || 0}</td><td>${u.match_open || 0}</td>
      <td>${u.highlight_play || 0}</td><td>${lg}</td><td>${when(u.last_active)}</td>
      <td>${u.is_admin ? '' : btns + reset}</td></tr>`;
  }).join('') || '<tr><td colspan="11" class="muted">אין משתמשים עדיין</td></tr>';
}
async function setStatus(email, status) {
  const r = await fetch('/admin/api/users/' + encodeURIComponent(email), {
    method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({status})});
  if (!r.ok) alert('נכשל'); load();
}
async function resetPw(email) {
  if (!confirm('לאפס את הסיסמה של ' + email + '? המשתמש יירשם שוב עם אותו מייל וסיסמה חדשה.')) return;
  const r = await fetch('/admin/api/users/' + encodeURIComponent(email) + '/reset_password', {method:'POST'});
  if (!r.ok) alert('נכשל'); load();
}
async function loadTiming() {
  const r = await fetch('/admin/api/timing?league=israel&days=21');
  if (!r.ok) return;
  const d = await r.json();
  document.getElementById('timing').innerHTML = d.summary.map(s =>
    `<tr><td>${esc(s.source)}</td><td>${s.first}</td><td>${s.found} / ${d.matches_over}</td><td>${s.median_min}</td></tr>`
  ).join('') || '<tr><td colspan="4" class="muted">אין נתונים עדיין — נאסף מהמחזור הבא</td></tr>';
  document.getElementById('timing_m').innerHTML = d.matches.map(m =>
    `<tr><td>${esc(m.match)}</td><td>${esc(m.date)}</td><td>${esc(m.first)}</td><td>` +
    Object.entries(m.delays).map(([k, v]) => esc(k) + ': ' + v).join(' · ') + '</td></tr>').join('');
}
load();
loadTiming();
</script></body></html>"""

# ── DB ─────────────────────────────────────────────────

class _LibsqlRow:
    """התנהגות כמו sqlite3.Row: row["col"], row[0], dict(row)."""
    __slots__ = ("_cols", "_vals")

    def __init__(self, cols, vals):
        self._cols, self._vals = cols, vals

    def __getitem__(self, key):
        if isinstance(key, int):
            return self._vals[key]
        return self._vals[self._cols.index(key)]

    def keys(self):
        return list(self._cols)

    def __len__(self):
        return len(self._vals)

    def __repr__(self):
        return repr(dict(zip(self._cols, self._vals)))


class _LibsqlCursor:
    def __init__(self, cur):
        self._cur = cur
        self._cols = [d[0] for d in (cur.description or [])]

    def fetchone(self):
        r = self._cur.fetchone()
        return _LibsqlRow(self._cols, r) if r is not None else None

    def fetchall(self):
        return [_LibsqlRow(self._cols, r) for r in self._cur.fetchall()]


# ── חיבור Turso משותף לכל התהליך ───────────────────────
# libsql.connect() מסנכרן מול הענן, וכל בקשה פתחה חיבור משלה — לפעמים
# כמה, כי אותה בקשה קוראת ל-get_db() יותר מפעם אחת. כל סנכרון הוא סבב
# רשת, ולכן כל פעולה באתר שילמה על כך. כאן: חיבור אחד, שמסונכרן לכל
# היותר פעם ב-TURSO_SYNC_SEC. כתיבה עדיין מסנכרנת מיד — היא חייבת
# להגיע לענן, ומיד אחריה קוראים את מה שנכתב.
# למה 60 שניות: יש instance אחד, והכתיבות שלו מסנכרנות מיד — כלומר
# החלון הזה מגן רק מפני כתיבה שנעשתה מחוץ לאתר. ב-20 שניות רוב
# הבקשות חצו אותו וממילא שילמו סבב רשת (skipped=0 בפרודקשן, 19.9.26).
TURSO_SYNC_SEC = float(os.environ.get("TURSO_SYNC_SEC", "60"))
# מתג חירום: TURSO_SHARED=0 מחזיר חיבור-לכל-בקשה כמו קודם
TURSO_SHARED   = os.environ.get("TURSO_SHARED", "1") != "0"
_LIBSQL_LOCK   = threading.RLock()
_libsql_state  = {"conn": None, "synced_at": 0.0,
                  "syncs": 0, "skipped": 0, "errors": 0, "rebuilds": 0, "fails": 0}


def _libsql_connect():
    return libsql.connect("turso_replica.db",
                          sync_url=TURSO_DATABASE_URL,
                          auth_token=TURSO_AUTH_TOKEN)


def _shared_libsql():
    """החיבור המשותף, מרוענן מהענן לא יותר מפעם ב-TURSO_SYNC_SEC.
    סנכרון שנכשל לא מפיל כלום — הרפליקה המקומית עדיין קריאה."""
    st = _libsql_state
    with _LIBSQL_LOCK:
        if st["conn"] is None:
            # אחרי deploy הדיסק ריק, והחיבור הראשון מושך את כל ה-DB
            st["conn"] = _libsql_connect()
            st["synced_at"] = time.time()
            st["syncs"] += 1
            return st["conn"]
        now = time.time()
        if now - st["synced_at"] >= TURSO_SYNC_SEC:
            try:
                st["conn"].sync()
                st["syncs"] += 1
            except Exception as e:
                st["errors"] += 1
                print(f"[turso] sync failed: {e}")
            st["synced_at"] = now     # גם כישלון ממתין למחזור הבא
        else:
            st["skipped"] += 1
        return st["conn"]


# כמה כישלונות רצופים בחיבור המשותף לפני שמוותרים עליו לגמרי. אם
# libsql האמיתי לא סובל שימוש מכמה threads, האתר יחזור מעצמו להתנהגות
# הישנה במקום להחזיר שגיאות — בלי שאף אחד יצטרך לגעת ב-Render.
SHARED_FAIL_LIMIT = 3


def _note_shared_failure(err):
    global TURSO_SHARED
    _libsql_state["fails"] = _libsql_state.get("fails", 0) + 1
    # הסיבה עצמה: בלי לראות אותה אי אפשר לדעת אם זו בעיית threads
    # (שתחזור בכל בקשה מקבילה) או תקלת רשת חד-פעמית
    _libsql_state["last_error"] = f"{type(err).__name__}: {err}"[:200]
    _libsql_state["last_error_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    _libsql_state["last_error_thread"] = threading.current_thread().name
    print(f"[turso] shared connection failed ({_libsql_state['fails']}): {err}")
    if _libsql_state["fails"] >= SHARED_FAIL_LIMIT and TURSO_SHARED:
        TURSO_SHARED = False
        print("[turso] giving up on the shared connection — "
              "back to one per request")


def _drop_shared_libsql():
    """חיבור שנשבר — נבנה מחדש בפעם הבאה, במקום להחזיר שגיאות לנצח."""
    with _LIBSQL_LOCK:
        old = _libsql_state["conn"]
        _libsql_state["conn"] = None
        _libsql_state["rebuilds"] += 1
    if old is not None:
        try:
            old.close()
        except Exception:
            pass


class _LibsqlConn:
    """עוטף חיבור libsql כך שיתנהג כמו sqlite3 עם row_factory=Row.
    commit() גם מסנכרן מול הענן, כדי שקריאות עוקבות יראו את הכתיבה.
    shared=True — החיבור משותף לכל התהליך, ולכן close() לא סוגר אותו,
    והפעולות ננעלות כדי שלא ירוצו משני threads בו-זמנית."""

    def __init__(self, conn, shared=False):
        self._conn = conn
        self._shared = shared

    def _lock(self):
        return _LIBSQL_LOCK if self._shared else _NULL_LOCK

    def _run(self, make):
        """נכשל על החיבור המשותף? מנסים פעם אחת על חיבור טרי משלנו.
        אי אפשר לבדוק כאן את libsql האמיתי (אין לו build ל-3.14), ולכן
        תקלה בשיתוף מורידה את הבקשה הזו להתנהגות הישנה במקום להיכשל."""
        with self._lock():
            try:
                return make(self._conn)
            except Exception as first:
                if not self._shared:
                    raise
                _drop_shared_libsql()
                _note_shared_failure(first)
                try:
                    fresh = _libsql_connect()
                except Exception:
                    raise first
                self._conn, self._shared = fresh, False
                return make(fresh)

    def execute(self, sql, params=()):
        p = tuple(params)
        return self._run(lambda c: _LibsqlCursor(c.execute(sql, p)))

    def executemany(self, sql, seq):
        rows = [tuple(x) for x in seq]
        return self._run(lambda c: c.executemany(sql, rows))

    def commit(self):
        self._run(lambda c: c.commit())
        with self._lock():
            try:
                self._conn.sync()
                _libsql_state["syncs"] += 1
                _libsql_state["synced_at"] = time.time()
            except Exception as e:
                _libsql_state["errors"] += 1
                print(f"[turso] sync after commit failed: {e}")

    def close(self):
        if self._shared:
            return          # חיבור משותף — נשאר פתוח לבקשה הבאה
        try:
            self._conn.close()
        except Exception:
            pass


class _NullLock:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


_NULL_LOCK = _NullLock()


def get_db():
    if TURSO_DATABASE_URL and libsql is not None:
        # embedded replica: קובץ מקומי (קריאות מהירות) שמסונכרן ל-Turso
        try:
            if TURSO_SHARED:
                return _LibsqlConn(_shared_libsql(), shared=True)
            return _LibsqlConn(_libsql_connect())
        except Exception as e:
            # Turso לא זמין? האתר ממשיך על sqlite מקומי במקום ליפול
            _libsql_state["conn"] = None
            print(f"[turso] connect failed — falling back to local sqlite: {e}")

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def _add_missing_columns(conn, table: str, cols) -> None:
    """מוסיף עמודות שחסרות, לפי מה שקיים בפועל.

    קודם זה היה ALTER בתוך try/except — "כבר קיימת" הוא מצב צפוי. אבל
    מול החיבור המשותף כל שגיאה כזו זורקת את החיבור, נספרת ככשל, ואחרי
    שלושה כאלה התהליך מוותר על השיתוף. בעלייה יש שבע עמודות כאלה, וזה
    היה עניין של מזל שזה נעצר על אחת (נמדד בפרודקשן, 26.9.26).
    """
    have = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    for col in cols:
        if col.split()[0] not in have:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {col}")


def init_db():
    conn = get_db()

    conn.execute("""
        CREATE TABLE IF NOT EXISTS matches (
            id           TEXT PRIMARY KEY,
            league_key   TEXT,
            home_team    TEXT,
            away_team    TEXT,
            home_team_id TEXT,
            away_team_id TEXT,
            date_utc     TEXT,
            time_utc     TEXT,
            venue        TEXT,
            matchday     INTEGER,
            status       TEXT DEFAULT 'scheduled',
            fetched_at   TEXT
        )
    """)
    # תוצאות (16.9.26) — לטבלה קיימת. נשלחות רק כשהמשתמש ביקש לראות
    _add_missing_columns(conn, "matches", ("home_score INTEGER", "away_score INTEGER"))

    conn.execute("""
        CREATE TABLE IF NOT EXISTS clubs (
            id             TEXT PRIMARY KEY,
            name           TEXT,
            short_name     TEXT,
            league_key     TEXT,
            tier           INTEGER DEFAULT 2,
            yt_channel_id  TEXT DEFAULT '',
            fd_team_id     TEXT DEFAULT '',
            active         INTEGER DEFAULT 1
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS highlight_cache (
            match_id   TEXT,
            source_id  TEXT,
            videos_json TEXT,
            found_at   TEXT,
            PRIMARY KEY (match_id, source_id)
        )
    """)

    # מי העלה ראשון (#10): הפעם הראשונה שכל מקור נמצא — לא נדרס ברענון
    conn.execute("""
        CREATE TABLE IF NOT EXISTS highlight_first_seen (
            match_id   TEXT,
            source_id  TEXT,
            first_seen TEXT,
            published  TEXT,
            PRIMARY KEY (match_id, source_id)
        )
    """)

    # כניסה אישית + מעקב שימוש
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            email        TEXT PRIMARY KEY,
            status       TEXT DEFAULT 'pending',
            is_admin     INTEGER DEFAULT 0,
            created_at   TEXT,
            approved_at  TEXT,
            last_login   TEXT,
            login_count  INTEGER DEFAULT 0
        )
    """)
    # כניסה עם סיסמה (13.9.26) — עמודות חדשות לטבלה קיימת ב-Turso
    _add_missing_columns(conn, "users",
                         ("password_hash TEXT", "pw_fails INTEGER DEFAULT 0",
                          "pw_locked_until TEXT", "pw_reset_until TEXT",
                          "onboarded_at TEXT"))   # מסכי הפתיחה (#32) הוצגו
    conn.execute("""
        CREATE TABLE IF NOT EXISTS login_codes (
            email      TEXT PRIMARY KEY,
            code_hash  TEXT,
            expires_at TEXT,
            attempts   INTEGER DEFAULT 0,
            sent_at    TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            token_hash TEXT PRIMARY KEY,
            email      TEXT,
            created_at TEXT,
            expires_at TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS events (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            email    TEXT,
            ts       TEXT,
            type     TEXT,
            league   TEXT,
            match_id TEXT,
            detail   TEXT
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_events_email ON events(email)")
    # מועדפים: מפתח קבוצה אחיד (team_key) — חל על הקבוצה בכל מפעל.
    # league_key נשאר בסכמה (ריק) מגרסה קודמת שבה הסימון היה לפי ליגה.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS favorites (
            email      TEXT,
            league_key TEXT,
            team       TEXT,
            PRIMARY KEY (email, league_key, team)
        )
    """)
    # ליגות מועדפות (#32) — טבלה נפרדת: favorites שמורה לקבוצות (מפתח אחיד)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS favorite_leagues (
            email      TEXT,
            league_key TEXT,
            PRIMARY KEY (email, league_key)
        )
    """)
    # ליגות מוסתרות — לא מוצגות ב"לפי יום" (משחקי קבוצה מועדפת כן)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS hidden_leagues (
            email      TEXT,
            league_key TEXT,
            PRIMARY KEY (email, league_key)
        )
    """)
    # העדפות אישיות (scores_default: off / all / match)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS prefs (
            email TEXT,
            key   TEXT,
            value TEXT,
            PRIMARY KEY (email, key)
        )
    """)
    # המרה חד-פעמית של שורות מהגרסה לפי-ליגה (שם מקור → מפתח אחיד)
    old = conn.execute("SELECT email, league_key, team FROM favorites "
                       "WHERE league_key != ''").fetchall()
    for r in old:
        conn.execute("INSERT OR IGNORE INTO favorites (email, league_key, team) VALUES (?, '', ?)",
                     (r["email"], team_key(r["team"])))
        conn.execute("DELETE FROM favorites WHERE email=? AND league_key=? AND team=?",
                     (r["email"], r["league_key"], r["team"]))

    conn.commit()

    # מועדוני פרמייר ליג 2026-27 — ערוצים מופו ואומתו ידנית (29/8/26); 7 ערוצים תוקנו אחרי אימות /debug/channels (1/9/26).
    # הקוד הוא מקור האמת: בכל עלייה הטבלה נבנית מחדש מהרשימה הזו.
    premier_clubs = PREMIER_CLUBS

    # seed מנוהל-גרסה: מזריעים מחדש רק כשהרשימה בקוד השתנתה (הקפץ את
    # SEED_VERSION אחרי כל עריכה שלה). אחרת — מה שב-DB, כולל מיפויים
    # שנעשו עם /admin/set_channel, שורד restarts ו-deploys.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS meta (
            key   TEXT PRIMARY KEY,
            value TEXT
        )
    """)
    SEED_VERSION = 2  # v2 = תיקון 7 ערוצי הפרמייר (1/9/26)
    row = conn.execute("SELECT value FROM meta WHERE key='clubs_seed_version'").fetchone()
    current = int(row["value"]) if row else 0
    if current < SEED_VERSION:
        conn.execute("DELETE FROM clubs WHERE league_key='premier'")
        conn.executemany("""
            INSERT OR REPLACE INTO clubs
            (id, name, short_name, league_key, tier, yt_channel_id, fd_team_id)
            VALUES (?,?,?,?,?,?,?)
        """, premier_clubs)
        conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('clubs_seed_version', ?)",
                     (str(SEED_VERSION),))
        print(f"[seed] clubs reseeded to version {SEED_VERSION}")

    # ניקוי חד-פעמי (16.9.26): תקצירים של ליגת העל שנשמרו לפני הכלל המחמיר
    # הצביעו על משחקים אחרים — תוצאה שמורה מוגשת כמו שהיא, אז מוחקים פעם אחת
    if not conn.execute("SELECT 1 FROM meta WHERE key='israel_cache_v2'").fetchone():
        conn.execute("DELETE FROM highlight_cache WHERE source_id IN ('sport1','sport5','ipfl') "
                     "AND match_id IN (SELECT id FROM matches WHERE league_key='israel')")
        conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('israel_cache_v2', '1')")
        print("[seed] cleared Israeli highlight cache (strict both-teams rule)")

    # ניקוי משחקים מלפני תחילת השלב (min_date) — למשל מוקדמות הצ'מפיונס
    for lk, cfg in LEAGUES.items():
        if cfg.get("min_date"):
            conn.execute("DELETE FROM matches WHERE league_key=? AND date_utc<?",
                         (lk, cfg["min_date"]))

    conn.commit()
    conn.close()

# ── TheSportsDB status mapping ────────────────────────

def map_sportsdb_status(event: dict) -> str:
    """Map TheSportsDB event to our internal status."""
    raw = (event.get("strStatus") or "").strip()

    if raw in ("Match Finished", "FT", "AET", "AP", "PEN"):
        return "FINISHED"
    if raw in ("1H", "HT", "2H", "ET", "BT", "P", "LIVE"):
        return "LIVE"
    if raw in ("Postponed", "PPD"):
        return "POSTPONED"
    if raw in ("Cancelled", "CANC", "Abandoned", "ABD"):
        return "CANCELLED"

    # Fallback: if we have scores, it's finished
    if event.get("intHomeScore") is not None and event.get("intAwayScore") is not None:
        return "FINISHED"

    return "SCHEDULED"

# ── Store / fetch matches ──────────────────────────────

_OVER_STATUSES = ("FINISHED", "FT", "AET", "PEN", "AP", "Match Finished")
_MATCH_COLS = ("home_team", "away_team", "home_team_id", "away_team_id",
               "date_utc", "time_utc", "venue", "matchday", "status",
               # תוצאות: נשמרות תמיד, נשלחות ללקוח רק לפי בקשה מפורשת
               "home_score", "away_score")


def _sync_league_rows(conn, league_key: str, incoming: dict,
                      purge: bool = False, hard: bool = False,
                      guard_status: bool = False, mark_fresh: bool = True) -> dict:
    """כותב לטבלת matches רק את מה שהשתנה. incoming: {id: {col: val}}.
    ב-Turso כל כתיבה היא סבב רשת לענן — כתיבה מחדש של כל ~380 שורות
    הליגה בכל רענון לקחה ~30 שניות. במצב יציב זה עכשיו כמה כתיבות בודדות.
    purge: מוחק שורות שהמקור כבר לא מחזיר — רק עתידיות ולא ידניות
    (היסטוריה שהסתיימה ושורות הלוח הידני שורדות); hard: את כולן.
    guard_status: לא מורידים FINISHED/LIVE בחזרה ל-SCHEDULED (sportsdb)."""
    now = datetime.now(timezone.utc).isoformat()
    existing = {r["id"]: r for r in conn.execute(
        "SELECT id, " + ", ".join(_MATCH_COLS) +
        " FROM matches WHERE league_key=?", (league_key,)).fetchall()}

    writes = []
    for mid, v in incoming.items():
        old = existing.get(mid)
        if old is not None:
            if (guard_status and v["status"] == "SCHEDULED"
                    and old["status"] in ("FINISHED", "LIVE")):
                v = {**v, "status": old["status"]}
            # get: מקורות שלא מביאים כל שדה (למשל בלי תוצאה) עדיין נכתבים
            if all(old[c] == v.get(c) for c in _MATCH_COLS):
                continue
        writes.append((mid, league_key, *(v.get(c) for c in _MATCH_COLS), now))

    deletes = []
    if purge and incoming:
        for mid, old in existing.items():
            if mid in incoming:
                continue
            if hard:
                deletes.append((mid,))
                continue
            if old["status"] in _OVER_STATUSES or str(mid).startswith("manual-"):
                continue
            # משחק ששריקת הפתיחה שלו כבר נשמעה לא נמחק. דווקא אז המקור
            # לפעמים לא מחזיר אותו, והוא נעלם מתחת לידיים של מי שצופה בו:
            # פתיחת מכבי חיפה–עירוני טבריה (19.9.26) גררה רענון, הרענון
            # מחק את המשחק, והחלון נפתח מחדש על משחק שכבר לא קיים.
            if kickoff_passed(old, hours=0):
                continue
            deletes.append((mid,))

    if deletes:
        conn.executemany("DELETE FROM matches WHERE id=?", deletes)
    if writes:
        conn.executemany("""
            INSERT OR REPLACE INTO matches
            (id, league_key, home_team, away_team, home_team_id, away_team_id,
             date_utc, time_utc, venue, matchday, status, home_score, away_score, fetched_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, writes)
    if incoming and mark_fresh:
        conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
                     (f"fetched:{league_key}", now))
    print(f"[sync] {league_key}: incoming={len(incoming)} "
          f"written={len(writes)} deleted={len(deletes)}")
    return {"written": len(writes), "deleted": len(deletes)}


def _league_fetched_at(conn, league_key: str):
    """מתי הליגה רועננה לאחרונה (ISO), או None. רק מ-meta: שורות שנכתבו
    בשליפה חלקית (sportsdb מצד השרת) לא נחשבות רענון."""
    row = conn.execute("SELECT value FROM meta WHERE key=?",
                       (f"fetched:{league_key}",)).fetchone()
    return row["value"] if row else None


def _sportsdb_rows(events: list) -> dict:
    """אירועי TheSportsDB → {id: שורה}. אותו משחק מגיע מכמה endpoints —
    eventsround לפעמים מחזיר סטטוס ריק למשחק שנגמר, אז לא מורידים סטטוס."""
    rows = {}
    for e in events:
        event_id = e.get("idEvent")
        if not event_id:
            continue
        matchday = None
        try:
            matchday = int(e.get("intRound") or 0) or None
        except (ValueError, TypeError):
            pass
        status = map_sportsdb_status(e)
        prev = rows.get(str(event_id))
        if prev and status == "SCHEDULED" and prev["status"] in ("FINISHED", "LIVE"):
            status = prev["status"]
        def _score(key):
            try:
                return int(e.get(key))
            except (TypeError, ValueError):
                return None

        rows[str(event_id)] = {
            "home_team": e.get("strHomeTeam"), "away_team": e.get("strAwayTeam"),
            "home_team_id": None, "away_team_id": None,
            "home_score": _score("intHomeScore"), "away_score": _score("intAwayScore"),
            "date_utc": e.get("dateEvent"),
            "time_utc": e.get("strTime") or "00:00:00",
            "venue": e.get("strVenue") or "", "matchday": matchday,
            "status": status,
        }
    return rows


def _store_sportsdb_events(conn, league_key: str, events: list,
                           purge: bool = False, hard: bool = False,
                           mark_fresh: bool = True) -> int:
    """Store a list of TheSportsDB events into our matches table."""
    # min_date: מסנן משחקים מלפני תחילת השלב (מוקדמות הצ'מפיונס מיולי
    # מגיעות מ-sportsdb עם intRound=1 ונכנסו למחזור 1 של שלב הליגה)
    min_date = LEAGUES.get(league_key, {}).get("min_date")
    if min_date:
        events = [e for e in events if (e.get("dateEvent") or "") >= min_date]
    rows = _sportsdb_rows(events)
    _sync_league_rows(conn, league_key, rows, purge=purge, hard=hard,
                      guard_status=True, mark_fresh=mark_fresh)
    return len(rows)


def fetch_football_data(league_key: str, purge: bool = False):
    league = LEAGUES[league_key]
    r = requests.get(
        f"https://api.football-data.org/v4/competitions/{league['fd_code']}/matches",
        headers={"X-Auth-Token": FOOTBALL_DATA_KEY},
        params={"season": league["fd_season"]},
        timeout=15
    )
    matches = r.json().get("matches", [])
    rows = {}
    for m in matches:
        utc_dt = datetime.fromisoformat(m["utcDate"].replace("Z", "+00:00"))
        full = (m.get("score") or {}).get("fullTime") or {}
        rows[str(m["id"])] = {
            "home_team": m["homeTeam"]["name"], "away_team": m["awayTeam"]["name"],
            "home_team_id": str(m["homeTeam"]["id"]),
            "away_team_id": str(m["awayTeam"]["id"]),
            "home_score": full.get("home"), "away_score": full.get("away"),
            "date_utc": utc_dt.strftime("%Y-%m-%d"),
            "time_utc": utc_dt.strftime("%H:%M:%S"),
            "venue": "", "matchday": m.get("matchday"),
            "status": m.get("status", "SCHEDULED"),
        }

    # purge רק אחרי ששליפה הצליחה — _sync_league_rows לא מוחק כשהגיע ריק
    conn = get_db()
    _sync_league_rows(conn, league_key, rows, purge=purge)
    conn.commit()
    conn.close()


def fetch_sportsdb(league_key: str, purge: bool = False):
    """Server-side fetch from TheSportsDB.
    שים לב: חסום מ-Render (IP ענן). עובד רק בהרצה מקומית.
    בפרודקשן הרענון נעשה client-side דרך POST /refresh/{league_key}."""
    league = LEAGUES[league_key]
    all_events = []

    for sdb_id in league.get("sportsdb_ids", []):
        endpoints = [
            ("eventsseason.php",     {"id": sdb_id, "s": league["sportsdb_season"]}),
            ("eventspastleague.php", {"id": sdb_id}),
            ("eventsnextleague.php", {"id": sdb_id}),
        ]
        for ep, params in endpoints:
            try:
                r = requests.get(
                    f"https://www.thesportsdb.com/api/v1/json/123/{ep}",
                    params=params, timeout=15
                )
                events = r.json().get("events") or []
                print(f"[sportsdb] {ep} ({sdb_id}): {len(events)} events")
                all_events.extend(events)
            except Exception as ex:
                print(f"[sportsdb] {ep} ({sdb_id}) failed: {ex}")

    # mark_fresh=False: בחינם sportsdb מחזיר מצד השרת רק ~7 משחקים. אם זה
    # היה מסמן את הליגה "טרייה", הרענון מהדפדפן (חלון מחזורים מלא) לא היה
    # רץ — כך נפתח טאב הצ'מפיונשיפ עם מחזור 1 חלקי בלבד (13.9.26).
    conn = get_db()
    _store_sportsdb_events(conn, league_key, all_events, purge=purge,
                           mark_fresh=False)
    conn.commit()
    conn.close()


def fetch_and_store(league_key: str, purge: bool = False):
    league = LEAGUES.get(league_key)
    if not league:
        return
    if league["source"] == "football-data":
        fetch_football_data(league_key, purge)
    else:
        fetch_sportsdb(league_key, purge)
    # לוח רשמי ידני גובר על נתוני המקור (ראו MANUAL_FIXTURES)
    if league_key in MANUAL_FIXTURES:
        apply_manual_fixtures(league_key)


# ── לוח רשמי — ליגת העל, מחזורים 4–15 ──────────────────
# מקור: מסמך דוברות מנהלת הליגות "ליגת Winner מחזורים 4-15" (1.9.26).
# רקע: sportsdb מחזיק placeholder למחזור 4 (כל המשחקים "שני 20:00" —
# בפועל 6/7 שגויים) ומחזורים 5–15 חסרים אצלו לגמרי (נבדק 5.9.26).
# שדות: (מחזור, תאריך, שעה בשעון ישראל, בית, חוץ, אצטדיון, שידור)
# שידור: תיעוד לעתיד (תיעדוף מקור פר-משחק, שלב 34.5+); לא נשמר ב-DB.
# גמר גביע הטוטו (28.10, מכבי ת"א–הפועל ת"א) אינו משחק ליגה — לא נכלל.
# שעון: המרה ל-UTC דרך ISRAEL_TZ — מעבר לשעון חורף 25.10.26 מטופל אוטומטית.
MANUAL_FIXTURES = {
    "israel": [
        # מחזור 4
        (4,  "2026-09-13", "20:30", "Hapoel Petah Tikva", "Hapoel Be'er Sheva", "שלמה ביטוח", "ספורט 4"),
        (4,  "2026-09-14", "19:30", "Hapoel Haifa", "Bnei Sakhnin", "סמי עופר", "5LIVE"),
        (4,  "2026-09-14", "19:30", "Hapoel Ramat Gan", "Maccabi Netanya", "רחובות", "ספורט 3"),
        (4,  "2026-09-14", "20:00", "Hapoel Ironi Kiryat Shmona", "Maccabi Haifa", "מרים", "ספורט 4"),
        (4,  "2026-09-14", "20:30", "Maccabi Tel Aviv", "Hapoel Tel-Aviv", "בלומפילד", "5SPORT"),
        (4,  "2026-09-15", "19:30", "Ironi Tiberias", "Hapoel Jerusalem", "בראל", "5LIVE"),
        (4,  "2026-09-15", "20:00", "Beitar Jerusalem", "Maccabi Petah Tikva", "בלומפילד", "ספורט 2"),
        # מחזור 5
        (5,  "2026-09-18", "15:45", "Hapoel Tel-Aviv", "Hapoel Petah Tikva", "בלומפילד", "ספורט 1"),
        (5,  "2026-09-19", "19:30", "Bnei Sakhnin", "Hapoel Ramat Gan", "דוחא", "5LIVE"),
        (5,  "2026-09-19", "19:30", "Maccabi Petah Tikva", "Hapoel Jerusalem", "שלמה ביטוח", "5STARS"),
        (5,  "2026-09-19", "20:00", "Maccabi Haifa", "Ironi Tiberias", "סמי עופר", "ספורט 2"),
        (5,  "2026-09-19", "20:00", "Maccabi Netanya", "Maccabi Tel Aviv", "מרים", "ספורט 4"),
        (5,  "2026-09-19", "20:15", "Hapoel Be'er Sheva", "Hapoel Ironi Kiryat Shmona", "טוטו טרנר", "ספורט 3"),
        (5,  "2026-09-19", "20:30", "Beitar Jerusalem", "Hapoel Haifa", "בלומפילד", "5SPORT"),
        # מחזור 6
        (6,  "2026-10-10", "19:00", "Hapoel Haifa", "Maccabi Petah Tikva", "סמי עופר", "5LIVE"),
        (6,  "2026-10-10", "19:00", "Ironi Tiberias", "Hapoel Be'er Sheva", "בראל", "ספורט 1"),
        (6,  "2026-10-10", "19:15", "Hapoel Ironi Kiryat Shmona", "Hapoel Tel-Aviv", "מרים", "ספורט 3"),
        (6,  "2026-10-10", "19:15", "Hapoel Petah Tikva", "Maccabi Netanya", "שלמה ביטוח", "5STARS"),
        (6,  "2026-10-10", "19:30", "Maccabi Tel Aviv", "Bnei Sakhnin", "בלומפילד", "ספורט 4"),
        (6,  "2026-10-11", "20:15", "Hapoel Ramat Gan", "Beitar Jerusalem", "רחובות", "ספורט 4"),
        (6,  "2026-10-12", "20:30", "Hapoel Jerusalem", "Maccabi Haifa", "טדי", "5SPORT"),
        # מחזור 7
        (7,  "2026-10-17", "18:45", "Hapoel Tel-Aviv", "Ironi Tiberias", "בלומפילד", "ספורט 3"),
        (7,  "2026-10-17", "19:00", "Hapoel Haifa", "Hapoel Ramat Gan", "סמי עופר", "5LIVE"),
        (7,  "2026-10-17", "19:15", "Bnei Sakhnin", "Hapoel Petah Tikva", "דוחא", "5STARS"),
        (7,  "2026-10-17", "19:15", "Maccabi Netanya", "Hapoel Ironi Kiryat Shmona", "מרים", "ספורט 2"),
        (7,  "2026-10-17", "19:30", "Maccabi Petah Tikva", "Maccabi Haifa", "שלמה ביטוח", "ספורט 4"),
        (7,  "2026-10-18", "20:15", "Hapoel Be'er Sheva", "Hapoel Jerusalem", "טוטו טרנר", "ספורט 4"),
        (7,  "2026-10-19", "20:30", "Beitar Jerusalem", "Maccabi Tel Aviv", "טדי", "5SPORT"),
        # מחזור 8 (25.10 = מעבר לשעון חורף)
        (8,  "2026-10-24", "18:45", "Hapoel Jerusalem", "Hapoel Tel-Aviv", "טדי", "ספורט 3"),
        (8,  "2026-10-24", "18:45", "Hapoel Ironi Kiryat Shmona", "Bnei Sakhnin", "מרים", "5LIVE"),
        (8,  "2026-10-24", "19:00", "Hapoel Ramat Gan", "Maccabi Petah Tikva", "רחובות", None),
        (8,  "2026-10-24", "19:00", "Ironi Tiberias", "Maccabi Netanya", "בראל", None),
        (8,  "2026-10-24", "19:30", "Maccabi Tel Aviv", "Hapoel Haifa", "בלומפילד", "ספורט 4"),
        (8,  "2026-10-25", "20:15", "Hapoel Petah Tikva", "Beitar Jerusalem", "שלמה ביטוח", "ספורט 4"),
        (8,  "2026-10-26", "20:30", "Maccabi Haifa", "Hapoel Be'er Sheva", "סמי עופר", "5SPORT"),
        # מחזור 9
        (9,  "2026-10-31", "15:00", "Beitar Jerusalem", "Hapoel Ironi Kiryat Shmona", "טדי", "ספורט 4"),
        (9,  "2026-10-31", "17:30", "Hapoel Haifa", "Hapoel Petah Tikva", "סמי עופר", "5STARS"),
        (9,  "2026-10-31", "18:00", "Bnei Sakhnin", "Ironi Tiberias", "דוחא", "5LIVE"),
        (9,  "2026-10-31", "19:30", "Maccabi Netanya", "Hapoel Jerusalem", "מרים", "ספורט 4"),
        (9,  "2026-11-01", "20:00", "Maccabi Petah Tikva", "Hapoel Be'er Sheva", "שלמה ביטוח", "ספורט 3"),
        (9,  "2026-11-01", "20:15", "Hapoel Ramat Gan", "Maccabi Tel Aviv", "רחובות", "ספורט 4"),
        (9,  "2026-11-02", "20:30", "Hapoel Tel-Aviv", "Maccabi Haifa", "בלומפילד", "5SPORT"),
        # מחזור 10 (הערת המסמך: יתכנו שינויים לפי זימוני נבחרות)
        (10, "2026-11-06", "14:00", "Maccabi Tel Aviv", "Maccabi Petah Tikva", "בלומפילד", "ספורט 4"),
        (10, "2026-11-07", "15:00", "Hapoel Petah Tikva", "Hapoel Ramat Gan", "שלמה ביטוח", "ספורט 4"),
        (10, "2026-11-07", "17:30", "Maccabi Haifa", "Maccabi Netanya", "סמי עופר", "ספורט 4"),
        (10, "2026-11-07", "18:00", "Hapoel Ironi Kiryat Shmona", "Hapoel Haifa", "מרים", "5LIVE"),
        (10, "2026-11-07", "18:00", "Hapoel Jerusalem", "Bnei Sakhnin", "טדי", "5STARS"),
        (10, "2026-11-07", "19:30", "Ironi Tiberias", "Beitar Jerusalem", "בראל", "ספורט 3"),
        (10, "2026-11-08", "20:30", "Hapoel Be'er Sheva", "Hapoel Tel-Aviv", "טוטו טרנר", "5SPORT"),
        # מחזור 11
        (11, "2026-11-27", "14:00", "Maccabi Petah Tikva", "Hapoel Tel-Aviv", "שלמה ביטוח", "ספורט 1"),
        (11, "2026-11-28", "15:00", "Bnei Sakhnin", "Maccabi Haifa", "דוחא", "ספורט 4"),
        (11, "2026-11-28", "17:30", "Hapoel Ramat Gan", "Hapoel Ironi Kiryat Shmona", "רחובות", "5LIVE"),
        (11, "2026-11-28", "18:00", "Hapoel Haifa", "Ironi Tiberias", "סמי עופר", "5STARS"),
        (11, "2026-11-28", "19:00", "Maccabi Tel Aviv", "Hapoel Petah Tikva", "בלומפילד", "ספורט 4"),
        (11, "2026-11-28", "20:00", "Beitar Jerusalem", "Hapoel Jerusalem", "טדי", "5SPORT"),
        (11, "2026-11-30", "20:00", "Maccabi Netanya", "Hapoel Be'er Sheva", "מרים", "ספורט 1"),
        # מחזור 12
        (12, "2026-12-01", "19:30", "Ironi Tiberias", "Hapoel Ramat Gan", "בראל", "5LIVE"),
        (12, "2026-12-01", "19:45", "Hapoel Jerusalem", "Hapoel Haifa", "טדי", "5STARS"),
        (12, "2026-12-01", "19:45", "Maccabi Petah Tikva", "Hapoel Petah Tikva", "שלמה ביטוח", "ספורט 1"),
        (12, "2026-12-01", "20:00", "Hapoel Ironi Kiryat Shmona", "Maccabi Tel Aviv", "מרים", "ספורט 4"),
        (12, "2026-12-02", "20:30", "Maccabi Haifa", "Beitar Jerusalem", "סמי עופר", "5SPORT"),
        (12, "2026-12-03", "19:45", "Hapoel Be'er Sheva", "Bnei Sakhnin", "טוטו טרנר", "ספורט 1"),
        (12, "2026-12-03", "20:00", "Hapoel Tel-Aviv", "Maccabi Netanya", "בלומפילד", "ספורט 2"),
        # מחזור 13
        (13, "2026-12-05", "15:00", "Maccabi Tel Aviv", "Ironi Tiberias", "בלומפילד", "ספורט 3"),
        (13, "2026-12-05", "17:30", "Hapoel Petah Tikva", "Hapoel Ironi Kiryat Shmona", "שלמה ביטוח", None),
        (13, "2026-12-05", "18:00", "Hapoel Ramat Gan", "Hapoel Jerusalem", "רחובות", None),
        (13, "2026-12-05", "19:30", "Hapoel Haifa", "Maccabi Haifa", "סמי עופר", "ספורט 4"),
        (13, "2026-12-06", "20:30", "Beitar Jerusalem", "Hapoel Be'er Sheva", "טדי", "5SPORT"),
        (13, "2026-12-07", "19:45", "Maccabi Netanya", "Maccabi Petah Tikva", "מרים", None),
        (13, "2026-12-07", "20:00", "Bnei Sakhnin", "Hapoel Tel-Aviv", "דוחא", "ספורט 4"),
        # מחזור 14
        (14, "2026-12-11", "14:00", "Hapoel Petah Tikva", "Ironi Tiberias", "שלמה ביטוח", None),
        (14, "2026-12-12", "15:00", "Bnei Sakhnin", "Maccabi Netanya", "דוחא", None),
        (14, "2026-12-12", "17:30", "Hapoel Ramat Gan", "Maccabi Haifa", "רחובות", "ספורט 1"),
        (14, "2026-12-12", "18:00", "Hapoel Ironi Kiryat Shmona", "Maccabi Petah Tikva", "מרים", "5STARS"),
        (14, "2026-12-12", "19:00", "Maccabi Tel Aviv", "Hapoel Jerusalem", "בלומפילד", "ספורט 4"),
        (14, "2026-12-14", "20:00", "Hapoel Haifa", "Hapoel Be'er Sheva", "סמי עופר", "ספורט 4"),
        (14, "2026-12-14", "20:30", "Beitar Jerusalem", "Hapoel Tel-Aviv", "טדי", "5SPORT"),
        # מחזור 15
        (15, "2026-12-18", "14:00", "Hapoel Jerusalem", "Hapoel Petah Tikva", "טדי", "ספורט 1"),
        (15, "2026-12-19", "15:00", "Hapoel Tel-Aviv", "Hapoel Haifa", "בלומפילד", "ספורט 4"),
        (15, "2026-12-19", "18:00", "Ironi Tiberias", "Hapoel Ironi Kiryat Shmona", "בראל", "5LIVE"),
        (15, "2026-12-19", "18:00", "Maccabi Petah Tikva", "Bnei Sakhnin", "שלמה ביטוח", "5STARS"),
        (15, "2026-12-19", "19:30", "Maccabi Netanya", "Beitar Jerusalem", "מרים", "ספורט 4"),
        (15, "2026-12-20", "20:15", "Hapoel Be'er Sheva", "Hapoel Ramat Gan", "טוטו טרנר", "ספורט 4"),
        (15, "2026-12-21", "20:30", "Maccabi Haifa", "Maccabi Tel Aviv", "סמי עופר", "5SPORT"),
    ],
    # צ'מפיונס ליג 2026-27, שלב הליגה — 8 מחזורים × 18 משחקים.
    # מקור: UEFA "League phase draw results — calendar by matchday" (PDF רשמי).
    # שעות ה-PDF (CET/CEST) הומרו לשעון ישראל; שמות = השמות ב-TheSportsDB
    # (אומת: מחזורים 1–2 זהים 36/36 כולל שעות, 13.9.26). אצטדיון ריק = לא נוגעים.
    "ucl": [
        # מחזור 1
        (1, "2026-09-08", "19:45", "AEK Athens", "LASK", "", ""),
        (1, "2026-09-08", "19:45", "Club Brugge", "Aston Villa", "", ""),
        (1, "2026-09-08", "22:00", "Borussia Dortmund", "Villarreal", "", ""),
        (1, "2026-09-08", "22:00", "Lille", "Real Betis", "", ""),
        (1, "2026-09-08", "22:00", "Porto", "Manchester City", "", ""),
        (1, "2026-09-08", "22:00", "Real Madrid", "Inter Milan", "", ""),
        (1, "2026-09-09", "19:45", "Barcelona", "Feyenoord", "", ""),
        (1, "2026-09-09", "19:45", "Stuttgart", "Viking", "", ""),
        (1, "2026-09-09", "22:00", "Liverpool", "Atlético Madrid", "", ""),
        (1, "2026-09-09", "22:00", "Napoli", "Arsenal", "", ""),
        (1, "2026-09-09", "22:00", "Paris Saint-Germain", "Slovan Bratislava", "", ""),
        (1, "2026-09-09", "22:00", "Sporting CP", "Galatasaray", "", ""),
        (1, "2026-09-10", "19:45", "Fenerbahçe", "Roma", "", ""),
        (1, "2026-09-10", "19:45", "PSV Eindhoven", "Shakhtar Donetsk", "", ""),
        (1, "2026-09-10", "22:00", "Bayern Munich", "Bodø/Glimt", "", ""),
        (1, "2026-09-10", "22:00", "Como", "RB Leipzig", "", ""),
        (1, "2026-09-10", "22:00", "Manchester United", "Sabah Baku", "", ""),
        (1, "2026-09-10", "22:00", "Slavia Prague", "Lens", "", ""),
        # מחזור 2
        (2, "2026-10-13", "19:45", "Lens", "Sporting CP", "", ""),
        (2, "2026-10-13", "19:45", "Sabah Baku", "Slavia Prague", "", ""),
        (2, "2026-10-13", "22:00", "Arsenal", "Lille", "", ""),
        (2, "2026-10-13", "22:00", "Atlético Madrid", "Manchester United", "", ""),
        (2, "2026-10-13", "22:00", "Galatasaray", "Barcelona", "", ""),
        (2, "2026-10-13", "22:00", "Inter Milan", "Club Brugge", "", ""),
        (2, "2026-10-13", "22:00", "RB Leipzig", "PSV Eindhoven", "", ""),
        (2, "2026-10-13", "22:00", "Viking", "Bayern Munich", "", ""),
        (2, "2026-10-13", "22:00", "Villarreal", "Napoli", "", ""),
        (2, "2026-10-14", "19:45", "Feyenoord", "Como", "", ""),
        (2, "2026-10-14", "19:45", "LASK", "Liverpool", "", ""),
        (2, "2026-10-14", "22:00", "Aston Villa", "Fenerbahçe", "", ""),
        (2, "2026-10-14", "22:00", "Bodø/Glimt", "Borussia Dortmund", "", ""),
        (2, "2026-10-14", "22:00", "Manchester City", "Paris Saint-Germain", "", ""),
        (2, "2026-10-14", "22:00", "Real Betis", "Porto", "", ""),
        (2, "2026-10-14", "22:00", "Roma", "Real Madrid", "", ""),
        (2, "2026-10-14", "22:00", "Shakhtar Donetsk", "AEK Athens", "", ""),
        (2, "2026-10-14", "22:00", "Slovan Bratislava", "Stuttgart", "", ""),
        # מחזור 3
        (3, "2026-10-20", "19:45", "Fenerbahçe", "Slavia Prague", "", ""),
        (3, "2026-10-20", "19:45", "Sabah Baku", "Borussia Dortmund", "", ""),
        (3, "2026-10-20", "22:00", "Liverpool", "Villarreal", "", ""),
        (3, "2026-10-20", "22:00", "Manchester City", "AEK Athens", "", ""),
        (3, "2026-10-20", "22:00", "Napoli", "Bodø/Glimt", "", ""),
        (3, "2026-10-20", "22:00", "Paris Saint-Germain", "Barcelona", "", ""),
        (3, "2026-10-20", "22:00", "Porto", "PSV Eindhoven", "", ""),
        (3, "2026-10-20", "22:00", "Roma", "Slovan Bratislava", "", ""),
        (3, "2026-10-20", "22:00", "Stuttgart", "Atlético Madrid", "", ""),
        (3, "2026-10-21", "19:45", "Como", "Manchester United", "", ""),
        (3, "2026-10-21", "19:45", "Lille", "Galatasaray", "", ""),
        (3, "2026-10-21", "22:00", "Aston Villa", "Viking", "", ""),
        (3, "2026-10-21", "22:00", "Bayern Munich", "Arsenal", "", ""),
        (3, "2026-10-21", "22:00", "Club Brugge", "Lens", "", ""),
        (3, "2026-10-21", "22:00", "Inter Milan", "Shakhtar Donetsk", "", ""),
        (3, "2026-10-21", "22:00", "Real Betis", "Feyenoord", "", ""),
        (3, "2026-10-21", "22:00", "Real Madrid", "RB Leipzig", "", ""),
        (3, "2026-10-21", "22:00", "Sporting CP", "LASK", "", ""),
        # מחזור 4
        (4, "2026-11-03", "19:45", "Galatasaray", "Stuttgart", "", ""),
        (4, "2026-11-03", "19:45", "Shakhtar Donetsk", "Sporting CP", "", ""),
        (4, "2026-11-03", "22:00", "Atlético Madrid", "Bayern Munich", "", ""),
        (4, "2026-11-03", "22:00", "Barcelona", "Aston Villa", "", ""),
        (4, "2026-11-03", "22:00", "Bodø/Glimt", "Lille", "", ""),
        (4, "2026-11-03", "22:00", "Feyenoord", "Inter Milan", "", ""),
        (4, "2026-11-03", "22:00", "LASK", "Slovan Bratislava", "", ""),
        (4, "2026-11-03", "22:00", "Manchester United", "Roma", "", ""),
        (4, "2026-11-03", "22:00", "Villarreal", "Paris Saint-Germain", "", ""),
        (4, "2026-11-04", "19:45", "AEK Athens", "Real Madrid", "", ""),
        (4, "2026-11-04", "19:45", "Fenerbahçe", "Liverpool", "", ""),
        (4, "2026-11-04", "22:00", "Borussia Dortmund", "Real Betis", "", ""),
        (4, "2026-11-04", "22:00", "Lens", "Como", "", ""),
        (4, "2026-11-04", "22:00", "PSV Eindhoven", "Club Brugge", "", ""),
        (4, "2026-11-04", "22:00", "Porto", "Napoli", "", ""),
        (4, "2026-11-04", "22:00", "RB Leipzig", "Manchester City", "", ""),
        (4, "2026-11-04", "22:00", "Slavia Prague", "Arsenal", "", ""),
        (4, "2026-11-04", "22:00", "Viking", "Sabah Baku", "", ""),
        # מחזור 5
        (5, "2026-11-24", "19:45", "Bodø/Glimt", "LASK", "", ""),
        (5, "2026-11-24", "19:45", "Galatasaray", "Aston Villa", "", ""),
        (5, "2026-11-24", "22:00", "Arsenal", "Borussia Dortmund", "", ""),
        (5, "2026-11-24", "22:00", "Como", "AEK Athens", "", ""),
        (5, "2026-11-24", "22:00", "Feyenoord", "Porto", "", ""),
        (5, "2026-11-24", "22:00", "Manchester City", "Napoli", "", ""),
        (5, "2026-11-24", "22:00", "RB Leipzig", "Lens", "", ""),
        (5, "2026-11-24", "22:00", "Real Madrid", "PSV Eindhoven", "", ""),
        (5, "2026-11-24", "22:00", "Slovan Bratislava", "Real Betis", "", ""),
        (5, "2026-11-25", "19:45", "Sabah Baku", "Barcelona", "", ""),
        (5, "2026-11-25", "19:45", "Slavia Prague", "Villarreal", "", ""),
        (5, "2026-11-25", "22:00", "Atlético Madrid", "Viking", "", ""),
        (5, "2026-11-25", "22:00", "Club Brugge", "Liverpool", "", ""),
        (5, "2026-11-25", "22:00", "Inter Milan", "Stuttgart", "", ""),
        (5, "2026-11-25", "22:00", "Lille", "Bayern Munich", "", ""),
        (5, "2026-11-25", "22:00", "Paris Saint-Germain", "Roma", "", ""),
        (5, "2026-11-25", "22:00", "Shakhtar Donetsk", "Fenerbahçe", "", ""),
        (5, "2026-11-25", "22:00", "Sporting CP", "Manchester United", "", ""),
        # מחזור 6
        (6, "2026-12-08", "19:45", "Viking", "Feyenoord", "", ""),
        (6, "2026-12-08", "19:45", "Villarreal", "Sabah Baku", "", ""),
        (6, "2026-12-08", "22:00", "AEK Athens", "Galatasaray", "", ""),
        (6, "2026-12-08", "22:00", "Aston Villa", "Paris Saint-Germain", "", ""),
        (6, "2026-12-08", "22:00", "Barcelona", "Manchester City", "", ""),
        (6, "2026-12-08", "22:00", "Bayern Munich", "Slavia Prague", "", ""),
        (6, "2026-12-08", "22:00", "Manchester United", "RB Leipzig", "", ""),
        (6, "2026-12-08", "22:00", "Napoli", "Club Brugge", "", ""),
        (6, "2026-12-08", "22:00", "Roma", "Sporting CP", "", ""),
        (6, "2026-12-09", "19:45", "Real Betis", "Como", "", ""),
        (6, "2026-12-09", "19:45", "Slovan Bratislava", "Shakhtar Donetsk", "", ""),
        (6, "2026-12-09", "22:00", "Arsenal", "Real Madrid", "", ""),
        (6, "2026-12-09", "22:00", "Borussia Dortmund", "Inter Milan", "", ""),
        (6, "2026-12-09", "22:00", "LASK", "Fenerbahçe", "", ""),
        (6, "2026-12-09", "22:00", "Lens", "Bodø/Glimt", "", ""),
        (6, "2026-12-09", "22:00", "Liverpool", "Porto", "", ""),
        (6, "2026-12-09", "22:00", "PSV Eindhoven", "Atlético Madrid", "", ""),
        (6, "2026-12-09", "22:00", "Stuttgart", "Lille", "", ""),
        # מחזור 7
        (7, "2027-01-19", "19:45", "Bodø/Glimt", "Atlético Madrid", "", ""),
        (7, "2027-01-19", "19:45", "Galatasaray", "Feyenoord", "", ""),
        (7, "2027-01-19", "22:00", "AEK Athens", "Roma", "", ""),
        (7, "2027-01-19", "22:00", "Aston Villa", "Borussia Dortmund", "", ""),
        (7, "2027-01-19", "22:00", "Inter Milan", "Liverpool", "", ""),
        (7, "2027-01-19", "22:00", "Lille", "Slovan Bratislava", "", ""),
        (7, "2027-01-19", "22:00", "Porto", "Slavia Prague", "", ""),
        (7, "2027-01-19", "22:00", "Real Madrid", "LASK", "", ""),
        (7, "2027-01-19", "22:00", "Stuttgart", "Club Brugge", "", ""),
        (7, "2027-01-20", "19:45", "Fenerbahçe", "Villarreal", "", ""),
        (7, "2027-01-20", "19:45", "Sabah Baku", "Napoli", "", ""),
        (7, "2027-01-20", "22:00", "Como", "Paris Saint-Germain", "", ""),
        (7, "2027-01-20", "22:00", "Lens", "Manchester City", "", ""),
        (7, "2027-01-20", "22:00", "Manchester United", "Bayern Munich", "", ""),
        (7, "2027-01-20", "22:00", "RB Leipzig", "Shakhtar Donetsk", "", ""),
        (7, "2027-01-20", "22:00", "Real Betis", "Arsenal", "", ""),
        (7, "2027-01-20", "22:00", "Sporting CP", "Barcelona", "", ""),
        (7, "2027-01-20", "22:00", "Viking", "PSV Eindhoven", "", ""),
        # מחזור 8
        (8, "2027-01-27", "22:00", "Arsenal", "Sabah Baku", "", ""),
        (8, "2027-01-27", "22:00", "Atlético Madrid", "Fenerbahçe", "", ""),
        (8, "2027-01-27", "22:00", "Barcelona", "Como", "", ""),
        (8, "2027-01-27", "22:00", "Bayern Munich", "Real Betis", "", ""),
        (8, "2027-01-27", "22:00", "Borussia Dortmund", "AEK Athens", "", ""),
        (8, "2027-01-27", "22:00", "Club Brugge", "Bodø/Glimt", "", ""),
        (8, "2027-01-27", "22:00", "Feyenoord", "RB Leipzig", "", ""),
        (8, "2027-01-27", "22:00", "LASK", "Porto", "", ""),
        (8, "2027-01-27", "22:00", "Liverpool", "Lens", "", ""),
        (8, "2027-01-27", "22:00", "Manchester City", "Sporting CP", "", ""),
        (8, "2027-01-27", "22:00", "Napoli", "Viking", "", ""),
        (8, "2027-01-27", "22:00", "PSV Eindhoven", "Stuttgart", "", ""),
        (8, "2027-01-27", "22:00", "Paris Saint-Germain", "Galatasaray", "", ""),
        (8, "2027-01-27", "22:00", "Roma", "Lille", "", ""),
        (8, "2027-01-27", "22:00", "Shakhtar Donetsk", "Real Madrid", "", ""),
        (8, "2027-01-27", "22:00", "Slavia Prague", "Aston Villa", "", ""),
        (8, "2027-01-27", "22:00", "Slovan Bratislava", "Inter Milan", "", ""),
        (8, "2027-01-27", "22:00", "Villarreal", "Manchester United", "", ""),
    ],
}


def _fixture_slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def _il_to_utc(date_str: str, time_str: str):
    """שעון ישראל → UTC. קיץ/חורף אוטומטית דרך ISRAEL_TZ."""
    dt_il = datetime.fromisoformat(f"{date_str}T{time_str}:00").replace(tzinfo=ISRAEL_TZ)
    dt_u = dt_il.astimezone(timezone.utc)
    return dt_u.strftime("%Y-%m-%d"), dt_u.strftime("%H:%M:%S")


def apply_manual_fixtures(league_key: str):
    """מיישם את הלוח הרשמי מעל נתוני sportsdb — מבוסס diff:
    SELECT אחד לכל הליגה, ואז נכתב רק מה שבאמת השתנה. במצב יציב זה
    אפס כתיבות, כך שרענון לא פותח חלון של מצב-ביניים מול קוראים.
    - משחק שקיים ב-sportsdb: עדכון תאריך/שעה/אצטדיון (סטטוס/תוצאה לא נוגעים).
    - משחק חסר: הוספת שורת manual-*.
    - אם sportsdb השלים משחק שהיה אצלנו כ-manual: הכפילות נמחקת."""
    fixtures = MANUAL_FIXTURES.get(league_key, [])
    if not fixtures:
        return
    conn = get_db()
    now = datetime.now(timezone.utc).isoformat()
    by_key = {}
    for r in conn.execute(
            """SELECT id, matchday, home_team, away_team, date_utc, time_utc,
                      venue FROM matches WHERE league_key=?""",
            (league_key,)).fetchall():
        k = (r["matchday"], str(r["home_team"]).strip().lower(),
             str(r["away_team"]).strip().lower())
        by_key.setdefault(k, []).append(r)

    updates, inserts, deletes = [], [], []
    for rnd, d_il, t_il, home, away, venue, _tv in fixtures:
        date_utc, time_utc = _il_to_utc(d_il, t_il)
        rows_k = by_key.get((rnd, home.lower(), away.lower()), [])
        real   = [r for r in rows_k if not str(r["id"]).startswith("manual-")]
        manual = [r for r in rows_k if str(r["id"]).startswith("manual-")]
        # אצטדיון ריק בלוח (צ'מפיונס) = לא נוגעים באצטדיון הקיים
        if real:
            r = real[0]
            v = venue or r["venue"]
            if (r["date_utc"], r["time_utc"], r["venue"]) != (date_utc, time_utc, v):
                updates.append((date_utc, time_utc, v, r["id"]))
            deletes.extend((m["id"],) for m in manual)
        elif manual:
            m = manual[0]
            v = venue or m["venue"]
            if (m["date_utc"], m["time_utc"], m["venue"]) != (date_utc, time_utc, v):
                updates.append((date_utc, time_utc, v, m["id"]))
        else:
            inserts.append((f"manual-{league_key}-r{rnd}-{_fixture_slug(home)}",
                            league_key, home, away, "", "", date_utc, time_utc,
                            venue, rnd, "SCHEDULED", now))

    for u in updates:
        conn.execute("UPDATE matches SET date_utc=?, time_utc=?, venue=? WHERE id=?", u)
    for d in deletes:
        conn.execute("DELETE FROM matches WHERE id=?", d)
    for i in inserts:
        conn.execute(
            """INSERT OR REPLACE INTO matches
               (id, league_key, home_team, away_team, home_team_id,
                away_team_id, date_utc, time_utc, venue, matchday,
                status, fetched_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""", i)
    if updates or deletes or inserts:
        conn.commit()
    conn.close()
    print(f"[manual] {league_key}: updated={len(updates)} "
          f"added={len(inserts)} deduped={len(deletes)}")


# ── Utils ──────────────────────────────────────────────

def to_israel_time(date_str: str, time_str: str) -> dict:
    try:
        dt_utc = datetime.fromisoformat(f"{date_str}T{time_str}+00:00")
        dt_il  = dt_utc.astimezone(ISRAEL_TZ)
        return {
            "date":    dt_il.strftime("%d/%m/%Y"),
            "time":    dt_il.strftime("%H:%M"),
            "weekday": ["שני","שלישי","רביעי","חמישי","שישי","שבת","ראשון"][dt_il.weekday()]
        }
    except:
        return {"date": date_str, "time": time_str or "", "weekday": ""}

def is_over(status: str) -> bool:
    return status in ("FINISHED", "FT", "AET", "PEN", "AP", "Match Finished")

def kickoff_passed(row, hours: float = 2.5) -> bool:
    """האם עברו לפחות X שעות משעת הפתיחה — כלומר המשחק כנראה נגמר במציאות,
    גם אם הסטטוס ב-DB עדיין ישן (לא רוענן מאז)."""
    try:
        dt = datetime.fromisoformat(f"{row['date_utc']}T{row['time_utc']}+00:00")
        return datetime.now(timezone.utc) > dt + timedelta(hours=hours)
    except Exception:
        return False

def likely_over(row) -> bool:
    """הסתיים לפי הסטטוס, או שעברו 6 שעות מהפתיחה (מקור הנתונים לפעמים
    מתעדכן באיחור של יום — ליג 1, 13.9.26). נדחה/בוטל — לא."""
    if is_over(row["status"]):
        return True
    if row["status"] in ("POSTPONED", "CANCELLED"):
        return False
    return kickoff_passed(row, hours=6)


def fetched_recently(row, minutes: int = 10) -> bool:
    """מגן נגד רענוני-אוטו חוזרים: אם הליגה רועננה ממש עכשיו, אין טעם לנסות שוב."""
    conn = get_db()
    try:
        ts = _league_fetched_at(conn, row["league_key"])
    finally:
        conn.close()
    try:
        dt = datetime.fromisoformat(ts)
        return datetime.now(timezone.utc) - dt < timedelta(minutes=minutes)
    except Exception:
        return False

# ── Hebrew team names for YouTube search ──────────────
# ערוצים ישראליים מתייגים בעברית — חיפוש בשמות אנגליים מחזיר ריק.
# התאמה לפי הכלה (case-insensitive), הארוך/ספציפי קודם.
HEB_TEAMS = [
    # sportsdb כותב "Tel-Aviv" עם מקף; מכבי פ"ת חסרה — חיפושים בעברית נכשלו
    ("hapoel tel-aviv",     "הפועל תל אביב"),
    ("maccabi petah tikva", "מכבי פתח תקווה"),
    # לפני "paris" — אחרת פריז FC הפכה ל"פאריס סן ז'רמן"
    ("paris fc",            "פריז FC"),
    ("maccabi tel aviv",  "מכבי תל אביב"),
    ("maccabi haifa",     "מכבי חיפה"),
    ("maccabi netanya",   "מכבי נתניה"),
    ("bnei raina",        "מכבי בני ריינה"),
    ("hapoel tel aviv",   "הפועל תל אביב"),
    ("hapoel jerusalem",  "הפועל ירושלים"),
    ("hapoel haifa",      "הפועל חיפה"),
    ("hapoel ramat gan",  "הפועל רמת גן"),
    ("hapoel petah tikva","הפועל פתח תקווה"),
    ("hapoel kfar saba",  "הפועל כפר סבא"),
    ("beer sheva",        "הפועל באר שבע"),
    ("be'er sheva",       "הפועל באר שבע"),
    ("beitar jerusalem",  'בית"ר ירושלים'),
    ("bnei sakhnin",      "בני סכנין"),
    ("kiryat shmona",     "עירוני קריית שמונה"),
    ("tiberias",          "עירוני טבריה"),
    ("ashdod",            "אשדוד"),
    # ── צ'מפיונס: אנגליה, גרמניה, צרפת ושאר אירופה ──
    # (איטליה/ספרד/ישראל מכוסות בבלוקים האחרים)
    ("manchester city",   "מנצ'סטר סיטי"),
    ("manchester united", "מנצ'סטר יונייטד"),
    ("liverpool",         "ליברפול"),
    ("arsenal",           "ארסנל"),
    ("chelsea",           "צ'לסי"),
    ("tottenham",         "טוטנהאם"),
    ("newcastle",         "ניוקאסל"),
    ("aston villa",       "אסטון וילה"),
    ("bayern",            "באיירן מינכן"),
    ("dortmund",          "דורטמונד"),
    ("leverkusen",        "לברקוזן"),
    ("leipzig",           "לייפציג"),
    ("frankfurt",         "פרנקפורט"),
    ("stuttgart",         "שטוטגרט"),
    ("paris",             "פאריס סן ז'רמן"),   # Paris SG / Paris Saint-Germain
    ("monaco",            "מונאקו"),
    ("marseille",         "מארסיי"),
    ("lille",             "ליל"),
    ("porto",             "פורטו"),
    ("benfica",           "בנפיקה"),
    ("sporting",          "ספורטינג ליסבון"),
    ("ajax",              "אייאקס"),
    ("psv",               "פ.ס.וו איינדהובן"),
    ("feyenoord",         "פיינורד"),
    ("celtic",            "סלטיק"),            # חייב לפני "celta" (סלטה ויגו)
    ("galatasaray",       "גלאטסראיי"),
    ("olympiacos",        "אולימפיאקוס"),
    ("brugge",            "קלאב ברוז'"),
    ("salzburg",          "זלצבורג"),
    ("copenhagen",        "קופנהגן"),
    # ── סריה A (סדר חשוב: אינטר לפני מילאן) ──
    ("inter",             "אינטר"),
    ("milan",             "מילאן"),
    ("juventus",          "יובנטוס"),
    ("napoli",            "נאפולי"),
    ("roma",              "רומא"),
    ("lazio",             "לאציו"),
    ("atalanta",          "אטאלנטה"),
    ("fiorentina",        "פיורנטינה"),
    ("bologna",           "בולוניה"),
    ("torino",            "טורינו"),
    ("genoa",             "ג'נואה"),
    ("cagliari",          "קליארי"),
    ("parma",             "פארמה"),
    ("sassuolo",          "ססואולו"),
    ("udinese",           "אודינזה"),
    ("lecce",             "לצ'ה"),
    ("verona",            "ורונה"),
    ("como",              "קומו"),
    ("monza",             "מונצה"),
    ("empoli",            "אמפולי"),
    ("venezia",           "ונציה"),
    ("cremonese",         "קרמונזה"),
    ("pisa",              "פיזה"),
    ("frosinone",         "פרוזינונה"),
    ("salernitana",       "סלרניטנה"),
    # ── לה ליגה ──
    ("real madrid",       "ריאל מדריד"),
    ("barcelona",         "ברצלונה"),
    ("tico madrid",       "אתלטיקו מדריד"),   # תופס Atlético/Atletico
    ("sevilla",           "סביליה"),
    ("betis",             "בטיס"),
    ("sociedad",          "ריאל סוסיאדד"),
    ("bilbao",            "אתלטיק בילבאו"),
    ("villarreal",        "ויאריאל"),
    ("valencia",          "ולנסיה"),
    ("getafe",            "חטאפה"),
    ("espanyol",          "אספניול"),
    ("celta",             "סלטה ויגו"),
    ("rayo",              "ראיו וייקאנו"),
    ("alav",              "אלאבס"),            # Alavés עם/בלי אקצנט
    ("levante",           "לבנטה"),
    ("elche",             "אלצ'ה"),
    ("mallorca",          "מיורקה"),
    ("osasuna",           "אוססונה"),
    ("girona",            "ג'ירונה"),
    ("laga",              "מאלגה"),            # Málaga/Malaga
    ("santander",         "ראסינג סנטנדר"),
    ("coru",              "דפורטיבו לה קורוניה"),  # A Coruña
    ("oviedo",            "אוביידו"),
]

def to_hebrew_team(name: str) -> str:
    tl = (name or "").lower()
    for key, heb in HEB_TEAMS:
        if key in tl:
            return heb
    return name

# ── שמות קבוצות לתצוגה, לפי שפה ────────────────────────
# נפרד מ-HEB_TEAMS בכוונה: HEB_TEAMS מזין חיפושי תקצירים בעברית (התאמה לפי
# הכלה), וכל שינוי בו משנה חיפושים. כאן — רק מה שהמשתמש רואה. מפתח = השם
# המדויק מהמקור (football-data / TheSportsDB). חסר → נופל ל-HEB_TEAMS / למקור.
TEAM_NAMES = {
    "he": {
        # פרמייר ליג (שמות football-data)
        "AFC Bournemouth": "בורנמות'", "Brentford FC": "ברנטפורד", "Brighton & Hove Albion FC": "ברייטון",
        "Coventry City FC": "קובנטרי", "Crystal Palace FC": "קריסטל פאלאס", "Everton FC": "אברטון",
        "Fulham FC": "פולהאם", "Hull City AFC": "האל סיטי", "Ipswich Town FC": "איפסוויץ'",
        "Leeds United FC": "לידס", "Nottingham Forest FC": "נוטינגהאם פורסט", "Sunderland AFC": "סנדרלנד",
        # צ'מפיונשיפ
        "Birmingham City": "ברמינגהאם", "Blackburn Rovers": "בלקבורן", "Bolton Wanderers": "בולטון",
        "Bristol City": "בריסטול סיטי", "Burnley": "ברנלי", "Cardiff City": "קארדיף",
        "Charlton Athletic": "צ'רלטון", "Derby County": "דרבי קאונטי", "Lincoln City": "לינקולן סיטי",
        "Middlesbrough": "מידלסברו", "Millwall": "מילוול", "Norwich City": "נוריץ'",
        "Portsmouth": "פורטסמות'", "Preston North End": "פרסטון", "Queens Park Rangers": "קווינס פארק ריינג'רס",
        "Sheffield United": "שפילד יונייטד", "Southampton": "סאות'המפטון", "Stoke City": "סטוק סיטי",
        "Swansea City": "סוונסי", "Watford": "ווטפורד", "West Bromwich Albion": "ווסט ברומיץ'",
        "West Ham United": "ווסטהאם", "Wolverhampton Wanderers": "וולבס", "Wrexham": "רקסהאם",
        # ליגת העל
        "Hapoel Tel-Aviv": "הפועל תל אביב", "Maccabi Petah Tikva": "מכבי פתח תקווה",
        # בונדסליגה
        "Augsburg": "אאוגסבורג", "Borussia Mönchengladbach": "בורוסיה מנשנגלדבאך", "Elversberg": "אלברסברג",
        "Freiburg": "פרייבורג", "Hamburg": "המבורג", "Hoffenheim": "הופנהיים", "Köln": "קלן",
        "Mainz": "מיינץ", "Paderborn": "פאדרבורן", "Schalke 04": "שאלקה", "Union Berlin": "אוניון ברלין",
        "Werder Bremen": "ורדר ברמן",
        # ליג 1
        "Angers": "אנז'ה", "Auxerre": "אוקסר", "Brest": "ברסט", "Le Havre": "לה האבר", "Le Mans": "לה מאן",
        "Lens": "לאנס", "Lorient": "לוריין", "Paris FC": "פריז FC", "Lyon": "ליון", "Nice": "ניס", "Rennes": "ראן",
        "Strasbourg": "שטרסבורג", "Toulouse": "טולוז", "Troyes": "טרואה",
        # צ'מפיונס (שלב הליגה)
        "AEK Athens": "א.א.ק אתונה", "Bodø/Glimt": "בודו/גלימט", "Fenerbahçe": "פנרבחצ'ה", "LASK": "לאסק",
        "Sabah Baku": "סבאח באקו", "Shakhtar Donetsk": "שחטאר דונייצק", "Slavia Prague": "סלביה פראג",
        "Slovan Bratislava": "סלובאן ברטיסלבה", "Viking": "ויקינג",
        # ליגה אירופית
        "AZ Alkmaar": "א.ז. אלקמאר", "Anderlecht": "אנדרלכט", "Ararat-Armenia": "ארארט ארמניה",
        "Beşiktaş": "בשיקטאש", "Bournemouth": "בורנמות'", "Celje": "צליה", "Crystal Palace": "קריסטל פאלאס",
        "Dinamo Zagreb": "דינמו זאגרב", "Ferencváros": "פרנצווארוש", "Jagiellonia Białystok": "יאגיילוניה ביאליסטוק",
        "Lech Poznań": "לך פוזנן", "Levski Sofia": "לבסקי סופיה", "Lillestrøm": "לילסטרום",
        "NEC Nijmegen": "NEC ניימכן", "OFI": "אופי כרתים", "Omonia Nicosia": "אומוניה ניקוסיה",
        # הליגה ההולנדית (16.9.26)
        "ADO Den Haag": "אדו האג", "Cambuur": "קמבור", "Excelsior": "אקסלסיור",
        "Fortuna Sittard": "פורטונה סיטארד", "Go Ahead Eagles": "חו אהד איגלס",
        "Groningen": "חרונינגן", "Heerenveen": "חירנפן", "PEC Zwolle": "פ.א.צ זוולה",
        "Sparta Rotterdam": "ספרטה רוטרדם", "Telstar": "טלסטאר", "Twente": "טוונטה",
        "Utrecht": "אוטרכט", "Willem II": "וילם II",
        "Sparta Prague": "ספרטה פראג", "Sturm Graz": "שטורם גראץ", "Sunderland": "סנדרלנד",
        "Torreense": "טוריינסה", "Union Saint-Gilloise": "יוניון סן ז'ילואז", "Viktoria Plzeň": "ויקטוריה פלזן",
        # MLS
        "Atlanta United": "אטלנטה יונייטד", "Austin FC": "אוסטין", "CF Montréal": "מונטריאול",
        "Charlotte FC": "שארלוט", "Chicago Fire": "שיקגו פייר", "Colorado Rapids": "קולורדו ראפידס",
        "Columbus Crew": "קולומבוס קרו", "DC United": "די.סי. יונייטד", "FC Cincinnati": "סינסינטי",
        "FC Dallas": "דאלאס", "Houston Dynamo": "יוסטון דינמו", "Inter Miami": "אינטר מיאמי",
        "LA Galaxy": "לוס אנג'לס גלקסי", "Los Angeles FC": "לוס אנג'לס FC", "Minnesota United": "מינסוטה יונייטד",
        "Nashville SC": "נאשוויל", "New England Revolution": "ניו אינגלנד רבולושן",
        "New York City FC": "ניו יורק סיטי", "New York Red Bulls": "ניו יורק רד בולס",
        "Orlando City": "אורלנדו סיטי", "Philadelphia Union": "פילדלפיה יוניון", "Portland Timbers": "פורטלנד טימברס",
        "Real Salt Lake": "ריאל סולט לייק", "San Diego FC": "סן דייגו", "San Jose Earthquakes": "סן חוזה ארת'קוויקס",
        "Seattle Sounders": "סיאטל סאונדרס", "Sporting Kansas City": "ספורטינג קנזס סיטי",
        "St. Louis City SC": "סנט לואיס סיטי", "Toronto FC": "טורונטו", "Vancouver Whitecaps": "ונקובר וייטקאפס",
        # ארגנטינה
        "Aldosivi": "אלדוסיבי", "Argentinos Juniors": "ארחנטינוס ג'וניורס", "Atlético Tucumán": "אתלטיקו טוקומאן",
        "Banfield": "בנפילד", "Barracas Central": "בארקאס סנטרל", "Belgrano": "בלגרנו",
        "Boca Juniors": "בוקה ג'וניורס", "Central Córdoba de Santiago del Estero": "סנטרל קורדובה",
        "Defensa y Justicia": "דפנסה אי חוסטיסיה", "Deportivo Riestra": "דפורטיבו ריאסטרה",
        "Estudiantes de La Plata": "אסטודיאנטס", "Estudiantes de Río Cuarto": "אסטודיאנטס ריו קוארטו",
        "Gimnasia y Esgrima de La Plata": "חימנסיה לה פלאטה", "Gimnasia y Esgrima de Mendoza": "חימנסיה מנדוסה",
        "Huracán": "הוראקן", "Independiente": "אינדפנדיינטה", "Independiente Rivadavia": "אינדפנדיינטה ריבדביה",
        "Instituto": "אינסטיטוטו", "Lanús": "לאנוס", "Newell's Old Boys": "ניואלס אולד בויז",
        "Platense": "פלטנסה", "Racing Club": "ראסינג קלאב", "River Plate": "ריבר פלייט",
        "Rosario Central": "רוסאריו סנטרל", "San Lorenzo": "סן לורנסו", "Sarmiento": "סרמיינטו",
        "Talleres de Córdoba": "טאייר קורדובה", "Tigre": "טיגרה", "Unión": "אוניון סנטה פה",
        "Vélez Sarsfield": "ולס סרספילד",
    },
    # ספרדית/צרפתית: רק שמות שונים מהאנגלית (השאר — כמו במקור)
    "es": {
        "Bayern Munich": "Bayern de Múnich", "Inter Milan": "Inter de Milán", "Atlético Madrid": "Atlético de Madrid",
        "Sporting CP": "Sporting de Portugal", "Slavia Prague": "Slavia de Praga", "Club Brugge": "Brujas",
        "Köln": "Colonia", "Crvena Zvezda": "Estrella Roja", "Marseille": "Olympique de Marsella",
        "Lyon": "Olympique de Lyon", "Paris Saint-Germain": "París Saint-Germain", "Tottenham Hotspur FC": "Tottenham",
        "Shakhtar Donetsk": "Shajtar Donetsk",
    },
    "fr": {
        "Atlético Madrid": "Atlético de Madrid", "Barcelona": "FC Barcelone", "Sevilla": "Séville",
        "Valencia": "Valence", "Napoli": "Naples", "Roma": "AS Rome", "Genoa": "Gênes", "Venezia": "Venise",
        "Torino": "Turin", "Sporting CP": "Sporting Portugal", "Club Brugge": "FC Bruges", "Köln": "Cologne",
        "Crvena Zvezda": "Étoile rouge de Belgrade", "Bayern Munich": "Bayern Munich",
        "Shakhtar Donetsk": "Chakhtar Donetsk",
    },
}
DISPLAY_LANGS = ("he", "en", "es", "fr")


def _short_en(name: str) -> str:
    """"Arsenal FC" → "Arsenal", "AFC Bournemouth" → "Bournemouth" (שמות football-data)."""
    return re.sub(r"^AFC |\s+A?FC$", "", name or "").strip() or (name or "")


# המפתחות של TEAM_NAMES הם שמות football-data ("Fulham FC"), ובגביע אותה
# קבוצה מגיעה מ-sportsdb בשם אחר ("Fulham"). נבנה פעם אחת גם אינדקס מנורמל,
# אחרת חצי מלוח הגביע היה נשאר באנגלית ליד שמות מתורגמים.
_TEAM_NAMES_BY_KEY: dict = {}


def _names_by_key(lang: str) -> dict:
    if lang not in _TEAM_NAMES_BY_KEY:
        _TEAM_NAMES_BY_KEY[lang] = {team_key(k): v
                                    for k, v in TEAM_NAMES.get(lang, {}).items()}
    return _TEAM_NAMES_BY_KEY[lang]


def display_team(name: str, lang: str = "he") -> str:
    """שם הקבוצה כפי שמוצג למשתמש בשפה שבחר."""
    if not name:
        return name
    if lang == "he":
        return (TEAM_NAMES["he"].get(name) or _names_by_key("he").get(team_key(name))
                or to_hebrew_team(name))
    return (TEAM_NAMES.get(lang, {}).get(name) or _names_by_key(lang).get(team_key(name))
            or _short_en(name))


# ── מפתח קבוצה אחיד (למועדפים — אותה קבוצה בכל מפעל) ───
# "Liverpool FC" (football-data, פרמייר) = "Liverpool" (TheSportsDB, צ'מפיונס).
TEAM_KEY_ALIASES = {
    "tottenham hotspur": "tottenham",
    "brighton hove albion": "brighton",
    "brighton and hove albion": "brighton",
    "wolverhampton wanderers": "wolves",
    "paris saint germain": "psg",
    "inter": "inter milan",
}


def team_key(name: str) -> str:
    s = unicodedata.normalize("NFD", (name or "").lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[^\w\s]", " ", s)                    # פיסוק, &, /, '
    s = re.sub(r"\b(fc|afc|cf|sc)\b", " ", s)           # סיומות מועדון
    s = " ".join(s.split())
    return TEAM_KEY_ALIASES.get(s, s)


def _lang(lang: str) -> str:
    return lang if lang in DISPLAY_LANGS else "he"


GOOGLE_SEARCH_KEY = os.environ.get("GOOGLE_SEARCH_KEY", "")
GOOGLE_CSE_ID     = os.environ.get("GOOGLE_CSE_ID", "")
_ddg_fail_until   = [0.0]   # מפסק זרם: אחרי כישלון, לא מנסים 15 דקות

# קיצורים נפוצים בכותרות ישראליות: מכבי ת"א, הפועל ב"ש...
HE_ABBREV = {
    "תל אביב":     ['ת"א', 'ת״א'],
    "באר שבע":     ['ב"ש', 'ב״ש'],
    "פתח תקווה":   ['פ"ת', 'פ״ת'],
    "קריית שמונה": ['ק"ש', 'ק״ש'],
    "רמת גן":      ['ר"ג', 'ר״ג'],
    "כפר סבא":     ['כ"ס', 'כ״ס'],
    "ירושלים":     ["י-ם", 'י"ם', 'י״ם'],
}

def he_team_variants(heb_name: str) -> list:
    """גרסאות לזיהוי קבוצה בכותרת: השם המלא, החלק המזהה (בלי מכבי/הפועל),
    וקיצורים מקובלים. למשל 'הפועל פתח תקווה' → גם 'פתח תקווה' וגם 'פ"ת'."""
    variants = [heb_name]
    core = heb_name
    for prefix in ("מכבי ", "הפועל ", 'בית"ר ', "עירוני ", "בני ", "מ.ס. "):
        if core.startswith(prefix):
            core = core[len(prefix):]
            break
    if core != heb_name:
        variants.append(core)
    variants.extend(HE_ABBREV.get(core, []))
    return variants

# ── קישורים ישירים לאתרים (ספורט 1 / ספורט 5) ───────────
# בלי מנוע חיפוש (DuckDuckGo חסום): קוראים את עמודי ה-VOD/הליגה של האתר
# ומשווים את הכותרות לשתי הקבוצות בעברית — אותו כלל כמו כותרות ONE.
SITE_TTL = 600
_site_cache = {}


def _site_anchors(url: str) -> list:
    """[(href, text)] מכל העוגנים בעמוד. טקסט מפוענח (&quot; → ") — בלי זה
    'הפועל פ&quot;ת' לא זוהה. קאש בזיכרון 10 דקות לעמוד."""
    hit = _site_cache.get(url)
    if hit and time.time() - hit[0] < SITE_TTL:
        return hit[1]
    out = []
    try:
        r = requests.get(url, timeout=8, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            "Accept-Language": "he-IL,he"})
        if r.status_code == 200:
            # תמיד UTF-8: דף הבית של ספורט 5 לא מצהיר charset, ו-requests
            # פענח אותו כ-latin-1 — הכותרות יצאו ג'יבריש ואף משחק לא זוהה
            content = getattr(r, "content", None)
            body = content.decode("utf-8", "ignore") if isinstance(content, bytes) else r.text
            for m in re.finditer(r"<a([^>]+)>(.*?)</a>", body, re.S):
                href = re.search(r"href=['\"]([^'\"]+)['\"]", m.group(1))
                if not href:
                    continue
                text = re.sub(r"<[^>]+>", " ", m.group(2))
                title = re.search(r"title=['\"]([^'\"]*)['\"]", m.group(1))
                if title:
                    text += " " + title.group(1)
                out.append((_unescape(href.group(1)), " ".join(_unescape(text).split())))
    except Exception as ex:
        print(f"[site] {url}: {ex}")
    _site_cache[url] = (time.time(), out)
    return out


# כתיבים חלופיים שראינו באתרים ישראליים (ספורט 5)
HE_SPELLINGS = {
    "Strasbourg": ["שטראסבורג"],
    "Paris Saint-Germain": ["פ.ס.ז'", "פריז סן ז'רמן"],
    "Bodø/Glimt": ["בודה גלימט"],
    # ONE (15.9.26): "לאמין ובארסה חוגגים על חשבונה של לבאנטה"
    "Barcelona": ["בארסה"],
    "Levante": ["לבאנטה"],
}


def _he_names(team: str) -> list:
    """שמות עבריים לחיפוש בכותרות אתרים. שם מדויק מהמילון גובר — ההתאמה
    החלקית של HEB_TEAMS רק כשאין (אחרת Paris FC חיפשה את PSG)."""
    exact = TEAM_NAMES["he"].get(team)
    names = ([exact] if exact else [to_hebrew_team(team)]) + HE_SPELLINGS.get(team, [])
    return [n for n in dict.fromkeys(names) if n]


IL_PREFIXES = ("מכבי ", "הפועל ", 'בית"ר ', "עירוני ", "בני ", "מ.ס. ")


def _web_team_in(name: str, text: str) -> bool:
    """קבוצה ישראלית: רק שם מלא או קידומת+קיצור ("הפועל פ"ת", "מכבי ת"א") —
    מילה בודדת ("הפועל", "אביב") מופיעה בעשרות כותרות ומבלבלת בין מכבי
    להפועל. קבוצות אחרות — הכלל המקל של כותרות ONE."""
    for p in IL_PREFIXES:
        if name.startswith(p):
            core = name[len(p):]
            return any(f in text for f in [name] + [p + a for a in HE_ABBREV.get(core, [])])
    return _he_team_in(name, text)


def _il_title_norm(title: str) -> str:
    """כתיבים של ערוצי יוטיוב ישראליים לא רשמיים: ביתר / בית''ר / קרית."""
    t = title.replace("`", "'").replace("׳", "'").replace("״", '"').replace("''", '"')
    t = t.replace("ביתר", 'בית"ר').replace("קרית", "קריית")
    return t.replace("הפועל קריית שמונה", "עירוני קריית שמונה")


def is_il_both_teams(title: str, home_he: str, away_he: str,
                     published: str = "", match_date: str = "") -> bool:
    """ערוצים לא רשמיים (העלאות פיראטיות): רק כותרת עם "תקציר" או תוצאה, ושתי
    הקבוצות בשם מלא (בכל סדר) — מכבי ת"א ≠ הפועל ת"א. עד 3 ימים אחרי המשחק, כדי
    שמפגש חוזר (גביע / מחזור הבא) לא ייתפס."""
    t = _il_title_norm(title)
    # "תקציר", או תוצאה ("0-3") — חלק מהכותרות בלי המילה
    if "תקציר" not in t and not re.search(r"\d+\s*-\s*\d+", t):
        return False
    if published and match_date:
        try:
            last = datetime.fromisoformat(match_date).date() + timedelta(days=3)
            if published[:10] > last.isoformat():
                return False
        except ValueError:
            pass
    return _web_team_in(home_he, t) and _web_team_in(away_he, t)


def _en_norm(s: str) -> str:
    """אנגלית להשוואה: בלי גרשים, נקודות ומקפים, רווח אחד בין מילים."""
    s = re.sub(r"[’'`.\-–]", " ", (s or "").lower())
    return " ".join(s.split())


# קידומות מועדון ישראליות באנגלית — "Hapoel Ironi Kiryat Shmona" מופיע
# בכותרות גם כ-"Ironi Kiryat Shmona"
_IL_EN_PREFIXES = ("hapoel", "maccabi", "beitar", "bnei", "ironi", "ms", "fc")


def _en_team_in(name_en: str, title_norm: str) -> bool:
    """שם מלא של הקבוצה (מנורמל), או בלי קידומת אחת — ולא מילה בודדת."""
    full = _en_norm(name_en)
    if not full:
        return False
    forms = [full]
    words = full.split()
    if len(words) >= 3 and words[0] in _IL_EN_PREFIXES:
        forms.append(" ".join(words[1:]))
    return any(len(f) >= 6 and f in title_norm for f in forms)


def is_il_both_teams_en(title: str, home_en: str, away_en: str,
                        published: str = "", match_date: str = "") -> bool:
    """אותו כלל מחמיר, לכותרות באנגלית: מילת תקציר או תוצאה, שתי הקבוצות
    בשמן המלא, ועד 3 ימים אחרי המשחק."""
    t = _en_norm(title)
    if "highlight" not in t and not re.search(r"\d+\s*-\s*\d+", t):
        return False
    if any(x in t for x in ("full match", "all the goals", "only goals", "u19", "u21", "women")):
        return False
    if published and match_date and not _within_days(published, match_date, 3):
        return False
    return _en_team_in(home_en, t) and _en_team_in(away_en, t)


def find_web_highlight(pages: list, link_pattern: str,
                       home_names: list, away_names: list, base: str = ""):
    """URL ישיר לכתבת התקציר באתר, או None. שתי הקבוצות חייבות להופיע
    בכותרת (אין תאריך בעמוד — לא מסתפקים בקבוצה אחת). כותרת עם "תקציר"
    גוברת על קליפ ("צפו: ...") של אותו משחק."""
    def team_in(names, text):
        return any(_web_team_in(n, text) for n in names)

    best = None
    for page in pages:
        for href, text in _site_anchors(page):
            if not re.search(link_pattern, href):
                continue
            t = text.replace("`", "'").replace("׳", "'").replace("״", '"')
            if not (team_in(home_names, t) and team_in(away_names, t)):
                continue
            url = href if href.startswith("http") else base + href
            if "תקציר" in t:
                return url
            best = best or url
    return best


def scrape_sport1_vod(home_he: str, away_he: str):
    """תקציר ספורט 1 לפי שמות עבריים (משמש גם את /debug/vodscrape)."""
    return find_web_highlight(SPORT1_PAGES, SPORT1_LINK, [home_he], [away_he],
                              base="https://sport1.maariv.co.il")


def resolve_web_link(query: str, domain: str):
    """מחלץ URL ישיר לכתבה הראשונה מהדומיין המבוקש — רק דרך Google Custom
    Search (כשמוגדר מפתח). DuckDuckGo הוסר: חסום (גם מ-Render), ועמוד
    התוצאות שלו כלל ספוילרים בכותרות."""
    # מסלול 1: Google CSE
    if GOOGLE_SEARCH_KEY and GOOGLE_CSE_ID:
        try:
            r = requests.get(
                "https://www.googleapis.com/customsearch/v1",
                params={"key": GOOGLE_SEARCH_KEY, "cx": GOOGLE_CSE_ID,
                        "q": query, "siteSearch": domain,
                        "siteSearchFilter": "i", "num": 3},
                timeout=6,
            ).json()
            for item in r.get("items", []):
                if domain in item.get("link", ""):
                    return item["link"]
        except Exception as ex:
            print(f"[weblink/cse] {domain}: {ex}")
    return None


def build_source_query(source: dict, home: str, away: str) -> str:
    if source.get("hebrew_names"):
        home, away = to_hebrew_team(home), to_hebrew_team(away)
    template = source.get("search_template", "{home} {away}")
    return template.format(home=home, away=away)

# ── YouTube ────────────────────────────────────────────

# Regex to detect scores in titles like "2-0", "3:1", "(2-1)"
SCORE_PATTERN = re.compile(r'\b\d+\s*[-:]\s*\d+\b')

def clean_title_for_display(title: str) -> str:
    """Remove anything that looks like a score from a video title."""
    return SCORE_PATTERN.sub("", title).strip()

# כינויים שמופיעים בכותרות במקום השם הרשמי (אחרי lower+deaccent).
# נמצאו בכותרות אמיתיות של ערוצי המועדונים (צ'מפיונס, מחזור 1, 13.9.26).
TEAM_ALIASES = {
    "Paris Saint-Germain": ["psg"],
    "Lille": ["losc"],
    "PSV Eindhoven": ["psv"],
    "Atlético Madrid": ["atleti"],
    "Manchester City": ["man city"],
    "Manchester United": ["man utd", "man united"],
    "Bodø/Glimt": ["glimt"],
    # ליגה אירופית — השם הרשמי בכותרות המועדונים
    "Rennes": ["rennais"],
    # יובנטוס כותבים את היריבה בקיצור ("Juventus 5-0 NEC | Europa League
    # Highlights") — בלי זה שתי הקבוצות לא מזוהות, והכותרת נמצאת רק ביום
    # המשחק עצמו (loose_club)
    "NEC Nijmegen": ["nec"],
    # צ'מפיונשיפ — הקיצורים של Sky Sports
    "Wolverhampton Wanderers": ["wolves"],
    "Queens Park Rangers": ["qpr"],
    "West Bromwich Albion": ["west brom"],
    "Sheffield United": ["sheff utd", "sheffield utd"],
    "Portsmouth": ["pompey"],
    "Preston North End": ["pne"],
    # MLS — השמות בכותרות הערוץ הרשמי
    "Los Angeles FC": ["lafc"],
    "St. Louis City SC": ["st. louis"],
    "DC United": ["d.c. united"],
    "New York City FC": ["nycfc"],
}

# סיומות כלליות — לא מספיקות לבד לזיהוי קבוצה בכותרת. בלי זה, היריבה
# "Bristol City" "נמצאה" בכל כותרת עם City ("Stockport 3-4 Leicester City"
# עבר עבור לינקולן; "Notts County 0-1 Bradford City" עבר עבור נוריץ').
GENERIC_TEAM_WORDS = {
    "city", "united", "county", "rovers", "athletic", "town", "wanderers",
    "albion", "rangers", "wednesday", "end",
    # קיצורים (MLS ועוד): "sc" של St. Louis City SC היה נמצא בכל "score"
    "sc", "cf", "fc", "afc",
}


# מילים שאומרות "זה תקציר משחק", בלי הגנריות ("goals", "match", "vs")
_STRONG_HIGHLIGHT = ("highlight", "תקציר", "resumen", "zusammenfassung", "samenvatting",
                     "sammendrag", "hoydepunkter", "sestrih", "ozet", "sintesi",
                     "resumo", "melhores momentos")


def _within_days(published: str, match_date: str, days: int) -> bool:
    """הסרטון עלה ביום המשחק ועד X ימים אחריו."""
    try:
        gap = (datetime.fromisoformat(published[:10]).date()
               - datetime.fromisoformat(match_date).date()).days
    except (ValueError, TypeError):
        return False
    return 0 <= gap <= days


def is_match_highlight(title: str, home: str, away: str,
                       home_alt: str = None, away_alt: str = None,
                       require_team: bool = False,
                       implicit_team: str = None,
                       loose_club: bool = False) -> bool:
    """home_alt/away_alt: שמות חלופיים (עברית) לזיהוי בכותרת.
    require_team: חובה לזהות קבוצה בכותרת גם כשיש מילת "תקציר" —
    למקורות רב-ליגתיים (ONE), מונע וידאו מליגה לא נכונה."""
    def deaccent(s):
        # Lanús→lanus, Alavés→alaves — משווים בלי אקצנטים
        return "".join(c for c in unicodedata.normalize("NFD", s)
                       if not unicodedata.combining(c))

    t = deaccent(title.lower())

    def clean(team):
        return deaccent(team.lower()
                .replace(" fc","").replace(" afc","")
                .replace(" national football team","")
                .strip())

    def team_in(team):
        c = clean(team)
        words = c.split()
        if c in t:
            return True
        # football-data: "Manchester United FC" — הכינויים שמורים בלי הסיומת
        # ("man utd"); בלי זה אף כינוי לא חל בפרמייר ליג (דרבי מנצ'סטר 13.9)
        base = re.sub(r"\s+A?FC$", "", team.strip())
        # גבול מילה: הקיצורים קצרים, ו-"nec" (NEC נימיכן) יושב גם בתוך
        # "connection". קיצור חייב להופיע בכותרת כמילה שלמה
        if any(re.search(rf"(?<!\w){re.escape(a)}(?!\w)", t)
               for a in TEAM_ALIASES.get(team, []) + TEAM_ALIASES.get(base, [])):
            return True
        if len(words) >= 1 and words[-1] not in GENERIC_TEAM_WORDS and words[-1] in t:
            return True
        # מילה ראשונה משמעותית: "Inter Milan" בכותרת "INTER-MONZA",
        # "Manchester City" בכותרת "MAN CITY". מינימום 4 תווים נגד רעש.
        if len(words) >= 2 and len(words[0]) >= 4 and words[0] in t:
            return True
        return False

    # נרמול גרשיים: ׳/’ → ' וכן ״ → " (אלצ׳ה, ג׳נואה, בית״ר...)
    title_norm = (title.replace("\u05f3", "'").replace("\u2019", "'")
                       .replace("\u05f4", '"'))

    def team_in_ex(team, alt):
        # implicit_team: בערוץ של מועדון, המועדון עצמו לא תמיד בכותרת
        # ("HIGHLIGHTS | Kicking Off ... vs Shakhtar Donetsk" בערוץ PSV)
        if implicit_team and team == implicit_team:
            return True
        if team_in(team):
            return True
        if not alt or alt == team:
            return False
        alt_norm = (alt.replace("\u05f3", "'").replace("\u2019", "'")
                       .replace("\u05f4", '"'))
        return alt_norm in title_norm

    exclude = any(w in t for w in
                  ["compilation", "best of", "every goal", "parade", "bts",
                   "training", "press conference", "interview", "#shorts",
                   "season review", "all goals season", "preview",
                   "prediction", "lineup", "tactical", "pre-match",
                   # post-match: מסיבות עיתונאים וניתוחים ("POST-MATCH ANALYSIS")
                   "post-match", "reaction",
                   "bench cam", "player cam", "fan cam", "tunnel",
                   "pitchside", "pitch side", "behind the scenes",
                   "unseen", "warm up", "warm-up", "arrival", "access all",
                   # ליג 1: שידור חוזר של אולפן טרום-משחק
                   "avant-match", "avant match", "tous les buts",
                   # ערוצי מועדונים (צ'מפיונס): מסיבות עיתונאים בשפות שונות —
                   # "FC Porto vs. Manchester City" עבר את הפילטר בגלל "vs"
                   "conferencia de imprensa", "conferencia de prensa",
                   "conferenza stampa", "conference de presse",
                   "pressekonferenz", "persconferentie",
                   # קבוצות נוער / תוכן נלווה מאותו ערוץ ואותו יריב
                   "u19", "uyl", "youth league", "watchparty", "re-live",
                   # לא הקבוצה הבוגרת: נשים, עתודה ונוער. בערוץ של מועדון הם
                   # עולים באותו סופ"ש ("HIGHLIGHTS | AZ Vrouwen - PSV Vrouwen",
                   # "HIGHLIGHTS U23: RSCA Futures", "Juventus Next Gen")
                   "vrouwen", "women", "féminin", "feminin", "femenino",
                   "jong psv", "jong ajax", "jong az", "jong utrecht", "beloften",
                   "u20", "u23", "next gen", "primavera", "futures", "serie c",
                   # קליפ של שער בודד / קומפילציה של שחקן — גם כשכתוב HIGHLIGHTS
                   # ("HIGHLIGHTS | De vierde goal in vijf wedstrijden voor ...")
                   "goal of the month", "goal van", "goal in vijf", "goal in vier",
                   "goal in drie", "goals in drie", "vote for",
                   "vlog", "uncut", "backstage",
                   # תוכנית אולפן לפני המשחק (Man City, Shakhtar, Wrexham)
                   "matchday live", "match day live"])

    # "תקציר" בכותרת = תקציר. החיפוש כבר scoped לערוץ הנכון.
    # חשוב: הבדיקה הזו חייבת להיות אחרי הגדרת exclude (UnboundLocalError)
    if "תקציר" in t and not exclude:
        if not require_team:
            return True
        # מקור רב-ליגתי: חובה לפחות קבוצה אחת מזוהה בכותרת
        return team_in_ex(home, home_alt) or team_in_ex(away, away_alt)

    has_both  = team_in_ex(home, home_alt) and team_in_ex(away, away_alt)
    highlight = any(w in t for w in
                    ["highlight", "match", "goals", "extended",
                     "שערים", "sign off", "vs", "v.", "\U0001f19a",
                     # הגביע האנגלי: "Knowle FC v Worcester City |
                     # Key Moments | Emirates FA Cup 2027"
                     "key moments",
                     "fifaworldcup", "full match", "resumen",
                     "zusammenfassung",
                     # ליג 1: הפורמט "TEAM - TEAM () | Week N" בלי מילת
                     # תקציר; resume/journee = Résumé/journée אחרי deaccent
                     "week", "resume", "journee",
                     # ערוצי מועדונים: טורקית (özet = תקציר, hafta = מחזור),
                     # הולנדית, איטלקית, פורטוגזית
                     "ozet", "hafta", "samenvatting", "sintesi",
                     "resumo", "melhores momentos",
                     # נורווגית (TV2 Sport), צ'כית (סלביה פראג)
                     "hoydepunkter", "sammendrag", "sestrih",
                     # סלובקית (Slovan Bratislava: "ZOSTRIH | PSG – ŠK Slovan")
                     "zostrih"])
    # תוצאה בכותרת = תקציר, כששתי הקבוצות מזוהות ("Fredrikstad 1 - 1
    # Sarpsborg 08" ב-TV2 הנורווגי) או בערוץ של מועדון ("PSG 6-1 BRATISLAVA")
    if (has_both or implicit_team) and re.search(r"\d{1,2}\s*[-–:]\s*\d{1,2}", t):
        highlight = True

    # ערוץ מועדון שלא כותב את היריבה כלל ("HIGHLIGHTS | A proper PSV night"):
    # חייבת מילת תקציר אמיתית — לא "goals"/"vs" הגנריות, שמופיעות גם
    # בסרטוני שערי החודש ובקומפילציות של שחקן. המתקשר מגביל ליום המשחק/למחרת
    if loose_club and implicit_team and not exclude and any(w in t for w in _STRONG_HIGHLIGHT):
        return True
    return has_both and highlight and not exclude


# ── ONE: כותרות חדשותיות בעברית ────────────────────────
# ONE (לה ליגה, סריה A) לא כותבים "תקציר" — הכותרת היא כותרת חדשות:
# "חוזרת לנצח: אספניול גוברת על אוססונה 0:2", "2:2 אדיר בין לאציו למילאן",
# לפעמים רק קבוצה אחת: "מלדיני מוביל את קליארי לעוד ניצחון" (13.9.26).
HE_GENERIC_WORDS = {"ריאל", "אתלטיק", "מדריד", "דפורטיבו"}   # משותפות לכמה קבוצות
HEADLINE_EXCLUDE = ("#", "בדיוק היום", "ראיון", "מסיבת עיתונאים", "אימון",
                    "החתימה", "הציגה את", "חתם", "פציעה", "נפצע", "פוטר",
                    "שידור חי")
HEADLINE_WINDOW_DAYS = 2   # כותרת עם קבוצה אחת — רק עד יומיים אחרי המשחק


def _he_team_in(team_he: str, title: str) -> bool:
    """שם מלא / גרסה מקובלת, או מילה מזהה מהשם ("ראיו", "בילבאו").
    תחיליות עבריות (ל/ב/ו) מכוסות — בדיקת הכלה ("למילאן" מכיל "מילאן")."""
    if any(_he_contains(v, title) for v in he_team_variants(team_he)):
        return True
    # גם "/" מפריד מילים: "בודו/גלימט" → "גלימט" (ספורט 5: "בודה גלימט")
    return any(_he_contains(w, title) for w in re.split(r"[\s/]+", team_he)
               if len(w) >= 3 and w not in HE_GENERIC_WORDS)


def _he_contains(needle: str, text: str) -> bool:
    """שם קצר (עד 3 אותיות) — רק כמילה שלמה, עם אות תחילית אחת מותרת
    (ב/ו/ל/מ/ש/ה): "לניס" ✓, "ניסיון" ✗, "לילה" ✗ עבור ליל. ארוך — הכלה."""
    if len(needle) > 3:
        return needle in text
    return re.search(r"(?:^|[^֐-׿])[בולמשה]?" + re.escape(needle)
                     + r"(?:$|[^֐-׿])", text) is not None


def is_headline_highlight(title: str, home_he: str, away_he: str,
                          published: str = "", match_date: str = "") -> bool:
    """שתי הקבוצות בכותרת → תקציר. קבוצה אחת → רק אם עלה עד יומיים אחרי
    המשחק. נוסטלגיה/שורטס (#, "בדיוק היום"), ראיונות והחתמות — לא."""
    t = (title.replace("׳", "'").replace("’", "'")
              .replace("״", '"'))
    if any(x in t for x in HEADLINE_EXCLUDE):
        return False
    h, a = _he_team_in(home_he, t), _he_team_in(away_he, t)
    if h and a:
        return True
    if (h or a) and published and match_date:
        try:
            days = (datetime.fromisoformat(published[:10]).date()
                    - datetime.fromisoformat(match_date).date()).days
        except ValueError:
            return False
        return 0 <= days <= HEADLINE_WINDOW_DAYS
    return False


_short_cache = {}   # video_id → True (Short) / False — לא משתנה


def _probe_short(video_id: str):
    """youtube.com/shorts/<id>: 200 = Short, הפניה (303) = סרטון רגיל.
    חינם, בלי מכסה. None = לא ידוע (תקלת רשת)."""
    try:
        r = requests.head(f"https://www.youtube.com/shorts/{video_id}", allow_redirects=False,
                          headers={"User-Agent": "Mozilla/5.0"}, timeout=5)
        return r.status_code == 200 if r.status_code in (200, 301, 302, 303, 307) else None
    except Exception:
        return None


def _is_short(video_id: str) -> bool:
    if video_id not in _short_cache:
        res = _probe_short(video_id)
        if res is None:
            return False            # לא ידוע — לא פוסלים, וננסה שוב בפעם הבאה
        _short_cache[video_id] = res
    return _short_cache[video_id]


def _scrape_durations(video_ids: list) -> dict:
    """גיבוי בלי API (אין מפתח / בלם יומי): "lengthSeconds" מדף הסרטון.
    חינם; רק למעט המועמדים שכבר עברו סינון."""
    durs = {}
    for vid in video_ids[:6]:
        try:
            html = requests.get(f"https://www.youtube.com/watch?v={vid}",
                                headers={"User-Agent": "Mozilla/5.0"}, timeout=8).text
            m = re.search(r'"lengthSeconds":"(\d+)"', html)
            if m:
                durs[vid] = int(m.group(1))
        except Exception:
            pass
    return durs


def _video_durations(video_ids: list) -> dict:
    """videos.list — משך כל וידאו בשניות. יחידת quota אחת לעד 50 IDs.
    בלי מפתח / מעל הבלם — מדף הסרטון (קצר מול מלא עובד תמיד)."""
    if not video_ids:
        return {}
    if not YOUTUBE_API_KEY or _yt_units_today() >= YT_DAILY_BRAKE:
        return _scrape_durations(video_ids)
    _yt_units(1)
    durs = {}
    try:
        resp = requests.get(
            "https://www.googleapis.com/youtube/v3/videos",
            params={"key": YOUTUBE_API_KEY, "part": "contentDetails",
                    "id": ",".join(video_ids[:50])},
            timeout=10
        ).json()
        for item in resp.get("items", []):
            m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?",
                         item["contentDetails"]["duration"])
            if m:
                h, mi, s = (int(x) if x else 0 for x in m.groups())
                durs[item["id"]] = h * 3600 + mi * 60 + s
    except Exception as ex:
        print(f"[durations] {ex}")
    return durs


# ── YouTube RSS: חינם, בלי מכסה ────────────────────────
# לכל ערוץ יש פיד ציבורי עם 15 הסרטונים האחרונים. בודקים אותו לפני
# search.list (100 יחידות מתוך 10,000 ביום). קאש בזיכרון 10 דקות לערוץ —
# ערוץ של מועדון משרת כמה משחקים.
_RSS_TTL = 600
_rss_cache = {}


def _rss_feed(channel_id: str):
    """[(video_id, title, published_iso)] מהחדש לישן, או None בכשל."""
    hit = _rss_cache.get(channel_id)
    if hit and time.time() - hit[0] < _RSS_TTL:
        return hit[1]
    try:
        r = requests.get("https://www.youtube.com/feeds/videos.xml",
                         params={"channel_id": channel_id}, timeout=8)
        if r.status_code != 200:
            print(f"[rss] {channel_id}: HTTP {r.status_code}")
            return None
        items = []
        for entry in re.findall(r"<entry>(.*?)</entry>", r.text, re.S):
            vid   = re.search(r"<yt:videoId>(.*?)</yt:videoId>", entry)
            title = re.search(r"<title>(.*?)</title>", entry, re.S)
            pub   = re.search(r"<published>(.*?)</published>", entry)
            if vid and title and pub:
                items.append((vid.group(1), _unescape(title.group(1)), pub.group(1)))
    except Exception as ex:
        print(f"[rss] {channel_id}: {ex}")
        return None
    _rss_cache[channel_id] = (time.time(), items)
    return items


def _yt_units(n: int):
    """מונה quota יומי ב-meta. היום לפי שעון פסיפיק — כמו האיפוס של גוגל."""
    day = datetime.now(ZoneInfo("America/Los_Angeles")).strftime("%Y-%m-%d")
    try:
        conn = get_db()
        conn.execute("INSERT INTO meta (key, value) VALUES (?, ?) "
                     "ON CONFLICT(key) DO UPDATE SET value = CAST(value AS INTEGER) + ?",
                     (f"yt_units:{day}", str(n), n))
        conn.commit()
        conn.close()
    except Exception as ex:
        print(f"[yt] units counter: {ex}")


YT_DAILY_BRAKE    = 9000   # מעל זה ביום: אין קריאות API בתשלום עד האיפוס
UPLOADS_MAX_PAGES = 10     # 10×50 = 500 סרטונים אחורה — מספיק גם לערוץ MLS


def _yt_units_today() -> int:
    day = datetime.now(ZoneInfo("America/Los_Angeles")).strftime("%Y-%m-%d")
    try:
        conn = get_db()
        row = conn.execute("SELECT value FROM meta WHERE key=?",
                           (f"yt_units:{day}",)).fetchone()
        conn.close()
        return int(row["value"]) if row else 0
    except Exception:
        return 0


def _uploads_since(channel_id: str, match_date: str):
    """רשימת ההעלאות של הערוץ (playlistItems: יחידה אחת ל-50 סרטונים, במקום
    100 לחיפוש), מהחדש לישן, עד שמגיעים לסרטונים מלפני יום המשחק.
    [(video_id, title, published)] — או None בשגיאה (אז נופלים ל-search.list)."""
    playlist = "UU" + channel_id[2:]     # רשימת ה-uploads של כל ערוץ
    out, token, page = [], None, 0
    for page in range(1, UPLOADS_MAX_PAGES + 1):
        params = {"key": YOUTUBE_API_KEY, "playlistId": playlist,
                  "part": "snippet", "maxResults": 50}
        if token:
            params["pageToken"] = token
        try:
            resp = requests.get("https://www.googleapis.com/youtube/v3/playlistItems",
                                params=params, timeout=10).json()
        except Exception as ex:
            print(f"[yt] uploads {channel_id}: {ex}")
            return None
        if "error" in resp:
            print(f"[yt] uploads {channel_id}: {resp['error'].get('message')}")
            return None
        _yt_units(1)
        reached_older = False
        for it in resp.get("items", []):
            sn = it.get("snippet", {})
            pub = sn.get("publishedAt", "")
            if pub[:10] < match_date:
                reached_older = True
                continue
            out.append((sn.get("resourceId", {}).get("videoId"),
                        _unescape(sn.get("title", "")), pub))
        token = resp.get("nextPageToken")
        if reached_older or not token:
            break
    # complete=False: נגמרה התקרה לפני שהגענו ליום המשחק (משחק ישן בערוץ עמוס)
    complete = reached_older or not token
    print(f"[yt] uploads {channel_id}: {page} page(s) = {page} units, "
          f"{len(out)} videos since {match_date}{'' if complete else ' (cap reached)'}")
    return out, complete


# כמה ימים אחרי המשחק תקציר עוד יכול לעלות. הגבול הזה הוא שמבדיל בין
# ניוקאסל–האל של מחזור 5 לניוקאסל–האל של מחזור 24: אותן קבוצות, אותה
# כותרת, והדבר היחיד שמפריד הוא מתי הסרטון עלה. שבעה ימים מכסים גם
# ערוצים שמאחרים (שחטאר העלו אחרי שלושה ימים).
HIGHLIGHT_MAX_DAYS = 7


def search_youtube(home: str, away: str, match_date: str,
                   channel_id: str, query: str = None,
                   title_exclude: list = None,
                   title_include: list = None,
                   home_alt: str = None, away_alt: str = None,
                   require_team: bool = False,
                   implicit_team: str = None,
                   headline: bool = False,
                   il_both: bool = False,
                   date_in_title: bool = False,
                   free_only: bool = False) -> list:
    """Search YouTube for match highlights. Returns list of videos."""
    if not channel_id:
        return []

    def _keep(title: str, published: str = "") -> bool:
        tl = title.lower()
        # אותן שתי קבוצות נפגשות שוב בהמשך העונה, והכותרת זהה. בלי גבול
        # עליון, חיפוש למשחק של מחזור 5 היה תופס את התקציר של מחזור 24 —
        # תוצאה של משחק שעוד לא נצפה, כלומר ספוילר.
        if published and not _within_days(published, match_date, HIGHLIGHT_MAX_DAYS):
            return False
        # סינון ברמת המקור (למשל: רק הגרסה בספרדית של Fanatiz)
        if title_exclude and any(x.lower() in tl for x in title_exclude):
            return False
        if title_include and not any(x.lower() in tl for x in title_include):
            return False
        if date_in_title:  # ערוץ מועדון שכותב את תאריך המשחק (שחטאר: "(10.09.2026)")
            return datetime.fromisoformat(match_date).strftime("%d.%m.%Y") in title
        if il_both:    # ערוצים ישראליים — שתי הקבוצות חייבות להופיע בכותרת
            # עברית, ומ-9.26 גם אנגלית ("Hapoel Be'er Sheva vs. Hapoel Petah
            # Tikva 2-0 Match Highlights"). לא נופלים למסנן הכללי — הוא מסתפק
            # ב"Hapoel" ומתאים כל משחק של הפועל לכל משחק אחר
            return (is_il_both_teams(title, home_alt or home, away_alt or away,
                                     published, match_date)
                    or is_il_both_teams_en(title, home, away, published, match_date))
        if headline:   # ONE — כותרות חדשותיות בעברית, כל כתיב מוכר ("בארסה")
            hs = list(dict.fromkeys([home_alt or home] + _he_names(home)))
            aw = list(dict.fromkeys([away_alt or away] + _he_names(away)))
            return any(is_headline_highlight(title, h, a, published, match_date)
                       for h in hs for a in aw)
        if is_match_highlight(title, home, away, home_alt, away_alt,
                              require_team, implicit_team):
            return True
        # ערוץ של מועדון בלבד, וכשהכלל הרגיל לא מצא: מילת תקציר + עלה ביום
        # המשחק או למחרת (פ.ס.וו לא כותבים את שם היריבה)
        return bool(implicit_team) and _within_days(published, match_date, 1) and \
            is_match_highlight(title, home, away, home_alt, away_alt,
                               require_team, implicit_team, loose_club=True)

    def _video(video_id: str, title: str, published: str = "") -> dict:
        tl = title.lower()
        return {"video_id": video_id,
                "extended": "extended" in tl or "מורחב" in title,
                "published": published,   # #10 — מתי המקור העלה
                "_title":   tl}

    # 1. RSS (חינם). אם הפיד מגיע אחורה עד יום המשחק ואין בו תקציר —
    #    התקציר פשוט עוד לא עלה, ואין טעם לשלם על חיפוש.
    results = None
    feed = _rss_feed(channel_id)
    if feed is not None:
        results = [_video(v, t, p) for v, t, p in feed
                   if p[:10] >= match_date and _keep(t, p)]
        covers = len(feed) < 15 or min(p for _, _, p in feed)[:10] < match_date
        if results:
            print(f"[yt] rss hit {channel_id}: {len(results)} (0 units)")
        elif covers:
            print(f"[yt] rss covers {channel_id} since {match_date}: none yet (0 units)")
            return []
        else:
            results = None   # ערוץ עמוס — הפיד לא מגיע עד יום המשחק

    # 2. API בתשלום — רק כשה-RSS לא יכול להכריע, ורק מתחת לבלם היומי
    if results is None:
        # ערוץ עמוס: ה-RSS מחזיק 15 פריטים בלבד. בערוץ של מנהלת הליגות
        # הם מכסים יומיים-שלושה, ולכן תקציר של מחזור שעבר נמצא מחוץ
        # לטווח (26.9.26). רשימת ההעלאות כן מגיעה עד שם, והיא עולה
        # יחידה אחת ל-50 סרטונים — מול 100 של חיפוש. לכן ברקע היא
        # מותרת, והחיפוש היקר לא.
        if free_only and not (YOUTUBE_API_KEY
                              and _yt_units_today() < PREFETCH_UNIT_BUDGET):
            return None
        if not free_only and not YOUTUBE_API_KEY:
            # ה-RSS לא הכריע (תקלה / ערוץ עמוס) ואין API — לא יודעים.
            # None = לא נשמר כ"אין תקציר" (החזרת [] "קיבעה" משחקים שלמים
            # כשה-RSS של יוטיוב נפל, 16.9.26)
            return None
        if not free_only and _yt_units_today() >= YT_DAILY_BRAKE:
            # None = לא נשמר בקאש כ"לא נמצא" — יחפש שוב אחרי האיפוס היומי
            print(f"[yt] daily brake {YT_DAILY_BRAKE} reached — no API for {channel_id}")
            return None

        # 2א. רשימת ההעלאות: יחידה לכל 50 סרטונים
        uploads = _uploads_since(channel_id, match_date)
        if uploads is not None:
            items_u, complete = uploads
            results = [_video(v, t, p) for v, t, p in items_u if v and _keep(t, p)]
            if not results and not complete:
                # הרשימה לא הגיעה עד יום המשחק — אחרת היה נקבע "לא נמצא" בטעות
                print(f"[yt] uploads cap before {match_date} — falling back to search")
                uploads = None
        if uploads is None and free_only:
            # ברקע עוצרים כאן: החיפוש עולה פי מאה, וזה מה ששרף 9,000
            # יחידות ביום (15–16.9.26)
            return None
        if uploads is None:
            # 2ב. גיבוי: search.list (100 יחידות) — הרשימה לא נגישה,
            #     או שהתקרה נגמרה לפני יום המשחק בלי תוצאה
            params = {
                "key":          YOUTUBE_API_KEY,
                "channelId":    channel_id,
                "part":         "snippet",
                "order":        "relevance",
                "maxResults":   15,
                "type":         "video",
                "q":            query or f"{home} {away}",
                "publishedAfter": f"{match_date}T00:00:00Z",
            }
            try:
                resp = requests.get(
                    "https://www.googleapis.com/youtube/v3/search",
                    params=params, timeout=10
                ).json()
                if "error" in resp:
                    # quotaExceeded וכד' — מחזירים None כדי שלא ייכנס לקאש כ"ריק"
                    print(f"YouTube API error: {resp['error'].get('message')}")
                    return None
                items = resp.get("items", [])
            except Exception as e:
                print(f"YouTube search error: {e}")
                return None
            _yt_units(100)
            print(f"[yt] api search {channel_id} (100 units)")
            results = [_video(item["id"]["videoId"], t, item["snippet"].get("publishedAt", ""))
                       for item in items
                       for t in [_unescape(item["snippet"]["title"])]
                       if _keep(t, item["snippet"].get("publishedAt", ""))]

    # YouTube Shorts (אנכיים) — קליפ חדשות קצר (ONE: "גורדון על ברצלונה")
    # או גרסת "רילז" של תקציר שכבר יש (LALIGA). מקורות כותרות-חדשות: Shorts
    # אף פעם; אחרים: רק כשאין חלופה רגילה.
    if results:
        shorts = {v["video_id"] for v in results if _is_short(v["video_id"])}
        if shorts:
            regular_only = [v for v in results if v["video_id"] not in shorts]
            if regular_only or headline:
                results = regular_only
        if not results:
            return []

    # דירוג: כותרת עם מילת תקציר מפורשת גוברת על התאמה גנרית
    # (מונע bench cam / סרטוני צבע כשקיים תקציר אמיתי)
    EXPLICIT = ("highlights", "תקציר", "resumen", "zusammenfassung")
    explicit_pool = [v for v in results if any(k in v["_title"] for k in EXPLICIT)]
    pool = explicit_pool if explicit_pool else results

    # משכים: מבדיל תקציר-דקה (יום המשחק) מתקציר מלא (יום-יומיים אחרי).
    # עלות: יחידת quota אחת — זניח מול 100 של החיפוש עצמו.
    durs = _video_durations([v["video_id"] for v in pool])
    for v in pool:
        v["_dur"] = durs.get(v["video_id"], 0)

    SHORT_MAX = 150        # עד 2:30 = קצר
    LONG_CAP  = 20 * 60    # מעל 20 דק' = שידור חוזר, לא תקציר

    titled_ext = next((v for v in pool if v["extended"]), None)
    shorts = [v for v in pool if 0 < v["_dur"] <= SHORT_MAX]
    longs  = [v for v in pool if SHORT_MAX < v["_dur"] <= LONG_CAP
              and not v["extended"]]

    final = []
    if shorts and (longs or titled_ext):
        # יש גם קצר וגם מלא — מציגים את שניהם, מתויגים
        final.append({"video_id": shorts[0]["video_id"],
                      "label": "תקציר קצר", "extended": False})
        long_v = titled_ext or longs[0]
        final.append({"video_id": long_v["video_id"],
                      "label": "תקציר מורחב" if long_v is titled_ext else "תקציר מלא",
                      "extended": True})
    else:
        # מקרה רגיל: וידאו אחד רלוונטי + מורחב-לפי-כותרת אם קיים
        # לא שידור חוזר של כל המשחק (בונדסליגה מעלה "X vs. Y | Matchday N"
        # של 2+ שעות דקות אחרי התקציר הקצר)
        regular = next((v for v in pool if not v["extended"] and v["_dur"] <= LONG_CAP), None)
        for v in (regular, titled_ext):
            if v:
                final.append({"video_id": v["video_id"],
                              "label": "תקציר מורחב" if v["extended"] else "תקציר",
                              "extended": v["extended"]})
    pub = {v["video_id"]: v.get("published", "") for v in pool}
    for f in final:
        f["published"] = pub.get(f["video_id"], "")
    return final


# ערוצי מועדונים עם פורמט כותרת משלהם (מתמזג למקור של המועדון)
CLUB_TITLE_RULES = {
    # שחטאר: כותרות באוקראינית — "ПСВ – Шахтар – 1:1 ... Голи та огляд матчу (10.09.2026)".
    # תאריך המשחק בכותרת = התאמה מדויקת; בלי נוער (U14/U21/НЛМ) ובלי משחק מלא
    "Shakhtar Donetsk": {"title_include": ["огляд"],
                         "title_exclude": ["U1", "U2", "НЛМ", "Повна версія", "LIVE"],
                         "title_date": True},
}


def _allowed(sources: list) -> list:
    if UNOFFICIAL_SOURCES:
        return sources
    return [s for s in sources if not s.get("unofficial")]


def get_sources_for_match(row, conn=None) -> list:
    """conn: חיבור פתוח לשימוש חוזר (הפיד קורא לזה לכל משחק — פתיחת חיבור
    לכל שורה הייתה מכפילה את עלות הפיד בפרמייר ליג)."""
    league_key = row["league_key"]
    league     = LEAGUES.get(league_key, {})

    if "club_channels" in league:
        # צ'מפיונס: ערוצי שני המועדונים (לפי שם ב-sportsdb), ואחריהם מקורות
        # הליגה. club_team: בערוץ של מועדון, שמו לא חייב להופיע בכותרת.
        cc = league["club_channels"]
        q = f"{row['home_team']} {row['away_team']}"
        # התאמה מנורמלת: בגביע אותה קבוצה מגיעה משמות שונים
        # ("Brighton & Hove Albion FC" מול "Brighton and Hove Albion")
        by_key = {team_key(name): (name, cid) for name, cid in cc.items()}
        club_sources = []
        for team in (row["home_team"], row["away_team"]):
            hit = by_key.get(team_key(team))
            if not hit:
                continue
            cfg_name, cid = hit
            club_sources.append(
                {"id": f"club_{_fixture_slug(team)}", "name": to_hebrew_team(team),
                 "channel_id": cid,
                 "query_override": q, "club_team": team,
                 **CLUB_TITLE_RULES.get(cfg_name, {})})
        return club_sources + _allowed(league.get("sources", []))

    if "sources" in league:
        return _allowed(league["sources"])

    # Premier League — search by club tier
    own_conn = conn is None
    if own_conn:
        conn = get_db()
    home_club = conn.execute(
        "SELECT * FROM clubs WHERE fd_team_id=? AND league_key=?",
        (row["home_team_id"], league_key)
    ).fetchone()
    away_club = conn.execute(
        "SELECT * FROM clubs WHERE fd_team_id=? AND league_key=?",
        (row["away_team_id"], league_key)
    ).fetchone()
    if own_conn:
        conn.close()

    clubs = []
    for club, team in ((home_club, row["home_team"]), (away_club, row["away_team"])):
        if not (club and club["yt_channel_id"]):
            continue
        # שמירה: הערוץ חייב להיות של אחת מקבוצות המשחק. 15.9.26 הוצגו
        # ערוצי ליברפול ופולהאם במשחק טוטנהאם–אברטון (תקצירים של משחקים אחרים)
        if team_key(club["name"]) != team_key(team):
            print(f"[sources] club/team mismatch in {row['id']}: {club['name']} ≠ {team}")
            continue
        clubs.append(club)
    clubs.sort(key=lambda c: c["tier"])

    # שאילתה משמות קצרים: "Crystal Palace Man City" ולא
    # "Crystal Palace FC Manchester City FC" — חיפוש-בתוך-ערוץ ביוטיוב
    # רגיש לפורמליות, ואומת (אבחון סיטי—פאלאס) שהשמות המלאים מחזירים אפס.
    def _short(club_row, fallback):
        if club_row and club_row["short_name"]:
            return club_row["short_name"]
        s = fallback.replace(" FC", "").replace(" AFC", "").strip()
        if s.startswith("AFC "):
            s = s[4:]
        return s
    short_q = (f"{_short(home_club, row['home_team'])} "
               f"{_short(away_club, row['away_team'])}")

    # club_team: הכפתור מציג את שם המועדון בשפת המשתמש (כמו בצ'מפיונס)
    club_sources = [{"id": f"club_{c['id']}", "name": c["short_name"],
                     "channel_id": c["yt_channel_id"],
                     "query_override": short_q, "club_team": c["name"]}
                    for c in clubs]

    # מקורות גיבוי ברמת הליגה (למשל Sky Sports) — אחרי המועדונים
    return club_sources + league.get("extra_sources", [])

# ── Endpoints ──────────────────────────────────────────

@app.get("/")
def root(request: Request):
    """הכתובת הראשית: מסך כניסה, או האפליקציה למי שמחובר."""
    return serve_frontend(request)


@app.get("/health")
def health():
    return {"status": "SpoilerFree API ✓"}


# ── פרטיות ─────────────────────────────────────────────
# נכתב מתוך הסכימה בפועל (26.9.26), לא מתבנית: כל שורה כאן מתאימה
# לטבלה או לקריאה שקיימות בקוד. אם משנים מה נאסף — משנים גם כאן.
PRIVACY_HE = """<h2>פרטיות</h2>
<p class="upd">עודכן: 26.9.2026</p>

<h3>מה נשמר אצלנו</h3>
<p><b>החשבון:</b> כתובת המייל, מתי נרשמת, מתי התחברת לאחרונה וכמה פעמים.
הסיסמה נשמרת <b>מעורבלת בלבד</b> (PBKDF2, 200,000 סיבובים) — אין לנו דרך
לקרוא אותה.<br>
<b>ההעדפות שלך:</b> הליגות והקבוצות שסימנת, ליגות שהסתרת, והאם לראות תוצאות.<br>
<b>שימוש:</b> פתיחת האתר, מעבר בין ליגות, פתיחת משחק, לחיצה על תקציר או על
קישור לאתר חיצוני — עם השעה ומזהה המשחק. זה משמש אותנו כדי לדעת אילו מקורות
עובדים ואילו לא.<br>
<b>קוד חד-פעמי</b> (כשנשלח) נשמר מעורבל, ונמחק אחרי השימוש או התפוגה.</p>

<h3>מה לא נאסף</h3>
<p>אין תשלומים, אין מיקום, אין גישה לאנשי הקשר, אין העלאת קבצים, ואין פרסום.
המידע לא נמכר.</p>

<h3>מה נשמר במכשיר שלך בלבד</h3>
<p>עוגיית התחברות (עד 90 יום), שפת הממשק, לוח המשחקים בזיכרון מקומי כדי שהאתר
ייפתח מהר, והעדפות תצוגה. אלה לא מגיעים אלינו.</p>

<h3>מי עוד מעורב</h3>
<p>האתר מציג תוכן של אחרים, ולכן הדפדפן שלך פונה אליהם ישירות והם רואים את
כתובת ה-IP שלך:</p>
<p><b>YouTube / Google</b> — התקצירים. צפייה או לחיצה כפופות למדיניות שלהם.
אנחנו משתמשים בגרסת youtube-nocookie.<br>
<b>TheSportsDB</b> — לוח המשחקים נשלף <b>מהדפדפן שלך</b> ישירות משירות זה.<br>
<b>Google Fonts</b> — גופנים.<br>
<b>Brevo</b> — שולחת את מיילי ההתחברות ומקבלת לשם כך את כתובת המייל שלך.<br>
<b>Render</b> ו-<b>Turso</b> — מארחים את האתר ואת מסד הנתונים עבורנו.</p>

<h3>כמה זמן</h3>
<p>חיבור פעיל — עד 90 יום. החשבון והנתונים שלו — עד שתמחק אותו.</p>

<h3>מה אתה יכול לעשות</h3>
<p>בתפריט ☰ ← חשבון אפשר לראות מה שמור עליך <b>ולמחוק את החשבון לצמיתות</b>.
מחיקה מסירה את המייל, ההעדפות, המועדפים ורישום השימוש.</p>

<h3>אבטחה</h3>
<p>סיסמאות מעורבלות, עוגיית התחברות חתומה, ונעילה זמנית אחרי ניסיונות כושלים
חוזרים.</p>
__CONTACT_HE__"""

PRIVACY_EN = """<h2>Privacy</h2>
<p class="upd">Updated: 26 September 2026</p>

<h3>What we keep</h3>
<p><b>Your account:</b> the email address, when you signed up, when you last
signed in and how often. The password is kept <b>hashed only</b> (PBKDF2,
200,000 rounds) — we have no way to read it.<br>
<b>Your choices:</b> the leagues and teams you follow, leagues you hid, and
whether you want to see scores.<br>
<b>Use:</b> opening the site, switching leagues, opening a match, pressing a
highlight or an outside link — with the time and the match. We use this to
tell which sources work and which do not.<br>
<b>A one-time code</b>, when one is sent, is stored hashed and deleted once
used or expired.</p>

<h3>What we never collect</h3>
<p>No payments, no location, no contacts, no uploads, no advertising. Nothing
is sold.</p>

<h3>What stays on your device</h3>
<p>The login cookie (up to 90 days), your language, the fixtures kept locally
so the site opens quickly, and display preferences. These never reach us.</p>

<h3>Who else is involved</h3>
<p>The site shows other people's content, so your browser contacts them
directly and they see your IP address:</p>
<p><b>YouTube / Google</b> — the highlights, under their own policies. We use
the youtube-nocookie version.<br>
<b>TheSportsDB</b> — fixtures are fetched <b>by your browser</b>, directly.<br>
<b>Google Fonts</b> — fonts.<br>
<b>Brevo</b> — sends sign-in emails and receives your address to do so.<br>
<b>Render</b> and <b>Turso</b> — host the site and the database for us.</p>

<h3>How long</h3>
<p>A signed-in session lasts up to 90 days. Your account and its data stay
until you delete it.</p>

<h3>What you can do</h3>
<p>Under ☰ → Account you can see what is stored about you and
<b>delete your account permanently</b>. That removes the email, the
preferences, the favourites and the usage record.</p>

<h3>Security</h3>
<p>Hashed passwords, a signed login cookie, and a temporary lock after repeated
failed attempts.</p>
__CONTACT_EN__"""


TERMS_HE = """<h2>תנאי שימוש</h2>
<p class="upd">עודכן: 26.9.2026</p>

<h3>מה השירות הזה</h3>
<p>SpoilerFree מציג לוח משחקים ומפנה לתקצירים, בלי לחשוף תוצאות. השימוש חינם.
זה פרויקט אישי ולא חברה — הוא מתוחזק כתחביב, וזה הבסיס לכל מה שכתוב כאן.</p>

<h3>מה אנחנו לא</h3>
<p><b>אנחנו לא מארחים תקצירים ולא מעלים אותם.</b> הסרטונים יושבים ביוטיוב
ובאתרי הספורט, בבעלות מי שהעלה אותם, וכפופים לתנאים שלהם. אנחנו מפנים אליהם
בלבד. אם אתה בעל זכויות ותוכן שלך מופיע כאן שלא כדין — כתוב לנו והקישור יוסר.</p>

<h3>החשבון שלך</h3>
<p>חשבון אחד לאדם, עם כתובת מייל אמיתית שלך. הסיסמה באחריותך; אם נראה לך
שמישהו נכנס אליה, החלף אותה. אפשר למחוק את החשבון בכל רגע דרך ☰ ← חשבון.</p>

<h3>מה אסור</h3>
<p>לא לגשת לאתר באמצעים אוטומטיים, לא לנסות לעקוף את מגבלות ההרשמה או את
מנגנוני האבטחה, ולא להעמיס עליו. חשבון שעושה את זה ייחסם.</p>

<h3>זמינות</h3>
<p>האתר עשוי להיות איטי, לא זמין, או להשתנות — בלי הודעה מראש. לוח המשחקים
והתקצירים מגיעים ממקורות חיצוניים, ולכן הם עשויים להיות חסרים, מאוחרים או
שגויים. אנחנו עושים מאמץ שלא ייחשפו תוצאות, <b>אבל אי אפשר להבטיח זאת</b>:
כותרת, תמונה או תגובה באתר חיצוני עלולות להסגיר תוצאה.</p>

<h3>אחריות</h3>
<p>השירות ניתן כמות שהוא, בלי התחייבות. במידה שהחוק מתיר, אין אחריות לנזק
שנגרם משימוש בו — לרבות תוצאה שנחשפה.</p>

<h3>שינויים וסיום</h3>
<p>התנאים עשויים להשתנות; המשך שימוש אחרי עדכון מהווה הסכמה. אפשר להפסיק
להפעיל את השירות בכל עת.</p>

<h3>דין</h3>
<p>על התנאים חל הדין הישראלי.</p>
__CONTACT_HE__"""

TERMS_EN = """<h2>Terms of use</h2>
<p class="upd">Updated: 26 September 2026</p>

<h3>What this is</h3>
<p>SpoilerFree shows fixtures and points you to highlights without giving the
result away. It is free. It is a personal project rather than a company —
maintained as a hobby, which is the ground for everything below.</p>

<h3>What we are not</h3>
<p><b>We do not host highlights and we do not upload them.</b> The videos live
on YouTube and on sports sites, belong to whoever posted them, and are subject
to those sites' terms. We link to them. If you hold rights to something that
appears here without permission, write to us and the link will be removed.</p>

<h3>Your account</h3>
<p>One account per person, with an email address that is really yours. The
password is your responsibility; change it if you think someone else has it.
You can delete the account at any time under ☰ → Account.</p>

<h3>What is not allowed</h3>
<p>No automated access, no working around the sign-up limits or the security
measures, and no overloading the site. An account doing any of that will be
closed.</p>

<h3>Availability</h3>
<p>The site may be slow, unavailable, or changed without notice. Fixtures and
highlights come from outside sources, so they can be missing, late or wrong. We
work at not revealing results, <b>but it cannot be guaranteed</b>: a title, a
thumbnail or a comment on someone else's site may give a score away.</p>

<h3>Liability</h3>
<p>The service is provided as is, without warranty. To the extent the law
allows, there is no liability for harm arising from using it — including a
result that was revealed.</p>

<h3>Changes and ending</h3>
<p>These terms may change; continuing to use the site after an update means
accepting it. The service may be stopped at any time.</p>

<h3>Law</h3>
<p>Israeli law applies.</p>
__CONTACT_EN__"""


def terms_html(lang: str = "he") -> str:
    return _with_contact(TERMS_HE if lang == "he" else TERMS_EN)


def _with_contact(body: str) -> str:
    """כתובת ליצירת קשר — דרושה גם לפרטיות וגם לתנאים (ולהסרת תוכן)."""
    who = sorted(NOTIFY_EMAILS or ADMIN_EMAILS)
    line = (f'<h3>יצירת קשר</h3><p dir="ltr"><a href="mailto:{who[0]}">{who[0]}</a></p>'
            if who else "")
    line_en = (f'<h3>Contact</h3><p dir="ltr"><a href="mailto:{who[0]}">{who[0]}</a></p>'
               if who else "")
    return body.replace("__CONTACT_HE__", line).replace("__CONTACT_EN__", line_en)


def privacy_html(lang: str = "he") -> str:
    """טקסט הפרטיות. es/fr מקבלים אנגלית — עדיף על תרגום מכונה של טקסט
    שמשמעותו משפטית."""
    return _with_contact(PRIVACY_HE if lang == "he" else PRIVACY_EN)


COOKIES_HTML = """<h2>הגדרות עוגיות ופרטיות</h2>
<p>אנחנו משתמשים בעוגיות ובטכנולוגיות דומות כדי שהאתר יעבוד, כדי לזכור את
ההתחברות שלך וכדי לשפר את השירות.</p>
<h3>עוגיות הכרחיות</h3>
<p>נדרשות להתחברות ולאבטחה (עוגיית התחברות למשך עד 90 יום). אי אפשר לבטל אותן.</p>
<h3>אחסון מקומי</h3>
<p>לוח המשחקים והדף נשמרים במכשיר שלך, כדי שהאתר ייפתח מהר גם בחיבור חלש.</p>
<h3>נתוני שימוש</h3>
<p>אנחנו שומרים את כתובת המייל שלך, מועדי התחברות, ואילו ליגות, משחקים ותקצירים
פתחת — לצורך תפעול ושיפור השירות. המידע לא נמכר. פירוט מלא, כולל מי עוד
מעורב, נמצא ב<a href="/privacy">מדיניות הפרטיות</a>.</p>
<h3>שירותי צד שלישי</h3>
<p>סרטונים נפתחים ביוטיוב וכפופים למדיניות של YouTube ו-Google. גופנים נטענים
מ-Google Fonts.</p>
<h3>ניהול ומחיקה</h3>
<p>אפשר לצפות בפרטי החשבון ולמחוק אותו לצמיתות דרך "חשבון" בראש העמוד, לאחר
ההתחברות.</p>"""


COOKIES_HTML_BY_LANG = {
    "he": COOKIES_HTML,
    "en": """<h2>Cookie & privacy settings</h2>
<p>We use cookies and similar technologies to make the site work, remember your
login and improve the service.</p>
<h3>Essential cookies</h3>
<p>Needed for login and security (a login cookie for up to 90 days). They can't be turned off.</p>
<h3>Local storage</h3>
<p>Fixtures and the page are stored on your device so the site opens quickly, even on a weak connection.</p>
<h3>Usage data</h3>
<p>We store your email address, login times, and which leagues, matches and highlights
you opened — to run and improve the service. This data is not sold or shared with third parties.</p>
<h3>Third-party services</h3>
<p>Videos open on YouTube and are subject to YouTube and Google policies. Fonts load from Google Fonts.</p>
<h3>Manage and delete</h3>
<p>You can view your account details and delete your account permanently from "Account" at the top of the page, after logging in.</p>""",
    "es": """<h2>Configuración de cookies y privacidad</h2>
<p>Usamos cookies y tecnologías similares para que el sitio funcione, recordar tu
sesión y mejorar el servicio.</p>
<h3>Cookies necesarias</h3>
<p>Necesarias para el inicio de sesión y la seguridad (una cookie de sesión de hasta 90 días). No se pueden desactivar.</p>
<h3>Almacenamiento local</h3>
<p>Los partidos y la página se guardan en tu dispositivo para que el sitio abra rápido, incluso con mala conexión.</p>
<h3>Datos de uso</h3>
<p>Guardamos tu correo, las horas de acceso y qué ligas, partidos y resúmenes abriste,
para operar y mejorar el servicio. No se venden ni se comparten con terceros.</p>
<h3>Servicios de terceros</h3>
<p>Los vídeos se abren en YouTube y se rigen por las políticas de YouTube y Google. Las fuentes se cargan desde Google Fonts.</p>
<h3>Gestión y eliminación</h3>
<p>Puedes ver los datos de tu cuenta y eliminarla definitivamente desde "Cuenta", arriba de la página, tras iniciar sesión.</p>""",
    "fr": """<h2>Paramètres des cookies et confidentialité</h2>
<p>Nous utilisons des cookies et des technologies similaires pour faire fonctionner le
site, mémoriser votre connexion et améliorer le service.</p>
<h3>Cookies essentiels</h3>
<p>Nécessaires à la connexion et à la sécurité (un cookie de connexion jusqu'à 90 jours). Ils ne peuvent pas être désactivés.</p>
<h3>Stockage local</h3>
<p>Le calendrier et la page sont enregistrés sur votre appareil pour que le site s'ouvre vite, même avec une connexion faible.</p>
<h3>Données d'utilisation</h3>
<p>Nous enregistrons votre e-mail, vos heures de connexion et les ligues, matchs et
résumés consultés, pour faire fonctionner et améliorer le service. Ces données ne sont ni vendues ni partagées.</p>
<h3>Services tiers</h3>
<p>Les vidéos s'ouvrent sur YouTube et relèvent des règles de YouTube et Google. Les polices sont chargées depuis Google Fonts.</p>
<h3>Gestion et suppression</h3>
<p>Vous pouvez consulter votre compte et le supprimer définitivement via « Compte » en haut de la page, une fois connecté.</p>""",
}


@app.get("/cookies")
def cookies_policy(lang: str = "he"):
    """תוכן חלון "Cookie settings" — ציבורי, משותף למסך הכניסה ולאפליקציה."""
    return HTMLResponse(COOKIES_HTML_BY_LANG.get(lang, COOKIES_HTML))


# ספרדית וצרפתית מקבלות את המסמך באנגלית — תרגום מכונה של טקסט משפטי
# גרוע מטקסט מובן בשפה אחרת. הקישור אליו מתורגם ("Términos"), ולכן צריך
# שורה שאומרת את זה, במקום עמוד שנפתח בשפה אחרת בלי הסבר.
_ENGLISH_NOTE = {
    "es": "Este documento solo está disponible en inglés.",
    "fr": "Ce document n'est disponible qu'en anglais.",
}


def _english_note(lang: str) -> str:
    note = _ENGLISH_NOTE.get(lang)
    return f'<p class="upd">{note}</p>' if note else ""


def _policy_page(body: str, title: str, lang: str) -> HTMLResponse:
    """עמוד מדיניות עומד בפני עצמו — כתובת משלו, כדי שאפשר לקשר אליו
    מחוץ לאתר. אותו טקסט מוצג גם בתוך האפליקציה."""
    rtl = lang == "he"
    return HTMLResponse(f"""<!DOCTYPE html>
<html lang="{'he' if rtl else 'en'}" dir="{'rtl' if rtl else 'ltr'}"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>SpoilerFree — {title}</title>
<style>
body{{background:#0a0a0f;color:#e8e8f0;font-family:system-ui,'Heebo',sans-serif;
line-height:1.7;margin:0;padding:2rem 1.25rem;}}
main{{max-width:640px;margin:0 auto;}}
h2{{font-size:1.4rem;margin:0 0 0.2rem;}}
h3{{font-size:0.95rem;color:#00e5a0;margin:1.6rem 0 0.3rem;}}
p{{font-size:0.9rem;color:#b9b9c8;margin:0.3rem 0;}}
.upd{{font-size:0.75rem;color:#6b6b80;}}
a{{color:#00e5a0;}}
nav{{margin-top:2.5rem;font-size:0.8rem;}}
</style></head><body><main>{_english_note(lang)}{body}
<nav><a href="/privacy?lang={lang}">{'פרטיות' if rtl else 'Privacy'}</a> ·
<a href="/terms?lang={lang}">{'תנאי שימוש' if rtl else 'Terms'}</a> ·
<a href="/">{'לאתר' if rtl else 'To the site'}</a></nav>
</main></body></html>""")


@app.get("/privacy")
def privacy_policy(lang: str = "he"):
    return _policy_page(privacy_html(lang), "פרטיות" if lang == "he" else "Privacy", lang)


@app.get("/terms")
def terms_of_use(lang: str = "he"):
    return _policy_page(terms_html(lang),
                        "תנאי שימוש" if lang == "he" else "Terms of use", lang)


@app.get("/health/db")
def health_db():
    """זמני DB בלבד (בלי נתונים) — למדידת Turso בפרודקשן בלי התחברות."""
    t0 = time.perf_counter()
    conn = get_db()
    t1 = time.perf_counter()
    conn.execute("SELECT COUNT(*) FROM meta").fetchone()
    t2 = time.perf_counter()
    conn.close()
    return {"turso": bool(TURSO_DATABASE_URL and libsql is not None),
            "connect_ms": round((t1 - t0) * 1000),
            "query_ms": round((t2 - t1) * 1000)}


@app.get("/health/rss")
def health_rss():
    """האם ה-RSS של יוטיוב נגיש מהשרת (Render) — בלי נתוני משתמש."""
    t0 = time.perf_counter()
    _rss_cache.pop("UC9LQwHZoucFT94I2h6JOcjw", None)
    feed = _rss_feed("UC9LQwHZoucFT94I2h6JOcjw")   # ערוץ ליברפול
    return {"ok": feed is not None, "items": len(feed or []),
            "ms": round((time.perf_counter() - t0) * 1000)}


def _admin_msg(text: str, status: int = 200):
    return HTMLResponse(
        '<body style="background:#0a0a0f;color:#e8e8f0;font-family:sans-serif;padding:2rem" dir="rtl">'
        f'<p>{text}</p><p><a style="color:#00e5a0" href="/admin/users">← לעמוד הניהול</a></p></body>',
        status_code=status)


@app.get("/admin/gmail/connect")
def admin_gmail_connect(request: Request):
    """חד-פעמי: המנהל נכנס עם חשבון ה-Gmail השולח ומאשר "שליחת מיילים".
    Google חוזרת ל-callback עם קוד → ה-refresh token נשמר ב-DB (לא מוצג)."""
    require_admin(request)
    if not (GMAIL_CLIENT_ID and GMAIL_CLIENT_SECRET):
        return _admin_msg("חסרים GMAIL_CLIENT_ID / GMAIL_CLIENT_SECRET ב-Render.", 400)
    from urllib.parse import urlencode
    state = secrets.token_urlsafe(24)
    _meta_set("gmail_oauth_state", f"{state}|{int(time.time()) + 600}")
    params = {"client_id": GMAIL_CLIENT_ID, "redirect_uri": APP_URL + GMAIL_CALLBACK,
              "response_type": "code", "scope": GMAIL_SCOPES,
              "access_type": "offline", "prompt": "consent", "state": state}
    if GMAIL_USER:
        params["login_hint"] = GMAIL_USER
    return RedirectResponse("https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(params))


@app.get(GMAIL_CALLBACK)
def admin_gmail_callback(request: Request, code: str = "", state: str = "", error: str = ""):
    require_admin(request)
    if error:
        return _admin_msg(f"Google החזירה שגיאה: {_html_escape(error)}", 400)
    saved, _, exp = (_meta_get("gmail_oauth_state") or "|0").partition("|")
    if not (state and saved and hmac.compare_digest(state, saved) and time.time() < int(exp or 0)):
        return _admin_msg("הקישור פג תוקף — התחל שוב מ\"חיבור Gmail\".", 400)
    _meta_set("gmail_oauth_state", "|0")          # חד-פעמי
    r = requests.post("https://oauth2.googleapis.com/token", data={
        "code": code, "client_id": GMAIL_CLIENT_ID, "client_secret": GMAIL_CLIENT_SECRET,
        "redirect_uri": APP_URL + GMAIL_CALLBACK, "grant_type": "authorization_code"}, timeout=15)
    j = r.json()
    if "refresh_token" not in j:
        return _admin_msg(f"לא התקבל אישור קבוע מ-Google ({_html_escape(str(j.get('error', '')))}). "
                          "נסה שוב.", 400)
    email = None
    if j.get("id_token"):
        import base64
        part = j["id_token"].split(".")[1]
        email = json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4))).get("email")
    _meta_set("gmail_refresh_token", j["refresh_token"])
    if email:
        _meta_set("gmail_sender", email)
    _gmail_token.update(value=None, exp=0.0)
    return _admin_msg(f"✓ Gmail מחובר ({_html_escape(email or '')}). "
                      "מעכשיו קודי הכניסה נשלחים דרך Gmail API.")


@app.get("/debug/mail")
def debug_mail(request: Request):
    """אבחון שליחת מיילים (למנהלים): המשתנים מוגדרים? Render מגיע ל-Gmail?
    Gmail מקבל את הסיסמה? — בלי לשלוח מייל ובלי לחשוף את הסיסמה."""
    import socket
    require_admin(request)
    report = {"gmail_user": GMAIL_USER or None,
              "password_set": bool(GMAIL_APP_PASSWORD),
              "password_length": len(GMAIL_APP_PASSWORD),          # צריך להיות 16
              "password_had_spaces": " " in os.environ.get("GMAIL_APP_PASSWORD", "")}
    report["gmail_api"] = {"client_set": bool(GMAIL_CLIENT_ID and GMAIL_CLIENT_SECRET),
                           "connected": bool(_gmail_refresh_token()),
                           "sender": _meta_get("gmail_sender"),
                           "token_ok": bool(_gmail_access_token()) if gmail_api_ready() else None}
    report["brevo"] = {"key_set": bool(BREVO_API_KEY), "sender": BREVO_SENDER or None,
                       "active": bool(BREVO_API_KEY and BREVO_SENDER)}
    if BREVO_API_KEY:
        try:   # GET /account: 200 = המפתח תקין (לא שולח כלום)
            a = requests.get("https://api.brevo.com/v3/account",
                             headers={"api-key": BREVO_API_KEY, "accept": "application/json"}, timeout=10)
            report["brevo"]["key_ok"] = a.status_code == 200
            if a.status_code != 200:
                report["brevo"]["error"] = a.status_code
        except Exception as ex:
            report["brevo"]["key_ok"] = False
            report["brevo"]["error"] = type(ex).__name__
    for port in (465, 587):
        try:
            socket.create_connection(("smtp.gmail.com", port), timeout=8).close()
            report[f"port_{port}"] = "open"
        except Exception as ex:
            report[f"port_{port}"] = f"blocked: {type(ex).__name__}"
    if report["port_465"] == "open" and GMAIL_USER and GMAIL_APP_PASSWORD:
        try:
            with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=15) as s:
                s.login(GMAIL_USER, GMAIL_APP_PASSWORD)
            report["login"] = "ok"
        except smtplib.SMTPAuthenticationError as ex:
            report["login"] = f"rejected by Gmail: {ex.smtp_code}"
        except Exception as ex:
            report["login"] = f"error: {type(ex).__name__}"
    return report


@app.get("/debug/db")
def debug_db(request: Request):
    """כמה סנכרונים מול Turso באמת קרו. skipped = בקשות שנחסכו להן
    סבב רשת בזכות החיבור המשותף — היחס ביניהם הוא כל העניין."""
    require_admin(request)
    st = _libsql_state
    return {"turso": bool(TURSO_DATABASE_URL and libsql is not None),
            "shared": TURSO_SHARED, "sync_every_sec": TURSO_SYNC_SEC,
            "connected": st["conn"] is not None,
            "syncs": st["syncs"], "skipped": st["skipped"],
            "sync_errors": st["errors"], "rebuilds": st["rebuilds"],
            "shared_failures": st.get("fails", 0),
            "last_error": st.get("last_error"),
            "last_error_at": st.get("last_error_at"),
            "last_error_thread": st.get("last_error_thread"),
            "seconds_since_sync": round(time.time() - st["synced_at"], 1)
                                  if st["synced_at"] else None}


@app.get("/debug/quota")
def debug_quota(request: Request):
    """צריכת quota של יוטיוב ב-7 הימים האחרונים (לפי מונה פנימי)."""
    require_admin(request)
    conn = get_db()
    rows = conn.execute("SELECT key, value FROM meta WHERE key LIKE 'yt_units:%' "
                        "ORDER BY key DESC LIMIT 7").fetchall()
    conn.close()
    return {"limit_per_day": 10000,
            "days": {r["key"][len("yt_units:"):]: int(r["value"]) for r in rows}}


@app.post("/login")
def login(payload: dict = Body(...)):
    if not APP_PASSWORD:
        return {"ok": True}
    if payload.get("password", "") != APP_PASSWORD:
        raise HTTPException(401, "סיסמה שגויה")
    resp = JSONResponse({"ok": True})
    resp.set_cookie("sf_auth", _auth_token(),
                    max_age=90 * 24 * 3600,  # 90 יום
                    httponly=True, samesite="lax")
    return resp


def _highlight_states(conn, rows: list) -> dict:
    """id → "yes" (יש תקציר שמור) / "none" (בדקנו, אין, והבדיקה עדיין
    תקפה) / חסר (לא יודעים — ואז לא מבטיחים למשתמש כלום).

    "אין" חייב להיות באותו תוקף שהחלון נותן לו: "לא נמצא" במשחק טרי
    נבדק שוב אחרי 30 דקות (_not_found_retry). בלי הכלל הזה הפיד הכריז
    "אין עדיין תקציר" על ברייטון–ארסנל (20.9.26 בבוקר), והחלון — שבדק
    מחדש — הציג מיד שני תקצירים.

    שתי הבטחות שהיו נשברות (QA, 26.9.26):
    1. הקאש משותף לשתי הכתובות, ולכן שורה של מקור לא רשמי נשמרת גם
       כשהאתר הציבורי לא מגיש אותו — הכרטיס הבטיח "▶ תקציר" והחלון הציג
       "עדיין לא הועלה". לכן נספרות רק שורות של מקורות שהמופע הזה יגיש.
    2. "אין עדיין תקציר" נאמר גם כשמקור אחד מתוך שבעה נבדק. זה לא "אין",
       זה "לא בדקנו" — ואז אין מצב, והכרטיס לא מבטיח דבר."""
    ids = [r["id"] for r in rows]
    per: dict = {}
    for i in range(0, len(ids), 400):              # SQLite מגביל פרמטרים
        chunk = ids[i:i + 400]
        marks = ",".join("?" * len(chunk))
        for c in conn.execute(
                f"SELECT match_id, source_id, videos_json, found_at "
                f"FROM highlight_cache WHERE match_id IN ({marks})",
                chunk).fetchall():
            per.setdefault(c["match_id"], []).append(c)

    now = datetime.now(timezone.utc)
    states = {}
    for row in rows:
        mid = row["id"]
        servable = {s["id"] for s in get_sources_for_match(row, conn)
                    if s.get("channel_id")}
        servable |= {f"web_{w['name']}" for w in
                     LEAGUES.get(row["league_key"], {}).get("web_sources", [])}
        cached = [c for c in per.get(mid, []) if c["source_id"] in servable]
        if not cached:
            continue
        if any(c["videos_json"] not in ("[]", "") for c in cached):
            states[mid] = "yes"
            continue
        if {c["source_id"] for c in cached} != servable:
            continue        # מקור שלא נבדק בכלל — אולי דווקא הוא ימצא
        retry = _not_found_retry(row)

        def still_valid(c):
            if retry is None:       # לא ייבדק שוב — "אין" נשאר נכון
                return True
            try:
                return now - datetime.fromisoformat(c["found_at"]) <= retry
            except (ValueError, TypeError):
                return False

        # כל מקור צריך להיות בתוקף: אחד שפג יישלח לבדיקה חוזרת בפתיחה,
        # ואולי דווקא הוא ימצא
        if all(still_valid(c) for c in cached):
            states[mid] = "none"
    return states


@app.get("/matches/{league_key}")
def get_matches(request: Request, league_key: str,
                refresh: bool = False, matchday: int = None, lang: str = "he",
                scores: bool = False):
    lang = _lang(lang)
    require_auth(request)
    if league_key not in LEAGUES:
        raise HTTPException(404, "ליגה לא נמצאה")

    if refresh:
        fetch_and_store(league_key, purge=True)

    query  = "SELECT * FROM matches WHERE league_key=?"
    params = [league_key]
    if matchday:
        query += " AND matchday=?"
        params.append(matchday)
    query += " ORDER BY date_utc, time_utc"

    conn = get_db()
    rows = conn.execute(query, params).fetchall()
    last_fetch = _league_fetched_at(conn, league_key)
    hl_state = _highlight_states(conn, rows)
    conn.close()

    # ליגה ריקה לגמרי — שליפה ראשונה. לא ב-Render לליגות sportsdb: שם
    # TheSportsDB חסום, והניסיון תקע את התשובה עד 3×15 שניות (בונדסליגה
    # "לוקחת הרבה זמן"); הדפדפן מרענן ליגה ריקה בעצמו תוך פחות משנייה.
    blocked = bool(os.environ.get("RENDER")) and LEAGUES[league_key].get("source") == "sportsdb"
    if not rows and not matchday and not refresh and not blocked:
        fetch_and_store(league_key)
        conn = get_db()
        rows = conn.execute(query, params).fetchall()
        last_fetch = _league_fetched_at(conn, league_key)
        conn.close()

    league_name = LEAGUES[league_key]["name"]
    matches = []
    for row in rows:
        il = to_israel_time(row["date_utc"], row["time_utc"])
        matches.append({
            "id":       row["id"],
            "home":     row["home_team"],
            "away":     row["away_team"],
            "home_name": display_team(row["home_team"], lang),
            "away_name": display_team(row["away_team"], lang),
            "home_key":  team_key(row["home_team"]),
            "away_key":  team_key(row["away_team"]),
            "date":     il["date"],
            "time":     il["time"],
            "weekday":  il["weekday"],
            "venue":    row["venue"] or "",
            "matchday": row["matchday"],
            "league":   league_name,
            "is_over":  likely_over(row),
            # "yes" = יש תקציר שמור, "none" = בדקנו ואין עדיין,
            # חסר = עוד לא נבדק (ואז לא מבטיחים למשתמש כלום)
            "highlight": hl_state.get(row["id"]),
            "status":   row["status"],
            # תוצאה נשלחת רק כשהמשתמש ביקש לראות (אחרת אין מה לדלוף למסך)
            **({"home_score": row["home_score"], "away_score": row["away_score"]}
               if scores and likely_over(row) else {}),
        })

    # מדד טריות: מתי הליגה רועננה לאחרונה. הפרונט משתמש בזה
    # כדי לרענן אוטומטית בלי לחיצה כשהנתונים מיושנים.
    stale = True
    if last_fetch:
        try:
            dt = datetime.fromisoformat(last_fetch)
            stale = (datetime.now(timezone.utc) - dt) > timedelta(hours=3)
        except Exception:
            stale = True

    return {"matches": matches, "count": len(matches),
            "stale": stale, "last_fetched": last_fetch}


@app.get("/matches/by_date/{date_il}")
def get_matches_by_date(request: Request, date_il: str, lang: str = "he",
                        scores: bool = False):
    """כל המשחקים מכל הליגות בתאריך נתון בשעון ישראל (YYYY-MM-DD),
    ממוינים לפי סדר הליגות ואז שעת פתיחה. קורא מה-DB בלבד —
    רענון נתונים נעשה בטאבי הליגות."""
    require_auth(request)
    try:
        day = datetime.fromisoformat(date_il).date()
    except ValueError:
        raise HTTPException(400, "פורמט תאריך: YYYY-MM-DD")

    # תאריך ישראלי אחד מכסה שני תאריכי UTC (ישראל מקדימה ב-2/3 שעות)
    d_prev = (day - timedelta(days=1)).isoformat()
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM matches WHERE date_utc IN (?, ?)",
        (d_prev, day.isoformat())).fetchall()
    # ליגה שנוספה עכשיו מתחילה בלי אף שורה, והנתונים מגיעים מהדפדפן —
    # כך שהיא לא תופיע כאן לעולם, ואף אחד לא "יזריע" אותה אלא אם נכנס
    # לטאב שלה. הלקוח מרענן ליגות ריקות ברקע.
    seeded = {r["league_key"] for r in
              conn.execute("SELECT DISTINCT league_key FROM matches").fetchall()}
    empty_leagues = [k for k, v in LEAGUES.items()
                     if v.get("source") == "sportsdb" and k not in seeded]
    hl_state = _highlight_states(conn, rows)
    conn.close()

    order = {k: i for i, k in enumerate(LEAGUES)}
    want = day.strftime("%d/%m/%Y")
    matches = []
    for row in rows:
        il = to_israel_time(row["date_utc"], row["time_utc"])
        if il["date"] != want:
            continue
        lk = row["league_key"]
        matches.append({
            "id":         row["id"],
            "home":       row["home_team"],
            "away":       row["away_team"],
            "home_name":  display_team(row["home_team"], _lang(lang)),
            "away_name":  display_team(row["away_team"], _lang(lang)),
            "home_key":   team_key(row["home_team"]),
            "away_key":   team_key(row["away_team"]),
            "date":       il["date"],
            "time":       il["time"],
            "weekday":    il["weekday"],
            "venue":      row["venue"] or "",
            "matchday":   row["matchday"],
            "league":     LEAGUES.get(lk, {}).get("name", lk),
            "league_key": lk,
            "is_over":    likely_over(row),
            "status":     row["status"],
            **({"home_score": row["home_score"], "away_score": row["away_score"]}
               if scores and likely_over(row) else {}),
            # הפתיחה עברה מזמן אבל לא מסומן כגמור — הדפדפן ירענן את הליגה
            "needs_refresh": not is_over(row["status"]) and kickoff_passed(row),
            "highlight": hl_state.get(row["id"]),
        })
    matches.sort(key=lambda m: (order.get(m["league_key"], 99), m["time"]))
    heb = ["שני", "שלישי", "רביעי", "חמישי", "שישי", "שבת", "ראשון"]
    return {"date": day.isoformat(), "weekday": heb[day.weekday()],
            "count": len(matches), "matches": matches,
            "empty_leagues": empty_leagues}


@app.post("/refresh/{league_key}")
def refresh_from_client(request: Request, league_key: str,
                        payload: dict = Body(...)):
    """Client-side refresh: הדפדפן שולף מ-TheSportsDB (שחסום מ-Render)
    ושולח את האירועים לכאן. Body: {"events": [...]}"""
    require_auth(request)
    league = LEAGUES.get(league_key)
    if not league:
        raise HTTPException(404, "ליגה לא נמצאה")
    if league["source"] != "sportsdb":
        raise HTTPException(400, "רענון client-side נתמך רק לליגות sportsdb")

    events = payload.get("events", [])
    if not isinstance(events, list):
        raise HTTPException(400, "פורמט לא תקין — צריך {\"events\": [...]}")

    conn = get_db()
    # purge סלקטיבי: רק משחקים עתידיים — היסטוריה שהסתיימה ושורות
    # הלוח הידני שורדות רענון. לאיפוס מלא (עונה חדשה): "hard": true.
    stored = _store_sportsdb_events(conn, league_key, events,
                                    purge=bool(payload.get("purge")),
                                    hard=bool(payload.get("hard")))
    conn.commit()
    conn.close()

    # הלוח הרשמי הידני גובר על מה שהדפדפן שלח (placeholder-ים וכו')
    if league_key in MANUAL_FIXTURES:
        apply_manual_fixtures(league_key)

    return {"ok": True, "received": len(events), "stored": stored}


# כמה זמן אחרי המשחק עוד סביר שיעלה תקציר — ולכן כמה זמן הרקע ממשיך
# לחפש, ובאיזו תדירות. בליגות האירופיות זה כמעט חוזה: משחק בשבת,
# תקציר עד אותו לילה. בישראל זה לוקח יותר (20.9.26).
HIGHLIGHT_WINDOW_HOURS = 48
_SLOW_LEAGUES = {"israel": 5 * 24}


def _highlight_window(league_key: str) -> timedelta:
    return timedelta(hours=_SLOW_LEAGUES.get(league_key, HIGHLIGHT_WINDOW_HOURS))


def _not_found_retry(row):
    """אחרי כמה זמן לחפש שוב כש"לא נמצא" — לפי גיל המשחק. גם משחק ישן נבדק
    שוב פעם בשבוע: תקלה זמנית (RSS נפל) לא "מקבעת" משחק בלי תקציר."""
    try:
        kick = datetime.fromisoformat(f"{row['date_utc']}T{row['time_utc']}+00:00")
    except Exception:
        return timedelta(minutes=30)
    match_age = datetime.now(timezone.utc) - kick
    # כל עוד התקציר עוד צפוי — בודקים תכופות. הגבול הזה הוא לפי ליגה:
    # יומיים באירופה, חמישה ימים בישראל
    if match_age < _highlight_window(row["league_key"]):
        return timedelta(minutes=30)
    if match_age < timedelta(days=7):
        return timedelta(hours=6)
    return timedelta(days=7)


def _mark_first_seen(conn, match_id, source_id, seen, published=None):
    """#10 מי העלה ראשון: רק הפעם הראשונה נשמרת (INSERT OR IGNORE)."""
    conn.execute("INSERT OR IGNORE INTO highlight_first_seen "
                 "(match_id, source_id, first_seen, published) VALUES (?,?,?,?)",
                 (match_id, source_id, seen, published))


def _source_highlights(row, source, free_only: bool = False) -> dict:
    """תקציר ממקור אחד למשחק: מהקאש, או חיפוש ושמירה בקאש.
    משותף ל-/highlights ולחיפוש-מראש ברקע."""
    match_id    = row["id"]
    source_id   = source["id"]
    channel_id  = source.get("channel_id", "")
    # צפייה בתוך האתר (#35): הנגן שלנו מכסה את הכותרת, את התמונה
    # הממוזערת ואת ההצעות של יוטיוב — שלושתן מסגירות את התוצאה. לפני
    # שהמגן הזה נבנה, כל מקור היה מסומן "אסור להטמיע".
    # ערוץ שחוסם הטמעה בכל זאת → הנגן מציג כפתור פתיחה ביוטיוב.
    allow_embed = EMBED_IN_APP and source.get("allow_embed", True)
    base = {"source_id": source_id, "name": source["name"], "allow_embed": allow_embed}

    if not channel_id:
        return {**base, "videos": [], "status": "no_channel"}

    conn = get_db()
    cached = conn.execute(
        "SELECT videos_json, found_at FROM highlight_cache WHERE match_id=? AND source_id=?",
        (match_id, source_id)
    ).fetchone()
    conn.close()

    had_videos = []
    if cached:
        videos = json.loads(cached["videos_json"])
        had_videos = videos if isinstance(videos, list) else []
        cache_age_ok = True
        try:
            age = datetime.now(timezone.utc) - datetime.fromisoformat(cached["found_at"])
        except Exception:
            age = None
        if not videos:
            # "לא נמצא" — ניסיון חוזר לפי גיל המשחק (30 דק' / 6 שעות / אף פעם)
            retry_after = _not_found_retry(row)
            if retry_after is not None and (age is None or age > retry_after):
                cache_age_ok = False
        elif not any(v.get("extended") for v in videos):
            # נמצא רק תקציר קצר — המלא עולה לרוב יום-יומיים אחרי.
            # מרעננים לכל היותר פעם ב-12 שעות, עד 3 ימים מהמציאה.
            if age is not None and timedelta(hours=12) < age < timedelta(days=3):
                cache_age_ok = False
        if cache_age_ok:
            return {**base, "videos": videos, "status": "cached"}

    # עדיפות לשאילתה מוכנה (שמות קצרים למועדונים), אחרת מתבנית המקור
    query = (source.get("query_override")
             or build_source_query(source, row["home_team"], row["away_team"]))
    videos = search_youtube(
        home=row["home_team"],
        away=row["away_team"],
        match_date=row["date_utc"],
        channel_id=channel_id,
        query=query,
        title_exclude=source.get("title_exclude"),
        title_include=source.get("title_include"),
        home_alt=to_hebrew_team(row["home_team"]),
        away_alt=to_hebrew_team(row["away_team"]),
        require_team=source.get("require_team_match", False),
        implicit_team=source.get("club_team"),
        headline=source.get("headline_titles", False),
        il_both=source.get("il_both_teams", False),
        date_in_title=source.get("title_date", False),
        free_only=free_only,
    )
    if videos is None:
        # שגיאת API / בלם יומי — לא שומרים בקאש, ינוסה שוב בהמשך
        return {**base, "videos": [], "status": "api_error"}

    # בדיקה חוזרת שלא מצאה כלום לא מוחקת את מה שכבר נמצא. הבדיקה הזו
    # מחפשת גרסה מורחבת, או מוודאת "לא נמצא" — ואין סיבה שתעלים תקציר
    # קיים. 19.9.26: ברייטון–ארסנל הציג תקציר בפיד, ובפתיחה נאמר
    # "עדיין לא הועלה ליוטיוב", כי הבדיקה החוזרת דרסה את הקאש בריק.
    if not videos and had_videos:
        print(f"[yt] keeping {len(had_videos)} cached video(s) for "
              f"{match_id}/{source_id} — recheck found none")
        return {**base, "videos": had_videos, "status": "cached"}

    now = datetime.now(timezone.utc).isoformat()
    conn = get_db()
    conn.execute("""
        INSERT OR REPLACE INTO highlight_cache
        (match_id, source_id, videos_json, found_at)
        VALUES (?,?,?,?)
    """, (match_id, source_id, json.dumps(videos), now))
    if videos:
        pubs = [v["published"] for v in videos if v.get("published")]
        _mark_first_seen(conn, match_id, source_id, now, min(pubs) if pubs else None)
    conn.commit()
    conn.close()
    return {**base, "videos": videos, "status": "found" if videos else "not_found"}


# ── חיפוש מראש ברקע ────────────────────────────────────
# משחקים שהסתיימו ב-48 השעות האחרונות ועוד אין להם קאש — השרת מחפש לבד.
# התקציר מוכן לפני שמישהו פותח, והעלות תלויה במספר המשחקים — לא במשתמשים.
def _web_link(row, w):
    """קישור ישיר לכתבת התקציר באתר (ספורט 1/5) — מהקאש, או מעמודי האתר
    ושמירה בקאש. משותף ל-/highlights ולחיפוש-מראש ברקע."""
    match_id  = row["id"]
    cache_key = f"web_{w['name']}"
    conn = get_db()
    cached = conn.execute(
        "SELECT videos_json FROM highlight_cache WHERE match_id=? AND source_id=?",
        (match_id, cache_key)
    ).fetchone()
    conn.close()
    if cached:
        return json.loads(cached["videos_json"])["url"]

    # לחיפוש ביוטיוב יש גבול תאריך משני הצדדים; לאתרים אין שום דרך לדעת
    # על איזה מפגש הכתבה מדברת — התנאי היחיד הוא ששתי הקבוצות מופיעות
    # בטקסט, וזה בדיוק מה שחוזר במפגש השני של אותן קבוצות. לכן מחפשים
    # רק בחלון שבו הכתבה עדיין על העמוד, ולא אחריו: פתיחת משחק ממחזור 5
    # בפברואר הייתה מחזירה את הכתבה של מחזור 22, עם התוצאה בכותרת.
    try:
        age = (datetime.now(timezone.utc).date()
               - datetime.fromisoformat(row["date_utc"]).date()).days
    except (ValueError, TypeError):
        age = 0
    if age > HIGHLIGHT_MAX_DAYS:
        return None

    # 1. עמודי האתר עצמו (VOD/ליגה) — קישור ישיר, בלי מנוע חיפוש
    url = None
    if w.get("scrape_pages"):
        url = find_web_highlight(w["scrape_pages"], w["link_pattern"],
                                 _he_names(row["home_team"]),
                                 _he_names(row["away_team"]),
                                 base=w.get("base", ""))
    # 2. Google CSE — רק אם הוגדר מפתח
    if not url:
        wq = w["query"].format(home=to_hebrew_team(row["home_team"]),
                               away=to_hebrew_team(row["away_team"]))
        url = resolve_web_link(wq, w["domain"])
    if url:
        # קאש רק לקישור ישיר — כישלון ינוסה שוב בפתיחה הבאה
        now = datetime.now(timezone.utc).isoformat()
        conn = get_db()
        conn.execute("""
            INSERT OR REPLACE INTO highlight_cache
            (match_id, source_id, videos_json, found_at)
            VALUES (?,?,?,?)
        """, (match_id, cache_key, json.dumps({"url": url}), now))
        _mark_first_seen(conn, match_id, cache_key, now)
        conn.commit()
        conn.close()
    return url


# צפייה בתוך האתר. EMBED_IN_APP=0 ב-Render מחזיר את כולם לפתיחה ביוטיוב,
# בלי לחכות ל-deploy — נתיב נסיגה אם יתגלה דליפה שלא נצפתה.
EMBED_IN_APP = os.environ.get("EMBED_IN_APP", "1") != "0"
# ערוצים שמעלים תקצירים בלי רישיון. הם מקדימים את הרשמיים, ולכן
# דלוקים (החלטת הבעלים, 26.9.26). הדגל קיים כדי ש-UNOFFICIAL_SOURCES=0
# יכבה אותם מיד — זו החשיפה המשפטית הממשית היחידה של האתר, ואם יגיע
# מכתב, הכיבוי צריך להיות משתנה סביבה ולא deploy.
UNOFFICIAL_SOURCES = os.environ.get("UNOFFICIAL_SOURCES", "1") != "0"
# מופע פרטי: רשימת כתובות שמותר להן להיכנס. ריק = פתוח (האתר הציבורי).
ALLOWED_EMAILS = {e.strip().lower()
                  for e in os.environ.get("ALLOWED_EMAILS", "").split(",") if e.strip()}

PREFETCH_EVERY_MIN   = 30
PREFETCH_MAX_MATCHES = 20
# #10 מי מעלה ראשון: בליגות האלה גם "לא נמצא" נבדק שוב בכל סבב (לפי
# _not_found_retry — כל 30 דק' ביומיים הראשונים), כדי למדוד מתי כל מקור עלה
TIMING_LEAGUES = {"israel"}
# תקציב מכסה יומי לבדיקות רקע. מעליו הרקע עובד רק מהמקור החינמי, והשאר
# נשמר למשחקים שמשתמשים פותחים בפועל (הבלם הכללי הוא YT_DAILY_BRAKE)
PREFETCH_UNIT_BUDGET = 1500


def prefetch_highlights_once() -> int:
    widest = max([_highlight_window(k) for k in LEAGUES] or [timedelta(hours=48)])
    since = (datetime.now(timezone.utc) - widest).strftime("%Y-%m-%d")
    conn = get_db()
    rows = conn.execute("SELECT * FROM matches WHERE date_utc >= ?", (since,)).fetchall()
    # (משחק, מקור) → האם נמצא משהו
    have = {(r["match_id"], r["source_id"]): (r["videos_json"] not in ("[]", ""),
                                             r["found_at"])
            for r in conn.execute("SELECT match_id, source_id, videos_json, found_at "
                                  "FROM highlight_cache").fetchall()}
    conn.close()

    # סדר הבדיקה: מי שלא נבדק מעולם קודם, ואחריו מי שנבדק לפני הכי הרבה
    # זמן. הלולאה נעצרת אחרי PREFETCH_MAX_MATCHES, והשליפה היא בלי
    # ORDER BY — כלומר בסדר הטבלה. ברוב המצבים זה מסתדר מעצמו, כי משחק
    # שנבדק מקבל קאש טרי ויוצא מהתור; אבל כשהתוקף פג לכולם יחד (שבת
    # עמוסה, 17 ליגות), הראשונים בטבלה תפסו את כל המקומות שוב ושוב.
    last_checked = {}
    for (mid, _sid), (_found, at) in have.items():
        if at and at > last_checked.get(mid, ""):
            last_checked[mid] = at
    rows = sorted(rows, key=lambda r: last_checked.get(r["id"], ""))

    done = 0
    for row in rows:
        if done >= PREFETCH_MAX_MATCHES:
            break
        window = _highlight_window(row["league_key"])
        if not likely_over(row) or kickoff_passed(row, hours=window.total_seconds() / 3600):
            continue
        recheck = row["league_key"] in TIMING_LEAGUES

        def needs_check(source):
            key = (row["id"], source["id"])
            if key not in have:
                return True
            found, at = have[key]
            if found:
                return False
            if recheck:        # מדידת "מי מעלה ראשון" — בכל סבב
                return True
            # "לא נמצא" שפג תוקפו. בלי זה, מקור שהוחזר ריק פעם אחת לא
            # נבדק שוב לעולם ברקע: משחק פרמייר ליג נבדק אחרי המשחק,
            # התקציר עלה בלילה, ואף אחד לא חזר אליו (20.9.26)
            expiry = _not_found_retry(row)
            if expiry is None:
                return False
            try:
                return datetime.now(timezone.utc) - datetime.fromisoformat(at) > expiry
            except (ValueError, TypeError):
                return True

        todo = [s for s in get_sources_for_match(row)
                if s.get("channel_id") and needs_check(s)]
        # סיבוב מוקדם בגביע מביא עשרות משחקי חובבים. בדיקה בתשלום עליהם
        # הייתה בולעת את תקציב הרקע שהליגות צריכות — ברקע הם חינם בלבד
        # (משחק שמשתמש פותח בפועל עדיין נבדק במלוא המקורות).
        is_cup = LEAGUES.get(row["league_key"], {}).get("cup")
        paid_ok = _yt_units_today() < PREFETCH_UNIT_BUDGET and not is_cup
        # אתרים (ספורט 1/5): בלי מכסה — נבדקים בכל סבב עד שנמצא קישור
        webs = [w for w in LEAGUES.get(row["league_key"], {}).get("web_sources", [])
                if (row["id"], f"web_{w['name']}") not in have]
        if not todo and not webs:
            continue
        for s in todo:
            # בדיקה חוזרת (מעקב "מי מעלה ראשון") — תמיד חינם בלבד;
            # בדיקה ראשונה למקור — בתשלום רק בתוך תקציב הרקע
            first_time = (row["id"], s["id"]) not in have
            _source_highlights(row, s, free_only=not (first_time and paid_ok))
        for w in webs:
            _web_link(row, w)
        done += 1
    print(f"[prefetch] searched {done} match(es)")
    return done


def _prefetch_loop():
    time.sleep(60)   # לתת לשרת לעלות לפני הסבב הראשון
    while True:
        try:
            prefetch_highlights_once()
        except Exception as ex:
            print(f"[prefetch] {ex}")
        time.sleep(PREFETCH_EVERY_MIN * 60)


@app.on_event("startup")
def _start_prefetch():
    # רק כשיש מפתח יוטיוב (פרודקשן). PREFETCH=0 מכבה.
    if YOUTUBE_API_KEY and os.environ.get("PREFETCH", "1") == "1":
        threading.Thread(target=_prefetch_loop, daemon=True).start()


# גרסת הלקוח. הנגן המוטמע והמגן שלו נוספו ב-2: לקוח ישן לא יודע
# לכסות את הכותרת ואת התמונה הממוזערת, ולכן הוא לא מקבל הרשאה להטמיע.
# ה-service worker מגיש את הדף מהקאש, כך שגרסה חדשה מגיעה רק בפתיחה
# הבאה — ובלי השער הזה השרת התיר הטמעה לקוד שאין לו מגן (22.9.26).
CLIENT_EMBED_VERSION = 2


@app.get("/highlights/{match_id}")
def get_highlights(request: Request, match_id: str, lang: str = "he", client: int = 1):
    require_auth(request)
    conn = get_db()
    row  = conn.execute("SELECT * FROM matches WHERE id=?", (match_id,)).fetchone()
    conn.close()

    if not row:
        raise HTTPException(404, "משחק לא נמצא")

    if not likely_over(row):
        league_cfg = LEAGUES.get(row["league_key"], {})

        # סטטוס מיושן? אם שעת הפתיחה עברה מזמן, המשחק כנראה נגמר במציאות
        # וה-DB פשוט לא רוענן. בליגות football-data (נגיש מ-Render) —
        # מרעננים אוטומטית מצד השרת ובודקים שוב.
        if kickoff_passed(row) and not fetched_recently(row):
            if league_cfg.get("source") == "football-data":
                try:
                    fetch_football_data(row["league_key"])
                except Exception as ex:
                    print(f"[auto-refresh] {row['league_key']}: {ex}")
                conn = get_db()
                row = conn.execute("SELECT * FROM matches WHERE id=?",
                                   (match_id,)).fetchone()
                conn.close()

        if not likely_over(row):
            if kickoff_passed(row):
                # סטטוס מיושן, ו-sportsdb חסום מצד השרת: הדפדפן מרענן את
                # הליגה בעצמו (needs_refresh) ופותח שוב — מכל עמוד, כולל "לפי יום"
                return {"available": False, "needs_refresh": True,
                        "league_key": row["league_key"], "reason_code": "stale",
                        "reason": "עדיין לא התקבל עדכון שהמשחק הסתיים — "
                                  "נסה שוב בעוד כמה דקות",
                        "sources": []}
            return {"available": False, "reason_code": "not_over",
                    "reason": "המשחק עדיין לא נגמר",
                    "sources": []}

    sources = get_sources_for_match(row)
    results = [_source_highlights(row, source) for source in sources]
    if client < CLIENT_EMBED_VERSION:
        for r in results:
            r["allow_embed"] = False

    # קישורי אתר (same-day): השרת מחלץ את הכתבה הישירה ושומר בקאש
    league = LEAGUES.get(row["league_key"], {})
    web_links = []
    for w in league.get("web_sources", []):
        url = _web_link(row, w)
        # אין קישור ישיר — אין כפתור (עמוד תוצאות חיפוש = ספוילרים בכותרות)
        if url:
            web_links.append({"name": w["name"], "url": url})

    # שם הקבוצה לצד ערוץ מועדון — הפרונט מציג אותו בשפת המשתמש
    club_of = {s["id"]: s.get("club_team") for s in sources}
    for r in results:
        r["club_team"] = club_of.get(r["source_id"])
        r["club_name"] = display_team(r["club_team"], _lang(lang)) if r["club_team"] else None

    return {
        "available": True,
        "match":     f"{row['home_team']} vs {row['away_team']}",
        "sources":   results,
        "web_links": web_links,
    }


@app.delete("/cache/{match_id}")
def clear_cache(request: Request, match_id: str):
    """Clear highlight cache for a match — forces re-search on next request."""
    require_auth(request)
    # מגן מכסה: מוחק רק קאש בן 15 דקות ומעלה — לחיצות חוזרות (או כמה
    # חברים על אותו משחק) לא מריצות חיפוש חדש בכל פעם
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=15)).isoformat()
    conn = get_db()
    # רק שורות ריקות: "חפש שוב" אמור להפוך "לא נמצא" לניסיון חדש, לא
    # למחוק מציאה. המגן ב-_source_highlights נשען על מה ששמור בקאש —
    # ומחיקה כאן עקפה אותו, כך שחיפוש שנפל על המכסה החזיר "לא הצלחנו
    # לבדוק" במקום התקציר שהיה על המסך שנייה קודם.
    conn.execute("DELETE FROM highlight_cache WHERE match_id=? AND found_at<? "
                 "AND videos_json IN ('[]', '')",
                 (match_id, cutoff))
    conn.commit()
    conn.close()
    return {"ok": True, "match_id": match_id}


@app.delete("/cache")
def clear_all_cache(request: Request):
    """Clear ALL highlight cache — useful when debugging."""
    require_admin(request)
    conn = get_db()
    conn.execute("DELETE FROM highlight_cache")
    conn.commit()
    conn.close()
    return {"ok": True}


@app.get("/clubs/{league_key}")
def get_clubs(request: Request, league_key: str):
    require_admin(request)
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM clubs WHERE league_key=? ORDER BY tier, name", (league_key,)
    ).fetchall()
    conn.close()
    return {"clubs": [dict(r) for r in rows]}


@app.put("/clubs/{club_id}/channel")
def update_club_channel(request: Request, club_id: str, channel_id: str):
    require_admin(request)
    conn = get_db()
    conn.execute("UPDATE clubs SET yt_channel_id=? WHERE id=?", (channel_id, club_id))
    conn.commit()
    conn.close()
    return {"ok": True}


@app.get("/debug/db")
def debug_db(request: Request):
    """Quick debug endpoint — shows counts per league."""
    require_admin(request)
    conn = get_db()
    leagues = conn.execute(
        "SELECT league_key, COUNT(*) as c, "
        "SUM(CASE WHEN status='FINISHED' THEN 1 ELSE 0 END) as finished, "
        "MAX(fetched_at) as last_fetch "
        "FROM matches GROUP BY league_key"
    ).fetchall()
    cache_count = conn.execute("SELECT COUNT(*) as c FROM highlight_cache").fetchone()["c"]
    conn.close()
    return {
        "leagues": [dict(r) for r in leagues],
        "cache_entries": cache_count,
    }


@app.get("/debug/fd")
def debug_fd(request: Request):
    """אבחון football-data — מציג מה ה-API באמת מחזיר עבור הפרמייר ליג."""
    require_admin(request)
    league = LEAGUES["premier"]
    try:
        r = requests.get(
            f"https://api.football-data.org/v4/competitions/{league['fd_code']}/matches",
            headers={"X-Auth-Token": FOOTBALL_DATA_KEY},
            params={"season": league["fd_season"]},
            timeout=15
        )
        body = r.json()
        matches = body.get("matches", [])
        return {
            "http_status":     r.status_code,
            "season_param":    league["fd_season"],
            "key_configured":  bool(FOOTBALL_DATA_KEY),
            "matches_count":   len(matches),
            "first_match_utc": matches[0]["utcDate"] if matches else None,
            "api_message":     body.get("message") or body.get("error"),
        }
    except Exception as ex:
        return {"exception": str(ex)}


@app.get("/debug/pl_teams")
def debug_pl_teams(request: Request):
    """כל קבוצות הפרמייר מהלוח הנוכחי + סטטוס ערוץ יוטיוב לכל אחת."""
    require_admin(request)
    conn = get_db()
    teams = {}
    rows = conn.execute(
        "SELECT home_team as name, home_team_id as tid FROM matches WHERE league_key='premier' "
        "UNION SELECT away_team, away_team_id FROM matches WHERE league_key='premier'"
    ).fetchall()
    for r in rows:
        if r["tid"]:
            teams[r["tid"]] = {"fd_team_id": r["tid"], "team_name": r["name"],
                               "yt_channel_id": ""}
    for c in conn.execute("SELECT * FROM clubs WHERE league_key='premier'").fetchall():
        if c["fd_team_id"] in teams:
            teams[c["fd_team_id"]]["yt_channel_id"] = c["yt_channel_id"] or ""
    conn.close()
    result = sorted(teams.values(), key=lambda t: (t["yt_channel_id"] != "", t["team_name"]))
    return {"teams": result,
            "missing_channel": sum(1 for t in result if not t["yt_channel_id"]),
            "howto": "לכל קבוצה חסרה: /admin/set_channel?fd_team_id=<ID>&url=<כתובת הערוץ ביוטיוב>"}


@app.get("/admin/set_channel")
def admin_set_channel(request: Request, fd_team_id: str, url: str, name: str = ""):
    """מגדיר ערוץ יוטיוב למועדון, מהדפדפן.
    url יכול להיות כל צורה: youtube.com/@Arsenal, @Arsenal,
    או youtube.com/channel/UC... — handle נפתר אוטומטית דרך YouTube API."""
    require_admin(request)
    url = url.strip()

    channel_id = ""
    channel_title = ""
    if "/channel/" in url:
        channel_id = url.split("/channel/")[1].split("/")[0].split("?")[0]
    else:
        # חילוץ ה-handle ופתרון דרך ה-API (עולה 1 unit בלבד)
        handle = url.split("/")[-1] if "/" in url else url
        handle = handle.split("?")[0].lstrip("@")
        if not handle:
            raise HTTPException(400, "לא הצלחתי לחלץ handle מהכתובת")
        try:
            r = requests.get(
                "https://www.googleapis.com/youtube/v3/channels",
                params={"key": YOUTUBE_API_KEY, "forHandle": handle,
                        "part": "id,snippet"},
                timeout=10
            ).json()
            items = r.get("items", [])
            if not items:
                raise HTTPException(404, f"YouTube לא מצא ערוץ עבור @{handle}")
            channel_id = items[0]["id"]
            channel_title = items[0]["snippet"]["title"]
        except HTTPException:
            raise
        except Exception as ex:
            raise HTTPException(502, f"שגיאה מול YouTube API: {ex}")

    # upsert לטבלת clubs
    conn = get_db()
    existing = conn.execute(
        "SELECT * FROM clubs WHERE fd_team_id=? AND league_key='premier'",
        (fd_team_id,)
    ).fetchone()
    team_row = conn.execute(
        "SELECT home_team as n FROM matches WHERE league_key='premier' AND home_team_id=? LIMIT 1",
        (fd_team_id,)
    ).fetchone()
    team_name = name or (team_row["n"] if team_row else channel_title or fd_team_id)

    if existing:
        conn.execute("UPDATE clubs SET yt_channel_id=? WHERE id=?",
                     (channel_id, existing["id"]))
        club_id = existing["id"]
    else:
        club_id = f"PL-fd{fd_team_id}"
        conn.execute("""
            INSERT OR REPLACE INTO clubs
            (id, name, short_name, league_key, tier, yt_channel_id, fd_team_id)
            VALUES (?,?,?,?,2,?,?)
        """, (club_id, team_name, team_name, "premier", channel_id, fd_team_id))
    conn.commit()
    conn.close()

    return {"ok": True, "club_id": club_id, "team": team_name,
            "channel_id": channel_id, "channel_title": channel_title,
            "note": "זמני עד deploy הבא! בסיום — שלח את /debug/pl_teams לצ'אט כדי לקבע בקוד"}


@app.get("/debug/highlights")
def debug_highlights(request: Request, q: str):
    """אבחון תקצירים: מציג את הכותרות הגולמיות מכל מקור ולמה כל אחת
    עברה/נפסלה. שימוש: /debug/highlights?q=Chelsea (שם קבוצה, חלקי מספיק).
    זהירות: כל מקור = חיפוש אמיתי = 100 יחידות quota."""
    require_admin(request)
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM matches WHERE (home_team LIKE ? OR away_team LIKE ?) "
        "AND status IN ('FINISHED','FT','AET','PEN') "
        "ORDER BY date_utc DESC LIMIT 1",
        (f"%{q}%", f"%{q}%")
    ).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, f"לא נמצא משחק שנגמר עבור '{q}'")

    home, away = row["home_team"], row["away_team"]
    report = {"match": f"{home} vs {away}", "date": row["date_utc"], "sources": []}

    for source in get_sources_for_match(row):
        channel_id = source.get("channel_id", "")
        entry = {"source": source["name"], "channel_id": channel_id}
        if not channel_id:
            entry["verdict"] = "אין channel_id מוגדר"
            report["sources"].append(entry)
            continue

        query = (source.get("query_override")
                 or build_source_query(source, home, away))
        entry["query"] = query

        try:
            resp = requests.get(
                "https://www.googleapis.com/youtube/v3/search",
                params={"key": YOUTUBE_API_KEY, "channelId": channel_id,
                        "part": "snippet", "order": "relevance",
                        "maxResults": 15, "type": "video", "q": query,
                        "publishedAfter": f"{row['date_utc']}T00:00:00Z"},
                timeout=10
            ).json()
        except Exception as ex:
            entry["error"] = str(ex)
            report["sources"].append(entry)
            continue

        if "error" in resp:
            # כאן יתגלה quotaExceeded אם שרפנו את המכסה היומית
            entry["youtube_error"] = resp["error"].get("message", str(resp["error"]))
            report["sources"].append(entry)
            continue

        titles = []
        excl = source.get("title_exclude") or []
        for item in resp.get("items", []):
            title = item["snippet"]["title"]
            tl = title.lower()
            if any(x.lower() in tl for x in excl):
                verdict = "נפסל: סינון מקור"
            elif not is_match_highlight(title, home, away,
                                         to_hebrew_team(home), to_hebrew_team(away),
                                         source.get("require_team_match", False)):
                verdict = "נפסל: לא זוהה כתקציר"
            else:
                verdict = "עבר ✓"
            titles.append({"title": clean_title_for_display(title),
                           "verdict": verdict})
        entry["results"] = titles
        entry["total"] = len(titles)
        report["sources"].append(entry)

    return report


@app.get("/debug/channels")
def debug_channels(request: Request):
    """אימות ערוצים: שואל את YouTube (channels.list, יחידת quota אחת)
    מה השם האמיתי של כל channel_id מקובע — מועדוני פרמייר + מקורות הליגות.
    ID שגוי יתגלה מיד: שם לא קשור, או 'לא קיים'."""
    require_admin(request)

    # אוספים את כל ה-IDs: מועדונים + מקורות ליגה
    entries = []   # (label, channel_id)
    conn = get_db()
    for c in conn.execute("SELECT name, yt_channel_id FROM clubs "
                          "WHERE yt_channel_id != ''").fetchall():
        entries.append((f"club: {c['name']}", c["yt_channel_id"]))
    conn.close()
    for lk, league in LEAGUES.items():
        for s in league.get("sources", []):
            if s.get("channel_id"):
                entries.append((f"{lk}: {s['name']}", s["channel_id"]))

    ids = list({cid for _, cid in entries})
    titles = {}
    try:
        # channels.list תומך עד 50 IDs בקריאה אחת = 1 יחידת quota
        for i in range(0, len(ids), 50):
            batch = ids[i:i+50]
            resp = requests.get(
                "https://www.googleapis.com/youtube/v3/channels",
                params={"key": YOUTUBE_API_KEY, "part": "snippet",
                        "id": ",".join(batch), "maxResults": 50},
                timeout=10
            ).json()
            if "error" in resp:
                return {"error": resp["error"].get("message")}
            for item in resp.get("items", []):
                titles[item["id"]] = item["snippet"]["title"]
    except Exception as ex:
        return {"error": str(ex)}

    report = []
    for label, cid in entries:
        report.append({
            "who": label,
            "channel_id": cid,
            "youtube_says": titles.get(cid, "❌ ערוץ לא קיים / ID שגוי"),
        })
    return {"channels": report,
            "note": "השווה בעין: who מול youtube_says. אי-התאמה = ID שגוי — "
                    "תקן עם /admin/set_channel ושלח לי את pl_teams לקיבוע."}


@app.get("/debug/match")
def debug_match(request: Request, q: str):
    """השורה הגולמית של משחק מה-DB — סטטוס, תאריך, מזהי קבוצות, מקורות
    התקצירים שהמשחק מקבל, ומה שמור בקאש לכל מקור (אבחון "ערוץ לא נכון")."""
    require_admin(request)
    conn = get_db()
    # q יכול להיות שתי קבוצות ("Tottenham Everton"); מציגים קודם משחקים
    # שכבר שוחקו — הם אלה שיש להם תקצירים לאבחן
    words = [w for w in q.split() if w][:3]
    where = " AND ".join(["(home_team LIKE ? OR away_team LIKE ?)"] * len(words)) or "1=1"
    params = [p for w in words for p in (f"%{w}%", f"%{w}%")]
    today = _now().strftime("%Y-%m-%d")
    rows = conn.execute(
        f"SELECT * FROM matches WHERE {where} "
        "ORDER BY (date_utc <= ?) DESC, CASE WHEN date_utc <= ? THEN date_utc END DESC, "
        "date_utc ASC LIMIT 5", (*params, today, today)
    ).fetchall()
    out = []
    for r in rows:
        d = {k: r[k] for k in ("id", "league_key", "home_team", "away_team", "home_team_id",
                               "away_team_id", "date_utc", "time_utc", "matchday", "status",
                               "fetched_at")}
        clubs = conn.execute("SELECT fd_team_id, name, short_name, yt_channel_id FROM clubs "
                             "WHERE fd_team_id IN (?, ?)",
                             (r["home_team_id"], r["away_team_id"])).fetchall()
        d["clubs_by_team_id"] = [dict(c) for c in clubs]
        d["cache"] = [{"source_id": c["source_id"], "found_at": c["found_at"],
                       "videos": c["videos_json"][:300]}
                      for c in conn.execute("SELECT source_id, found_at, videos_json FROM highlight_cache "
                                            "WHERE match_id=?", (r["id"],)).fetchall()]
        out.append(d)
    conn.close()
    for d, r in zip(out, rows):
        d["sources"] = [{"id": s["id"], "name": s["name"], "channel_id": s.get("channel_id")}
                        for s in get_sources_for_match(r)]
        # החיווי בפיד מול מה שהחלון באמת ימצא. פער ביניהם = שורות קאש
        # תחת מזהה מקור שהמשחק כבר לא משתמש בו (19.9.26: הפיד הבטיח
        # תקציר לטוטנהאם–אסטון וילה, והחלון אמר "עדיין לא עלה")
        live = {c["source_id"] for c in d["cache"]
                if c["videos"] not in ("[]", "")}
        mine = {x["id"] for x in d["sources"]}
        d["badge"] = {"feed_says": _highlight_states(get_db(), [r]).get(r["id"]),
                      "cache_with_videos": sorted(live),
                      "orphan_rows": sorted(live - mine),
                      "usable_now": sorted(live & mine)}
    return {"matches": out}


@app.get("/admin/resolve_channel")
def admin_resolve_channel(request: Request, url: str):
    """פותר handle של יוטיוב ל-channel ID, בלי לכתוב כלום.
    שימוש: /admin/resolve_channel?url=@sport1sport2"""
    require_admin(request)
    url = url.strip().rstrip("/")   # סלאש בסוף שבר את חילוץ ה-handle
    if "/channel/" in url:
        cid = url.split("/channel/")[1].split("/")[0].split("?")[0]
        return {"channel_id": cid, "note": "חולץ ישירות מהכתובת"}
    handle = url.split("/")[-1] if "/" in url else url
    handle = handle.split("?")[0].lstrip("@")
    if not handle:
        raise HTTPException(400, "לא הצלחתי לחלץ handle מהכתובת")
    r = requests.get(
        "https://www.googleapis.com/youtube/v3/channels",
        params={"key": YOUTUBE_API_KEY, "forHandle": handle,
                "part": "id,snippet"},
        timeout=10
    ).json()
    items = r.get("items", [])
    if not items:
        raise HTTPException(404, f"YouTube לא מצא ערוץ עבור @{handle}")
    return {"channel_id": items[0]["id"],
            "channel_title": items[0]["snippet"]["title"]}


@app.get("/debug/weblink")
def debug_weblink(request: Request, q: str, domain: str):
    """אבחון קישורי אתר: מציג מה Google CSE באמת מחזיר.
    שימוש: /debug/weblink?q=תקציר מכבי חיפה&domain=sport1.maariv.co.il"""
    require_admin(request)
    report = {
        "google_key_configured": bool(GOOGLE_SEARCH_KEY),
        "cse_id_configured":     bool(GOOGLE_CSE_ID),
        "cse_id_looks_valid":    ":" in GOOGLE_CSE_ID or len(GOOGLE_CSE_ID) >= 10,
    }
    if GOOGLE_SEARCH_KEY and GOOGLE_CSE_ID:
        try:
            r = requests.get(
                "https://www.googleapis.com/customsearch/v1",
                params={"key": GOOGLE_SEARCH_KEY, "cx": GOOGLE_CSE_ID,
                        "q": q, "siteSearch": domain,
                        "siteSearchFilter": "i", "num": 3},
                timeout=8,
            )
            body = r.json()
            report["cse_http_status"] = r.status_code
            report["cse_error"] = (body.get("error") or {}).get("message")
            items = body.get("items", [])
            report["cse_items_count"] = len(items)
            report["cse_first_links"] = [i.get("link") for i in items[:3]]
        except Exception as ex:
            report["cse_exception"] = str(ex)
    return report


@app.get("/debug/vodscrape")
def debug_vodscrape(request: Request, home: str = "מכבי חיפה", away: str = "הפועל רמת גן"):
    """אבחון סקרייפר ספורט 1: מה העמוד מחזיר והאם נמצאה התאמה."""
    require_admin(request)
    report = {"home_variants": he_team_variants(home),
              "away_variants": he_team_variants(away)}
    try:
        r = requests.get(
            "https://sport1.maariv.co.il/vod/",
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
            timeout=8,
        )
        report["http_status"] = r.status_code
        html = r.text
        report["html_length"] = len(html)
        anchors = []
        for m in re.finditer(r"<a[^>]+href=['\"]([^'\"]*?/video/\d+[^'\"]*)['\"][^>]*>(.*?)</a>",
                             html, re.S):
            text = re.sub(r"<[^>]+>", " ", m.group(2)).strip()
            anchors.append({"href": m.group(1)[:100], "text": text[:80]})
        report["video_anchors_found"] = len(anchors)
        report["sample"] = anchors[:6]
        # אולי הדף נבנה ב-JS והנתונים חיים ב-JSON מוטמע — סורקים גולמי
        raw_refs = re.findall(r"/video/\d+", html)
        report["raw_video_refs"] = len(raw_refs)
        contexts = []
        for m in list(re.finditer(r"/video/\d+", html))[:4]:
            s = max(0, m.start() - 150)
            contexts.append(html[s:m.end() + 20].replace("\n", " ")[-170:])
        report["raw_contexts"] = contexts
        report["matched_url"] = scrape_sport1_vod(home, away)
    except Exception as ex:
        report["exception"] = str(ex)
    return report


# Serve frontend (מוגן בסיסמה — מציג דף כניסה אם אין cookie)
# ── Auth endpoints ─────────────────────────────────────

# ── הגבלת קצב ──────────────────────────────────────────
# עד כה היה בלם רק על סיסמה שגויה ועל שליחת קוד חוזרת לאותו מייל.
# ההרשמה עצמה הייתה פתוחה לחלוטין: בוט יכול היה ליצור אלפי חשבונות,
# למלא את ה-DB ולהציף את הבעלים בהתראות — ובכל בקשת קוד גם לשלוח מייל
# אמיתי דרך Brevo, כלומר לשרוף מכסה ומוניטין שליחה.
REGISTER_PER_IP_HOUR = int(os.environ.get("REGISTER_PER_IP_HOUR", "3"))
REGISTER_PER_HOUR    = int(os.environ.get("REGISTER_PER_HOUR", "60"))
_rate_hits: dict = {}
_RATE_LOCK = threading.Lock()


def _client_ip(request: Request) -> str:
    """מאחורי ה-proxy של Render, הכתובת האמיתית ב-X-Forwarded-For."""
    fwd = request.headers.get("x-forwarded-for", "")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "?"


def _rate_limit(key: str, limit: int, window_sec: int = 3600) -> None:
    now = time.time()
    with _RATE_LOCK:
        hits = [t for t in _rate_hits.get(key, []) if now - t < window_sec]
        if len(hits) >= limit:
            raise HTTPException(429, "יותר מדי בקשות — נסה שוב בעוד שעה")
        hits.append(now)
        _rate_hits[key] = hits
        if len(_rate_hits) > 5000:      # לא נותנים למילון לגדול לנצח
            for k in [k for k, v in _rate_hits.items()
                      if not any(now - t < window_sec for t in v)]:
                _rate_hits.pop(k, None)


def _guard_signup(request: Request) -> None:
    """גם לפי כתובת וגם סך הכול: האחת עוצרת מי שמנסה שוב ושוב, השנייה
    היא רשת ביטחון מפני הצפה מכמה כתובות."""
    _rate_limit(f"signup:{_client_ip(request)}", REGISTER_PER_IP_HOUR)
    _rate_limit("signup:*", REGISTER_PER_HOUR)


def _email_from(payload) -> str:
    email = str(payload.get("email") or "").strip().lower()
    if len(email) > 200 or not EMAIL_RE.match(email):
        raise HTTPException(400, "כתובת מייל לא תקינה")
    # ALLOWED_EMAILS: מופע פרטי. חוסם גם כניסה ולא רק הרשמה — שתי
    # הכתובות חולקות את אותו DB, ובלי זה כל משתמש של האתר הציבורי היה
    # נכנס לכתובת הפרטית עם הסיסמה הקיימת שלו.
    if ALLOWED_EMAILS and email not in ALLOWED_EMAILS:
        raise HTTPException(403, "האתר הזה סגור")
    return email


BLOCKED_MSG = "אין גישה לחשבון הזה"


def _start_session(conn, email: str, now, method: str) -> str:
    """session חדש + מונה כניסות + אירוע login (method: code / password)."""
    token = secrets.token_urlsafe(32)
    conn.execute("INSERT INTO sessions (token_hash, email, created_at, expires_at) VALUES (?,?,?,?)",
                 (_sha(token), email, now.isoformat(),
                  (now + timedelta(days=SESSION_DAYS)).isoformat()))
    conn.execute("UPDATE users SET last_login=?, login_count=COALESCE(login_count,0)+1 WHERE email=?",
                 (now.isoformat(), email))
    conn.execute("INSERT INTO events (email, ts, type, detail) VALUES (?,?,'login',?)",
                 (email, now.isoformat(), method))
    return token


def _session_response(token: str, body: dict):
    resp = JSONResponse(body)
    resp.set_cookie("sf_session", token, max_age=SESSION_DAYS * 24 * 3600,
                    httponly=True, samesite="lax", secure=bool(os.environ.get("RENDER")))
    return resp


@app.post("/auth/request_code")
def auth_request_code(request: Request, payload: dict = Body(...)):
    """קוד בן 6 ספרות למייל: כניסה ראשונה (הרשמה), שכחתי סיסמה, או כניסה בלי
    סיסמה. בלי אישור מנהל — המשתמש נוצר כשהקוד מאומת."""
    email = _email_from(payload)
    now = _now()
    conn = get_db()
    user = conn.execute("SELECT status FROM users WHERE email=?", (email,)).fetchone()
    if user and user["status"] == "blocked":
        conn.close()
        raise HTTPException(403, BLOCKED_MSG)

    row = conn.execute("SELECT sent_at FROM login_codes WHERE email=?", (email,)).fetchone()
    if row:
        try:
            if (now - datetime.fromisoformat(row["sent_at"])).total_seconds() < CODE_RESEND_SEC:
                conn.close()
                return {"status": "code_sent"}   # נשלח לפני פחות מדקה — משתמשים בו
        except Exception:
            pass
    # מכאן והלאה נשלח מייל אמיתי דרך Brevo — כלומר עלות ומוניטין שליחה
    try:
        _guard_signup(request)
    except HTTPException:
        conn.close()
        raise
    code = f"{secrets.randbelow(10**6):06d}"
    conn.execute(
        "INSERT OR REPLACE INTO login_codes (email, code_hash, expires_at, attempts, sent_at) "
        "VALUES (?,?,?,0,?)",
        (email, _sha(f"{email}:{code}"),
         (now + timedelta(minutes=CODE_MINUTES)).isoformat(), now.isoformat()))
    conn.commit()
    conn.close()
    lang = payload.get("lang") if payload.get("lang") in CODE_EMAIL else "he"
    subject, body = CODE_EMAIL[lang]
    ok = send_email(email, subject.format(code=code),
                    body.format(code=code, m=CODE_MINUTES))
    if not ok:
        conn = get_db()
        conn.execute("DELETE FROM login_codes WHERE email=?", (email,))
        conn.commit()
        conn.close()
        raise HTTPException(503, "שליחת המייל נכשלה — נסה שוב בעוד דקה")
    return {"status": "code_sent"}


@app.post("/auth/verify")
def auth_verify(payload: dict = Body(...)):
    email = _email_from(payload)
    code = re.sub(r"\D", "", str(payload.get("code") or ""))
    now = _now()
    conn = get_db()
    row = conn.execute("SELECT code_hash, expires_at, attempts FROM login_codes WHERE email=?",
                       (email,)).fetchone()
    if not row or row["expires_at"] < now.isoformat():
        conn.close()
        raise HTTPException(400, "הקוד פג תוקף — בקש קוד חדש")
    if row["attempts"] >= CODE_MAX_ATTEMPTS:
        conn.close()
        raise HTTPException(429, "יותר מדי ניסיונות — בקש קוד חדש")
    if not hmac.compare_digest(row["code_hash"], _sha(f"{email}:{code}")):
        conn.execute("UPDATE login_codes SET attempts = attempts + 1 WHERE email=?", (email,))
        conn.commit()
        conn.close()
        raise HTTPException(400, "קוד שגוי")
    user = conn.execute("SELECT status, password_hash FROM users WHERE email=?", (email,)).fetchone()
    if user and user["status"] == "blocked":
        conn.close()
        raise HTTPException(403, BLOCKED_MSG)

    new_user = user is None
    if new_user:
        conn.execute(
            "INSERT INTO users (email, status, is_admin, created_at, approved_at, login_count) "
            "VALUES (?, 'approved', ?, ?, ?, 0)",
            (email, int(email in ADMIN_EMAILS), now.isoformat(), now.isoformat()))
    elif user["status"] != "approved":
        # ממתינים מהמנגנון הקודם (אישור ידני) — המייל אומת, נכנסים
        conn.execute("UPDATE users SET status='approved', approved_at=? WHERE email=?",
                     (now.isoformat(), email))
    # קוד מהמייל = אפשר לקבוע / להחליף סיסמה ברבע השעה הקרובה
    conn.execute("UPDATE users SET pw_reset_until=? WHERE email=?",
                 ((now + timedelta(minutes=PW_RESET_MIN)).isoformat(), email))
    conn.execute("DELETE FROM login_codes WHERE email=?", (email,))
    token = _start_session(conn, email, now, "code")
    conn.commit()
    conn.close()
    if new_user:
        _notify_registration(email, payload.get("lang"))
    return _session_response(token, {"ok": True,
                                     "need_password": not (user and user["password_hash"])})


@app.get("/auth/contact")
def auth_contact():
    """למי לכתוב כשאין שליחת מיילים ושכחת סיסמה. נמסר רק בלחיצה,
    ולא יושב בקוד המקור של העמוד — פחות מזון לסורקי ספאם."""
    return {"email": sorted(NOTIFY_EMAILS or ADMIN_EMAILS)[0]
                     if (NOTIFY_EMAILS or ADMIN_EMAILS) else ""}


@app.post("/auth/register")
def auth_register(request: Request, payload: dict = Body(...)):
    """הרשמה מיידית: מייל + סיסמה, בלי קוד (כל עוד EMAIL_CODE_REQUIRED כבוי).
    מייל רשום עם סיסמה — תפוס. כתובת מנהל — רק עם סיסמת המנהל."""
    if EMAIL_CODE_REQUIRED:
        raise HTTPException(403, "הרשמה דורשת קוד למייל")
    email = _email_from(payload)
    pw = str(payload.get("password") or "")
    if len(pw) < PW_MIN_LEN:
        raise HTTPException(400, "הסיסמה צריכה 8 תווים לפחות")
    if len(pw) > 200:
        raise HTTPException(400, "הסיסמה ארוכה מדי")
    if email in ADMIN_EMAILS:
        # כתובת מנהל: רק עם סיסמת המנהל (APP_PASSWORD, ידועה רק לבעלים) —
        # אחרת כל אחד היה נרשם עם הכתובת ומקבל הרשאות מנהל
        key = str(payload.get("admin_key") or "")
        if not (APP_PASSWORD and hmac.compare_digest(key.encode(), APP_PASSWORD.encode())):
            raise HTTPException(403, "כתובת מנהל דורשת את סיסמת המנהל")
    now = _now()
    conn = get_db()
    u = conn.execute("SELECT status, password_hash FROM users WHERE email=?", (email,)).fetchone()
    if u and u["status"] == "blocked":
        conn.close()
        raise HTTPException(403, BLOCKED_MSG)
    if u and u["password_hash"]:
        conn.close()
        raise HTTPException(409, "המייל כבר רשום — היכנס עם הסיסמה")
    # הבלם נספר רק על חשבון שבאמת נוצר. אילו היה בכניסה לפונקציה, מי
    # שטועה בסיסמה פעמיים ומתקן היה נחסם לשעה — וזה לא מי שמגנים מפניו.
    try:
        _guard_signup(request)
    except HTTPException:
        conn.close()
        raise
    new_user = u is None
    if new_user:
        conn.execute(
            "INSERT INTO users (email, status, is_admin, created_at, approved_at, login_count) "
            "VALUES (?, 'approved', 0, ?, ?, 0)", (email, now.isoformat(), now.isoformat()))
    else:
        # בלי סיסמה (ממתין מהמנגנון הישן / אופס ע"י המנהל) — נרשם מחדש
        conn.execute("UPDATE users SET status='approved', approved_at=COALESCE(approved_at, ?) "
                     "WHERE email=?", (now.isoformat(), email))
    conn.execute("UPDATE users SET password_hash=?, pw_fails=0, pw_locked_until=NULL, "
                 "pw_reset_until=NULL WHERE email=?", (_pw_hash(pw), email))
    token = _start_session(conn, email, now, "register")
    conn.commit()
    conn.close()
    if new_user:
        _notify_registration(email, payload.get("lang"))
    return _session_response(token, {"ok": True})


_DUMMY_PW_HASH = _pw_hash(secrets.token_hex(8))   # זמן תגובה זהה גם למייל לא קיים


@app.post("/auth/login")
def auth_login(payload: dict = Body(...)):
    """כניסה עם מייל + סיסמה. 5 טעויות רצופות → נעילה ל-15 דקות (הקוד למייל
    עדיין עובד)."""
    email = _email_from(payload)
    pw = str(payload.get("password") or "")[:200]
    now = _now()
    conn = get_db()
    u = conn.execute("SELECT status, password_hash, pw_fails, pw_locked_until FROM users "
                     "WHERE email=?", (email,)).fetchone()
    if u and (u["pw_locked_until"] or "") > now.isoformat():
        conn.close()
        raise HTTPException(429, "יותר מדי ניסיונות — נסה שוב בעוד 15 דקות או היכנס עם קוד")
    stored = u["password_hash"] if u and u["password_hash"] else None
    ok = _pw_check(pw, stored or _DUMMY_PW_HASH) and stored is not None
    if not ok:
        if u:
            fails = (u["pw_fails"] or 0) + 1
            if fails >= PW_MAX_FAILS:
                conn.execute("UPDATE users SET pw_fails=0, pw_locked_until=? WHERE email=?",
                             ((now + timedelta(minutes=PW_LOCK_MIN)).isoformat(), email))
            else:
                conn.execute("UPDATE users SET pw_fails=? WHERE email=?", (fails, email))
            conn.commit()
        conn.close()
        raise HTTPException(400, "מייל או סיסמה שגויים")
    if u["status"] == "blocked":
        conn.close()
        raise HTTPException(403, BLOCKED_MSG)
    conn.execute("UPDATE users SET pw_fails=0, pw_locked_until=NULL WHERE email=?", (email,))
    token = _start_session(conn, email, now, "password")
    conn.commit()
    conn.close()
    return _session_response(token, {"ok": True})


@app.post("/auth/set_password")
def auth_set_password(request: Request, payload: dict = Body(...)):
    """קביעת סיסמה בכניסה הראשונה, או החלפה — עד 15 דק' אחרי כניסה עם קוד."""
    require_auth(request)
    email = (current_user(request) or {}).get("email")
    if not email:
        raise HTTPException(400, "אין חשבון אישי")
    pw = str(payload.get("password") or "")
    if len(pw) < PW_MIN_LEN:
        raise HTTPException(400, "הסיסמה צריכה 8 תווים לפחות")
    if len(pw) > 200:
        raise HTTPException(400, "הסיסמה ארוכה מדי")
    now = _now()
    conn = get_db()
    u = conn.execute("SELECT password_hash, pw_reset_until FROM users WHERE email=?",
                     (email,)).fetchone()
    if u["password_hash"] and (u["pw_reset_until"] or "") < now.isoformat():
        conn.close()
        raise HTTPException(403, "כדי להחליף סיסמה — היכנס עם קוד למייל")
    conn.execute("UPDATE users SET password_hash=?, pw_reset_until=NULL, pw_fails=0, "
                 "pw_locked_until=NULL WHERE email=?", (_pw_hash(pw), email))
    conn.commit()
    conn.close()
    return {"ok": True}


@app.post("/auth/logout")
def auth_logout(request: Request):
    token = request.cookies.get("sf_session", "")
    if token:
        conn = get_db()
        conn.execute("DELETE FROM sessions WHERE token_hash=?", (_sha(token),))
        conn.commit()
        conn.close()
    resp = JSONResponse({"ok": True})
    resp.delete_cookie("sf_session")
    resp.delete_cookie("sf_auth")
    return resp


@app.get("/auth/me")
def auth_me(request: Request):
    require_auth(request)
    u = current_user(request) or {}
    # onboarded: האם כבר הוצגו מסכי הפתיחה (#32). מי שכבר יש לו מועדפים —
    # לא מציגים לו. בלי חשבון אישי: None (הפרונט לא מציג)
    onboarded = None
    if u.get("email"):
        conn = get_db()
        r = conn.execute("SELECT onboarded_at FROM users WHERE email=?", (u["email"],)).fetchone()
        has = (conn.execute("SELECT 1 FROM favorites WHERE email=? LIMIT 1", (u["email"],)).fetchone()
               or conn.execute("SELECT 1 FROM favorite_leagues WHERE email=? LIMIT 1",
                               (u["email"],)).fetchone())
        conn.close()
        onboarded = bool((r and r["onboarded_at"]) or has)
    return {"auth_on": AUTH_ON, "email": u.get("email"),
            "is_admin": bool(u.get("is_admin")) or not AUTH_ON,
            "legacy": bool(u.get("legacy")), "onboarded": onboarded,
            # שתי הכתובות מריצות את אותו קוד ונראות זהות. הסימונים האלה
            # הם מה שמבדיל ביניהן — ומה שמאפשר לענות על "למה זה נפתח
            # ביוטיוב אצלי?" בלי לנחש איזה משתנה הוגדר איפה.
            "private": bool(ALLOWED_EMAILS), "embed": EMBED_IN_APP}


@app.post("/auth/onboarded")
def auth_onboarded(request: Request):
    """מסכי הפתיחה הוצגו (סיום או דילוג) — לא יוצגו שוב."""
    require_auth(request)
    email = (current_user(request) or {}).get("email")
    if email:
        conn = get_db()
        conn.execute("UPDATE users SET onboarded_at=COALESCE(onboarded_at, ?) WHERE email=?",
                     (_now().isoformat(), email))
        conn.commit()
        conn.close()
    return {"ok": True}


@app.post("/events")
def log_event(request: Request, payload: dict = Body(...)):
    """מעקב שימוש: אירוע אחד לכל פעולה (פתיחת אפליקציה, ליגה, משחק, תקציר)."""
    require_auth(request)
    u = current_user(request)
    if not u or not u.get("email"):
        return {"ok": True, "skipped": True}   # פיתוח מקומי / סיסמה ישנה — אין משתמש
    etype = payload.get("type")
    if etype not in EVENT_TYPES:
        raise HTTPException(400, "סוג אירוע לא מוכר")

    def field(k):
        v = payload.get(k)
        return str(v)[:100] if v not in (None, "") else None

    conn = get_db()
    conn.execute("INSERT INTO events (email, ts, type, league, match_id, detail) VALUES (?,?,?,?,?,?)",
                 (u["email"], _now().isoformat(), etype,
                  field("league"), field("match_id"), field("detail")))
    conn.commit()
    conn.close()
    return {"ok": True}


# ── חשבון אישי: פרטים ומחיקה ───────────────────────────

@app.get("/auth/account")
def auth_account(request: Request):
    require_auth(request)
    u = current_user(request) or {}
    if not u.get("email"):
        return {"email": None}
    conn = get_db()
    r = conn.execute("SELECT email, created_at, last_login, login_count FROM users WHERE email=?",
                     (u["email"],)).fetchone()
    n = conn.execute("SELECT COUNT(*) AS c FROM events WHERE email=?", (u["email"],)).fetchone()["c"]
    conn.close()
    return {"email": r["email"], "created_at": r["created_at"], "last_login": r["last_login"],
            "login_count": r["login_count"] or 0, "events": n}


@app.post("/auth/delete_account")
def auth_delete_account(request: Request, payload: dict = Body(...)):
    """מחיקה סופית של החשבון וכל נתוני השימוש. אישור: הקלדת המייל."""
    require_auth(request)
    email = (current_user(request) or {}).get("email")
    if not email:
        raise HTTPException(400, "אין חשבון אישי למחיקה")
    if str(payload.get("confirm") or "").strip().lower() != email:
        raise HTTPException(400, "כדי למחוק, הקלד את כתובת המייל שלך בדיוק")
    conn = get_db()
    for table in ("events", "sessions", "login_codes", "favorites", "favorite_leagues",
                  "hidden_leagues", "prefs", "users"):
        conn.execute(f"DELETE FROM {table} WHERE email=?", (email,))
    conn.commit()
    conn.close()
    resp = JSONResponse({"ok": True})
    resp.delete_cookie("sf_session")
    return resp


# ── מועדפים ────────────────────────────────────────────
# נשמרים בחשבון (זהים בכל המכשירים). בלי חשבון אישי (סיסמה ישנה / פיתוח
# מקומי) — הפרונט שומר במכשיר.

@app.get("/favorites")
def get_favorites(request: Request):
    require_auth(request)
    email = (current_user(request) or {}).get("email")
    if not email:
        return {"favorites": [], "leagues": [], "hidden": [], "per_device": True}
    conn = get_db()
    rows = conn.execute("SELECT team FROM favorites WHERE email=? ORDER BY team",
                        (email,)).fetchall()
    lgs = conn.execute("SELECT league_key FROM favorite_leagues WHERE email=? ORDER BY league_key",
                       (email,)).fetchall()
    hid = conn.execute("SELECT league_key FROM hidden_leagues WHERE email=? ORDER BY league_key",
                       (email,)).fetchall()
    conn.close()
    return {"favorites": [r["team"] for r in rows], "leagues": [r["league_key"] for r in lgs],
            "hidden": [r["league_key"] for r in hid]}


@app.post("/favorites")
def set_favorite(request: Request, payload: dict = Body(...)):
    require_auth(request)
    email = (current_user(request) or {}).get("email")
    if not email:
        raise HTTPException(400, "בלי חשבון אישי — המועדפים נשמרים במכשיר")
    if "hide_league" in payload:   # ליגה מוסתרת — מסתירים = גם לא מועדפת
        lg = str(payload.get("hide_league") or "")
        if lg not in LEAGUES:
            raise HTTPException(400, "ליגה לא מוכרת")
        conn = get_db()
        if payload.get("on", True):
            conn.execute("INSERT OR IGNORE INTO hidden_leagues (email, league_key) VALUES (?, ?)",
                         (email, lg))
            conn.execute("DELETE FROM favorite_leagues WHERE email=? AND league_key=?", (email, lg))
        else:
            conn.execute("DELETE FROM hidden_leagues WHERE email=? AND league_key=?", (email, lg))
        conn.commit()
        conn.close()
        return {"ok": True}
    if "league" in payload:   # ליגה מועדפת (#32)
        lg = str(payload.get("league") or "")
        if lg not in LEAGUES:
            raise HTTPException(400, "ליגה לא מוכרת")
        conn = get_db()
        if payload.get("on", True):
            conn.execute("INSERT OR IGNORE INTO favorite_leagues (email, league_key) VALUES (?, ?)",
                         (email, lg))
        else:
            conn.execute("DELETE FROM favorite_leagues WHERE email=? AND league_key=?", (email, lg))
        conn.commit()
        conn.close()
        return {"ok": True}
    # מפתח אחיד — גם אם נשלח שם מקור ("Liverpool FC") הוא מנורמל
    team = team_key(str(payload.get("team") or ""))[:120]
    if not team:
        raise HTTPException(400, "קבוצה לא תקינה")
    conn = get_db()
    if payload.get("on", True):
        conn.execute("INSERT OR IGNORE INTO favorites (email, league_key, team) VALUES (?, '', ?)",
                     (email, team))
    else:
        conn.execute("DELETE FROM favorites WHERE email=? AND team=?", (email, team))
    conn.commit()
    conn.close()
    return {"ok": True}


@app.post("/favorites/bulk")
def set_favorites_bulk(request: Request, payload: dict = Body(...)):
    """כל המועדפים בבקשה אחת. חיבור ל-Turso מסנכרן מול הענן, כך
    שבקשה לכל קבוצה בנפרד שילמה את המחיר הזה שוב ושוב — במסכי
    הפתיחה זה הצטבר לשניות, והמשתמש לחץ "סיום" שוב ושוב."""
    require_auth(request)
    email = (current_user(request) or {}).get("email")
    if not email:
        raise HTTPException(400, "בלי חשבון אישי — המועדפים נשמרים במכשיר")
    teams = [k for k in (team_key(str(t or ""))[:120]
                         for t in (payload.get("teams") or [])[:200]) if k]
    leagues = [lg for lg in (payload.get("leagues") or [])[:100] if lg in LEAGUES]
    # ליגות שהמשתמש לא בחר — לא מוצגות. מסכי הפתיחה שואלים "באילו ליגות
    # אתה מתעניין", והתשובה צריכה להיות גם מה שרואים בתצוגה לפי יום.
    hide = [lg for lg in (payload.get("hide_leagues") or [])[:100]
            if lg in LEAGUES and lg not in leagues]
    conn = get_db()
    for team in teams:
        conn.execute("INSERT OR IGNORE INTO favorites (email, league_key, team) VALUES (?, '', ?)",
                     (email, team))
    for lg in leagues:
        conn.execute("INSERT OR IGNORE INTO favorite_leagues (email, league_key) VALUES (?, ?)",
                     (email, lg))
        # מועדפת = לא מוסתרת (אותה משמעות כמו בשמירה הבודדת)
        conn.execute("DELETE FROM hidden_leagues WHERE email=? AND league_key=?", (email, lg))
    for lg in hide:
        conn.execute("INSERT OR IGNORE INTO hidden_leagues (email, league_key) VALUES (?, ?)",
                     (email, lg))
        conn.execute("DELETE FROM favorite_leagues WHERE email=? AND league_key=?", (email, lg))
    conn.commit()
    conn.close()
    return {"ok": True, "teams": len(teams), "leagues": len(leagues), "hidden": len(hide)}


# ── Admin: משתמשים ─────────────────────────────────────

# מסכי הפתיחה (#32): קבוצות פופולריות לכל ליגה, לפי סדר. השמות מותאמים
# לנתונים דרך team_key (כולל קידומת: "Inter Milan" ↔ "Inter"); ליגה בלי
# רשימה / עם מעט התאמות — משלימים מהקבוצות שבנתונים.
POPULAR_TEAMS = {
    "premier":    ["Arsenal", "Liverpool", "Manchester City", "Manchester United", "Chelsea",
                   "Tottenham Hotspur"],
    "israel":     ["Maccabi Tel Aviv", "Maccabi Haifa", "Hapoel Be'er Sheva", "Beitar Jerusalem",
                   "Hapoel Tel-Aviv", "Maccabi Netanya"],
    "bundesliga": ["Bayern Munich", "Borussia Dortmund", "Bayer Leverkusen", "RB Leipzig",
                   "Eintracht Frankfurt"],
    "laliga":     ["Real Madrid", "Barcelona", "Atlético Madrid", "Athletic Bilbao", "Real Sociedad",
                   "Sevilla"],
    "seriea":     ["Juventus", "Inter Milan", "AC Milan", "Napoli", "Roma", "Lazio"],
    "ligue1":     ["Paris Saint-Germain", "Marseille", "Lyon", "Monaco", "Lille"],
    "ucl":        ["Real Madrid", "Barcelona", "Bayern Munich", "Liverpool", "Manchester City",
                   "Paris Saint-Germain", "Arsenal", "Inter Milan"],
    "uel":        ["Hapoel Be'er Sheva", "AC Milan", "Juventus", "Benfica", "Celtic", "Lyon"],
    "mls":        ["Inter Miami", "LA Galaxy", "Los Angeles FC"],
    "argentina":  ["Boca Juniors", "River Plate", "Racing Club", "Independiente"],
}
# גביע = אותן קבוצות גדולות כמו הליגה של אותה מדינה. בלי זה, מסך
# הפתיחה היה מציע את מוקדמות הגביע האנגלי לפי א"ב.
for _cup, _league in (("carabao", "premier"), ("facup", "premier"),
                      ("dfbpokal", "bundesliga"), ("copadelrey", "laliga"),
                      ("coupedefrance", "ligue1")):
    POPULAR_TEAMS[_cup] = POPULAR_TEAMS[_league]

ONBOARD_MIN_TEAMS = 6


@app.get("/onboarding/teams")
def onboarding_teams(request: Request, leagues: str = "", lang: str = "he"):
    require_auth(request)
    lang = _lang(lang)
    wanted = [lg for lg in dict.fromkeys(leagues.split(",")) if lg in LEAGUES]
    out = {}
    conn = get_db()
    # שאילתה אחת לכל הליגות שנבחרו (היו שתיים לכל ליגה)
    by_league: dict = {lg: {} for lg in wanted}
    if wanted:
        marks = ",".join("?" * len(wanted))
        for r in conn.execute(
                f"SELECT league_key, home_team, away_team FROM matches "
                f"WHERE league_key IN ({marks})", wanted).fetchall():
            cat = by_league.setdefault(r["league_key"], {})
            for name in (r["home_team"], r["away_team"]):
                name = (name or "").strip()
                if team_key(name):
                    cat.setdefault(team_key(name), name)
    # קבוצה מוצעת פעם אחת בלבד. ריאל מדריד הופיעה גם תחת "לה ליגה" וגם
    # תחת "צ'מפיונס" — שני צ'יפים לאותה בחירה, כך שסימון שניהם ביטל אותה
    # והמסך הראה שני מצבים סותרים.
    offered: set = set()
    for lg in wanted:
        catalog = by_league.get(lg, {})
        picked = []
        for name in POPULAR_TEAMS.get(lg, []):
            k = team_key(name)
            hit = k if k in catalog else next(
                (c for c in catalog if k.startswith(c + " ") or c.startswith(k + " ")), None)
            if hit and hit not in picked and hit not in offered:
                picked.append(hit)
        if len(picked) < ONBOARD_MIN_TEAMS:
            rest = sorted((c for c in catalog if c not in picked and c not in offered),
                          key=lambda c: display_team(catalog[c], lang))
            picked += rest[:ONBOARD_MIN_TEAMS - len(picked)]
        offered.update(picked)
        out[lg] = [{"key": k, "name": display_team(catalog[k], lang)} for k in picked]
    conn.close()
    return {"leagues": out}


# ── תוצאות: ברירת מחדל אישית ───────────────────────────
# off (ברירת המחדל בכל מכשיר חדש) / all (בכל האתר) / match (רק בחלון המשחק)
SCORES_MODES = ("off", "all", "match")


@app.get("/prefs")
def get_prefs(request: Request):
    require_auth(request)
    email = (current_user(request) or {}).get("email")
    if not email:
        return {"scores_default": "off", "per_device": True}
    conn = get_db()
    row = conn.execute("SELECT value FROM prefs WHERE email=? AND key='scores_default'",
                       (email,)).fetchone()
    conn.close()
    return {"scores_default": row["value"] if row else "off"}


@app.post("/prefs")
def set_prefs(request: Request, payload: dict = Body(...)):
    require_auth(request)
    email = (current_user(request) or {}).get("email")
    mode = str(payload.get("scores_default") or "")
    if mode not in SCORES_MODES:
        raise HTTPException(400, "ערך לא תקין")
    if not email:
        raise HTTPException(400, "בלי חשבון אישי — ההעדפה נשמרת במכשיר")
    conn = get_db()
    conn.execute("INSERT OR REPLACE INTO prefs (email, key, value) VALUES (?, 'scores_default', ?)",
                 (email, mode))
    conn.commit()
    conn.close()
    return {"ok": True}


@app.get("/score/{match_id}")
def get_score(request: Request, match_id: str):
    """תוצאה של משחק בודד — רק כשהמשתמש ביקש לראות אותה במפורש."""
    require_auth(request)
    conn = get_db()
    row = conn.execute("SELECT home_score, away_score, status FROM matches WHERE id=?",
                       (match_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "משחק לא נמצא")
    if row["home_score"] is None or row["away_score"] is None:
        return {"available": False}
    return {"available": True, "home": row["home_score"], "away": row["away_score"]}


@app.get("/teams")
def list_teams(request: Request, lang: str = "he"):
    """קטלוג קבוצות לעמוד המועדפים: מפתח אחיד (כמו במועדפים), שם בשפת
    המשתמש, ובאילו מפעלים הקבוצה משחקת (ליברפול: פרמייר + צ'מפיונס)."""
    require_auth(request)
    lang = _lang(lang)
    conn = get_db()
    rows = conn.execute("SELECT DISTINCT league_key, home_team AS team FROM matches "
                        "UNION SELECT DISTINCT league_key, away_team FROM matches").fetchall()
    conn.close()
    order = list(LEAGUES)
    teams = {}
    for r in rows:
        name = (r["team"] or "").strip()
        key = team_key(name)
        if not key:
            continue
        e = teams.setdefault(key, {"key": key, "name": display_team(name, lang), "leagues": []})
        if r["league_key"] not in e["leagues"]:
            e["leagues"].append(r["league_key"])
    for e in teams.values():
        e["leagues"].sort(key=lambda lg: order.index(lg) if lg in order else len(order))
    return {"teams": sorted(teams.values(), key=lambda e: e["name"])}


@app.get("/admin/users")
def admin_users_page(request: Request):
    if AUTH_ON and not (current_user(request) or {}).get("is_admin"):
        return RedirectResponse("/")
    return HTMLResponse(ADMIN_USERS_PAGE)


@app.get("/admin/api/users")
def admin_api_users(request: Request):
    require_admin(request)
    conn = get_db()
    users = [{k: r[k] for k in r.keys()} for r in conn.execute("SELECT * FROM users").fetchall()]
    for u in users:   # לעולם לא שולחים hash של סיסמה לדפדפן
        u["has_password"] = bool(u.pop("password_hash", None))
        for k in ("pw_fails", "pw_locked_until", "pw_reset_until"):
            u.pop(k, None)
    counts = conn.execute("SELECT email, type, COUNT(*) AS c, MAX(ts) AS last "
                          "FROM events GROUP BY email, type").fetchall()
    leagues = conn.execute("SELECT email, league, COUNT(*) AS c FROM events "
                           "WHERE league IS NOT NULL GROUP BY email, league").fetchall()
    # צריכת quota של יוטיוב היום (יום פסיפיק — כמו האיפוס של גוגל)
    yt_day = datetime.now(ZoneInfo("America/Los_Angeles")).strftime("%Y-%m-%d")
    yt_row = conn.execute("SELECT value FROM meta WHERE key=?", (f"yt_units:{yt_day}",)).fetchone()
    conn.close()

    by = {u["email"]: u for u in users}
    for u in users:
        u["last_active"] = u.get("last_login")
        u["_lg"] = {}
        u["is_admin"] = bool(u.get("is_admin")) or u["email"] in ADMIN_EMAILS
    for r in counts:
        u = by.get(r["email"])
        if not u:
            continue
        u[r["type"]] = r["c"]
        if r["last"] and (not u["last_active"] or r["last"] > u["last_active"]):
            u["last_active"] = r["last"]
    for r in leagues:
        if r["email"] in by:
            by[r["email"]]["_lg"][r["league"]] = r["c"]
    for u in users:
        u["top_leagues"] = [k for k, _ in sorted(u.pop("_lg").items(), key=lambda x: -x[1])[:3]]

    order = {"pending": 0, "approved": 1, "blocked": 2}
    # ממתינים קודם, ובתוך כל סטטוס — הפעיל לאחרונה למעלה (מיון יציב)
    users.sort(key=lambda u: u["last_active"] or "", reverse=True)
    users.sort(key=lambda u: order.get(u["status"], 3))
    week = (_now() - timedelta(days=7)).isoformat()
    kpis = {"total": len(users),
            "pending": sum(u["status"] == "pending" for u in users),
            "active_7d": sum(1 for u in users if (u["last_active"] or "") > week),
            "plays": sum(u.get("highlight_play", 0) for u in users),
            "yt_units_today": int(yt_row["value"]) if yt_row else 0}
    return {"users": users, "kpis": kpis}


MATCH_LENGTH_MIN = 115   # פתיחה → שריקת סיום (משוער: הפסקה + תוספות)


@app.get("/admin/api/timing")
def admin_api_timing(request: Request, league: str = "israel", days: int = 21):
    """#10 מי מעלה ראשון: לכל משחק — דקות מהסיום (משוער) עד שכל מקור עלה.
    יוטיוב: שעת ההעלאה בפועל; אתרים: הפעם הראשונה שמצאנו (דיוק ~30 דק')."""
    require_admin(request)
    since = (_now() - timedelta(days=days)).strftime("%Y-%m-%d")
    conn = get_db()
    rows = conn.execute("SELECT * FROM matches WHERE league_key=? AND date_utc>=? "
                        "ORDER BY date_utc DESC, time_utc DESC", (league, since)).fetchall()
    seen = conn.execute("SELECT f.* FROM highlight_first_seen f JOIN matches m ON m.id=f.match_id "
                        "WHERE m.league_key=? AND m.date_utc>=?", (league, since)).fetchall()
    conn.close()

    cfg = LEAGUES.get(league, {})
    names = {s["id"]: s["name"] for s in cfg.get("sources", [])}
    names.update({f"web_{w['name']}": f"{w['name']} (אתר)" for w in cfg.get("web_sources", [])})
    by_match = {}
    for s in seen:
        by_match.setdefault(s["match_id"], []).append(s)

    matches, stats = [], {}
    for r in rows:
        try:
            end = (datetime.fromisoformat(f"{r['date_utc']}T{r['time_utc']}+00:00")
                   + timedelta(minutes=MATCH_LENGTH_MIN))
        except (ValueError, TypeError):
            continue
        delays = {}
        for s in by_match.get(r["id"], []):
            at = (s["published"] or s["first_seen"] or "").replace("Z", "+00:00")
            try:
                delays[s["source_id"]] = max(0, int((datetime.fromisoformat(at) - end)
                                                    .total_seconds() // 60))
            except ValueError:
                pass
        if not delays:
            continue
        first = min(delays, key=delays.get)
        for sid, d in delays.items():
            st = stats.setdefault(sid, {"found": 0, "first": 0, "delays": []})
            st["found"] += 1
            st["delays"].append(d)
        stats[first]["first"] += 1
        matches.append({
            "match": f"{display_team(r['home_team'], 'he')} – {display_team(r['away_team'], 'he')}",
            "date": r["date_utc"], "first": names.get(first, first),
            "delays": {names.get(k, k): v for k, v in sorted(delays.items(), key=lambda x: x[1])}})

    summary = sorted(({"source": names.get(k, k), "found": v["found"], "first": v["first"],
                       "median_min": sorted(v["delays"])[len(v["delays"]) // 2]}
                      for k, v in stats.items()),
                     key=lambda x: (-x["first"], x["median_min"]))
    return {"league": league, "days": days,
            "matches_over": sum(1 for r in rows if likely_over(r)),
            "summary": summary, "matches": matches}


@app.post("/admin/api/users/{email}")
def admin_api_update_user(request: Request, email: str, payload: dict = Body(...)):
    require_admin(request)
    email = unquote(email).strip().lower()
    status = payload.get("status")
    if status not in ("approved", "blocked", "pending"):
        raise HTTPException(400, "סטטוס לא תקין")
    conn = get_db()
    row = conn.execute("SELECT status FROM users WHERE email=?", (email,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "משתמש לא נמצא")
    conn.execute("UPDATE users SET status=?, "
                 "approved_at = CASE WHEN ?='approved' THEN ? ELSE approved_at END WHERE email=?",
                 (status, status, _now().isoformat(), email))
    if status == "blocked":
        conn.execute("DELETE FROM sessions WHERE email=?", (email,))  # מנותק מיד
    conn.commit()
    conn.close()
    if status == "approved" and row["status"] != "approved":
        send_email(email, "אושרת ל-SpoilerFree ⚽",
                   f"החשבון שלך אושר!\n\nלכניסה: {APP_URL}\n"
                   f"הכנס את המייל הזה ותקבל קוד כניסה.\n")
    return {"ok": True}


@app.post("/admin/api/users/{email}/reset_password")
def admin_api_reset_password(request: Request, email: str):
    """"שכחתי סיסמה" בלי מיילים: המנהל מאפס, והמשתמש נרשם שוב עם אותו מייל
    וסיסמה חדשה (ההיסטוריה והמועדפים נשמרים). מנותק מכל המכשירים."""
    require_admin(request)
    email = unquote(email).strip().lower()
    conn = get_db()
    if not conn.execute("SELECT 1 FROM users WHERE email=?", (email,)).fetchone():
        conn.close()
        raise HTTPException(404, "משתמש לא נמצא")
    conn.execute("UPDATE users SET password_hash=NULL, pw_fails=0, pw_locked_until=NULL, "
                 "pw_reset_until=NULL WHERE email=?", (email,))
    conn.execute("DELETE FROM sessions WHERE email=?", (email,))
    conn.commit()
    conn.close()
    return {"ok": True}


@app.get("/app")
def serve_frontend(request: Request):
    # no-store: אותה כתובת מחזירה דף אחר לפי ה-cookie. בלי זה הדפדפן שמר את
    # האפליקציה בקאש ל"/?fresh=1", ואחרי יציאה/401 טען אותה שוב — לולאה.
    # (הקאש של ה-service worker נפרד ולא מושפע.)
    no_store = {"Cache-Control": "no-store"}
    if not is_authed(request):
        return HTMLResponse(render_login_page(), headers=no_store)
    # X-SF-App: ה-service worker שומר בקאש רק את הדף הזה, לא את מסך הכניסה
    return FileResponse("index.html", headers={"X-SF-App": "1", **no_store})


# ── PWA ────────────────────────────────────────────────
# ציבוריים (בלי סיסמה) — הדפדפן טוען אותם גם לפני כניסה.

@app.get("/manifest.webmanifest")
def pwa_manifest():
    return FileResponse("static/manifest.webmanifest",
                        media_type="application/manifest+json")


@app.get("/sw.js")
def pwa_service_worker():
    # no-cache: שינויים ב-sw.js מגיעים למכשירים מיד אחרי deploy
    return FileResponse("static/sw.js", media_type="application/javascript",
                        headers={"Cache-Control": "no-cache"})


@app.get("/icons/{name}")
def pwa_icon(name: str):
    if name not in ("icon-192.png", "icon-512.png", "apple-touch-icon.png"):
        raise HTTPException(404)
    return FileResponse(f"static/icons/{name}", media_type="image/png")


# ── Init ───────────────────────────────────────────────
init_db()
