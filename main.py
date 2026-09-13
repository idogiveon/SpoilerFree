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
from html import unescape as _unescape
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
             "title_include": ["efl"],
             "allow_embed": False},
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
            {"id": "sport1", "name": "ספורט 1",
             "channel_id": "UC_wkUEeEC4HlcfI5xanWjBQ",
             "search_template": "תקציר {home} {away}",
             "hebrew_names": True,
             "allow_embed": False},
            {"id": "sport5", "name": "ערוץ הספורט",
             "channel_id": "UCyXf5cz6E9IIL40aivg7tOw",
             "search_template": "תקציר {home} {away}",
             "hebrew_names": True,
             "allow_embed": False},
            {"id": "ipfl", "name": "ליגת העל",
             "channel_id": "UCxjaVFauWASy0CuJfHKZeiw",
             "search_template": "תקציר {home} {away}",
             "hebrew_names": True,
             "allow_embed": False},
            # ערוצים לא רשמיים (העלאות פיראטיות) — לפעמים מקדימים את הרשמיים.
            # il_both_teams: רק "תקציר" + שתי הקבוצות בשם מלא (is_il_both_teams)
            {"id": "yt_footballyom1", "name": "@FootballYom1",
             "channel_id": "UC5TtVDq_BSplSOHf7lb2AGQ",
             "search_template": "תקציר {home} {away}",
             "hebrew_names": True, "il_both_teams": True,
             "allow_embed": False},
            {"id": "yt_almog218", "name": "@almog218",
             "channel_id": "UCm8OkQc5lHJE29ADWkbB7CQ",
             "search_template": "תקציר {home} {away}",
             "hebrew_names": True, "il_both_teams": True,
             "allow_embed": False},
            {"id": "yt_itsfootball44", "name": "@ItsFootball44",
             "channel_id": "UCUEeo-8_3zovErCSQb58dnw",
             "search_template": "תקציר {home} {away}",
             "hebrew_names": True, "il_both_teams": True,
             "allow_embed": False},
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
             "search_template": "{home} {away} highlights",
             "allow_embed": False},
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
             "headline_titles": True,
             "allow_embed": False},
            {"id": "laliga_official", "name": "LALIGA",
             "channel_id": "UCTv-XvfzLX3i4IGWAm4sbmA",
             "search_template": "{home} {away} resumen",
             "allow_embed": False},
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
             "headline_titles": True,
             "allow_embed": False},
            {"id": "seriea_official", "name": "Serie A",
             "channel_id": "UCBJeMCIeLQos7wacox4hmLQ",
             "search_template": "{home} {away} highlights",
             "allow_embed": False},
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
             "search_template": "{home} {away} highlights",
             "allow_embed": False},
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
        "sources": [],
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
             "title_include": ["highlights"],
             "allow_embed": False},
        ],
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
             "title_exclude": ["game highlights"],
             "allow_embed": False},
            {"id": "lpf_official", "name": "Liga Profesional",
             "channel_id": "UCJmCVoUfCBQb9lcfXIS8nXQ",
             "search_template": "{home} {away} resumen",
             "allow_embed": False},
        ],
    },
}

# ── Auth ───────────────────────────────────────────────
# כניסה אישית: מייל → קוד חד-פעמי (6 ספרות, 10 דקות) → session ל-90 יום.
# חשבון חדש ממתין לאישור ידני של אדמין (/admin/users). אדמינים: ADMIN_EMAILS
# (משתנה סביבה ב-Render — לא בקוד, הריפו ציבורי).
# הסיסמה המשותפת הישנה (APP_PASSWORD) עובדת במקביל עד שמסירים אותה מ-Render.
# בלי אף אחד מהמשתנים (פיתוח מקומי) — האתר פתוח. AUTH_DEV=1: כניסה פעילה
# מקומית, והקוד מודפס ללוג במקום להישלח.

GMAIL_USER         = os.environ.get("GMAIL_USER", "")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "")
ADMIN_EMAILS = {e.strip().lower()
                for e in os.environ.get("ADMIN_EMAILS", "").split(",") if e.strip()}
APP_URL  = os.environ.get("APP_URL", "https://spoilerfree.onrender.com").rstrip("/")
AUTH_DEV = os.environ.get("AUTH_DEV") == "1"
AUTH_ON  = bool(APP_PASSWORD or GMAIL_USER or AUTH_DEV)

SESSION_DAYS      = 90
CODE_MINUTES      = 10
CODE_MAX_ATTEMPTS = 5
CODE_RESEND_SEC   = 60
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


def send_email(to: str, subject: str, body: str) -> bool:
    """שליחה דרך Gmail ייעודי (SMTP + סיסמת אפליקציה מ-Render)."""
    if not (GMAIL_USER and GMAIL_APP_PASSWORD):
        if AUTH_DEV:
            print(f"[mail:dev] to={to} | {subject}\n{body}")
            return True
        print(f"[mail] not configured — cannot send to {to}")
        return False
    msg = EmailMessage()
    msg["From"] = f"SpoilerFree <{GMAIL_USER}>"
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=15) as s:
            s.login(GMAIL_USER, GMAIL_APP_PASSWORD)
            s.send_message(msg)
        return True
    except Exception as ex:
        print(f"[mail] send to {to} failed: {ex}")
        return False


def _notify_admins_new_user(email: str):
    for admin in ADMIN_EMAILS:
        send_email(admin, f"SpoilerFree — בקשת הצטרפות: {email}",
                   f"{email} ביקש/ה להצטרף ל-SpoilerFree.\n\n"
                   f"לאישור או חסימה: {APP_URL}/admin/users\n")


# תרגומי מסך הכניסה (השפה נשמרת במכשיר — אותה בחירה כמו באפליקציה).
# err_*: הודעות השרת (בעברית) → מפתח, כדי להציג אותן בשפת המשתמש.
LOGIN_I18N = {
    "he": {"title": "כניסה", "enter_email": "הכנס מייל ונשלח לך קוד כניסה", "send_code": "שלח קוד",
           "sent_to": "שלחנו קוד בן 6 ספרות אל", "enter": "כניסה", "other_email": "מייל אחר / שלח שוב",
           "request_sent": "✓ הבקשה נשלחה", "pending": "החשבון ממתין לאישור. תקבל מייל ברגע שהוא יאושר.",
           "back": "חזרה", "password": "סיסמה", "back_to_email": "חזרה לכניסה במייל",
           "legacy_link": "כניסה עם סיסמה (זמני)", "ok": "אישור", "generic_err": "שגיאה — נסה שוב",
           "code_len": "הקוד הוא 6 ספרות", "wrong_password": "סיסמה שגויה",
           "err_invalid_email": "כתובת מייל לא תקינה", "err_send_failed": "שליחת המייל נכשלה — נסה שוב בעוד דקה",
           "err_expired": "הקוד פג תוקף — בקש קוד חדש", "err_too_many": "יותר מדי ניסיונות — בקש קוד חדש",
           "err_wrong_code": "קוד שגוי", "err_pending": "החשבון ממתין לאישור"},
    "en": {"title": "Log in", "enter_email": "Enter your email and we'll send you a login code", "send_code": "Send code",
           "sent_to": "We sent a 6-digit code to", "enter": "Log in", "other_email": "Different email / resend",
           "request_sent": "✓ Request sent", "pending": "Your account is awaiting approval. We'll email you once it's approved.",
           "back": "Back", "password": "Password", "back_to_email": "Back to email login",
           "legacy_link": "Log in with password (temporary)", "ok": "OK", "generic_err": "Something went wrong — try again",
           "code_len": "The code has 6 digits", "wrong_password": "Wrong password",
           "err_invalid_email": "Invalid email address", "err_send_failed": "Couldn't send the email — try again in a minute",
           "err_expired": "The code has expired — request a new one", "err_too_many": "Too many attempts — request a new code",
           "err_wrong_code": "Wrong code", "err_pending": "Your account is awaiting approval"},
    "es": {"title": "Entrar", "enter_email": "Escribe tu correo y te enviaremos un código de acceso", "send_code": "Enviar código",
           "sent_to": "Enviamos un código de 6 dígitos a", "enter": "Entrar", "other_email": "Otro correo / reenviar",
           "request_sent": "✓ Solicitud enviada", "pending": "Tu cuenta está pendiente de aprobación. Te avisaremos por correo cuando se apruebe.",
           "back": "Volver", "password": "Contraseña", "back_to_email": "Volver al acceso por correo",
           "legacy_link": "Entrar con contraseña (temporal)", "ok": "Aceptar", "generic_err": "Algo salió mal — inténtalo de nuevo",
           "code_len": "El código tiene 6 dígitos", "wrong_password": "Contraseña incorrecta",
           "err_invalid_email": "Correo no válido", "err_send_failed": "No se pudo enviar el correo — inténtalo en un minuto",
           "err_expired": "El código ha caducado — pide uno nuevo", "err_too_many": "Demasiados intentos — pide un código nuevo",
           "err_wrong_code": "Código incorrecto", "err_pending": "Tu cuenta está pendiente de aprobación"},
    "fr": {"title": "Connexion", "enter_email": "Saisissez votre e-mail et nous vous enverrons un code", "send_code": "Envoyer le code",
           "sent_to": "Nous avons envoyé un code à 6 chiffres à", "enter": "Se connecter", "other_email": "Autre e-mail / renvoyer",
           "request_sent": "✓ Demande envoyée", "pending": "Votre compte est en attente de validation. Vous recevrez un e-mail dès qu'il sera validé.",
           "back": "Retour", "password": "Mot de passe", "back_to_email": "Retour à la connexion par e-mail",
           "legacy_link": "Connexion par mot de passe (temporaire)", "ok": "OK", "generic_err": "Une erreur est survenue — réessayez",
           "code_len": "Le code comporte 6 chiffres", "wrong_password": "Mot de passe incorrect",
           "err_invalid_email": "Adresse e-mail invalide", "err_send_failed": "L'e-mail n'a pas pu être envoyé — réessayez dans une minute",
           "err_expired": "Le code a expiré — demandez-en un nouveau", "err_too_many": "Trop de tentatives — demandez un nouveau code",
           "err_wrong_code": "Code incorrect", "err_pending": "Votre compte est en attente de validation"},
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
button.cookie-link{position:fixed;bottom:12px;left:50%;transform:translateX(-50%);
width:auto;background:none;color:#4a4a5a;font-weight:400;font-size:0.7rem;
padding:0.2rem;text-decoration:underline}
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

<div id="step-email">
  <p data-i18n="enter_email">הכנס מייל ונשלח לך קוד כניסה</p>
  <input type="email" id="email" placeholder="you@example.com" autocomplete="email" dir="ltr">
  <button id="send-btn" onclick="sendCode()" data-i18n="send_code">שלח קוד</button>
</div>

<div id="step-code" hidden>
  <p><span data-i18n="sent_to">שלחנו קוד בן 6 ספרות אל</span><br><b id="sent-to" dir="ltr"></b></p>
  <input id="code" inputmode="numeric" autocomplete="one-time-code" maxlength="6" placeholder="••••••" dir="ltr">
  <button id="verify-btn" onclick="verify()" data-i18n="enter">כניסה</button>
  <button class="link" onclick="back()" data-i18n="other_email">מייל אחר / שלח שוב</button>
</div>

<div id="step-pending" hidden>
  <p class="ok" data-i18n="request_sent">✓ הבקשה נשלחה</p>
  <p data-i18n="pending">החשבון ממתין לאישור. תקבל מייל ברגע שהוא יאושר.</p>
  <button class="link" onclick="back()" data-i18n="back">חזרה</button>
</div>

<div id="step-legacy" hidden>
  <input type="password" id="pw" placeholder="סיסמה">
  <button onclick="legacy()" data-i18n="enter">כניסה</button>
  <button class="link" onclick="back()" data-i18n="back_to_email">חזרה לכניסה במייל</button>
</div>

<div class="err" id="err"></div>
<!--LEGACY--><button class="link" id="legacy-link" onclick="show('step-legacy')" data-i18n="legacy_link">כניסה עם סיסמה (זמני)</button><!--/LEGACY-->
</div>
<button class="cookie-link" onclick="openCookies()">Cookie settings</button>
<div class="cookie-overlay" id="cookie-overlay" hidden
     onclick="if (event.target === this) closeCookies()">
  <div class="cookie-box"><div id="cookie-body"></div>
    <button onclick="closeCookies()" data-i18n="ok">אישור</button></div>
</div>
<script>
const $ = id => document.getElementById(id);
// ── שפה (אותה בחירה כמו באפליקציה — נשמרת במכשיר) ──
const L = __LOGIN_I18N__;
let LANG = 'he';
try { LANG = localStorage.getItem('sf:lang') || 'he'; } catch (e) {}
if (!L[LANG]) LANG = 'he';
const t = k => (L[LANG] || {})[k] ?? L.he[k] ?? k;
function applyLang() {
  document.documentElement.lang = LANG;
  document.documentElement.dir = LANG === 'he' ? 'rtl' : 'ltr';
  document.title = 'SpoilerFree — ' + t('title');
  document.querySelectorAll('[data-i18n]').forEach(el => { el.textContent = t(el.dataset.i18n); });
  $('pw').placeholder = t('password');
  $('lang-select').value = LANG;
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
function show(id) {
  for (const s of ['step-email','step-code','step-pending','step-legacy']) $(s).hidden = s !== id;
  $('err').textContent = '';
}
function back() { show('step-email'); $('email').focus(); }
async function post(url, body) {
  const r = await fetch(url, {method:'POST', headers:{'Content-Type':'application/json'},
                              body: JSON.stringify(body)});
  let j = {}; try { j = await r.json(); } catch (e) {}
  if (!r.ok) throw new Error(serverMsg(j.detail));
  return j;
}
async function sendCode() {
  const email = $('email').value.trim();
  if (!email) return;
  $('send-btn').disabled = true; $('err').textContent = '';
  try {
    const j = await post('/auth/request_code', {email, lang: LANG});
    if (j.status === 'pending') { show('step-pending'); return; }
    $('sent-to').textContent = email; show('step-code'); $('code').focus();
  } catch (e) { $('err').textContent = e.message; }
  finally { $('send-btn').disabled = false; }
}
async function verify() {
  const code = $('code').value.trim();
  if (code.length !== 6) { $('err').textContent = t('code_len'); return; }
  $('verify-btn').disabled = true; $('err').textContent = '';
  try {
    await post('/auth/verify', {email: $('email').value.trim(), code});
    location.href = '/?fresh=1';
  } catch (e) { $('err').textContent = e.message; }
  finally { $('verify-btn').disabled = false; }
}
async function legacy() {
  try { await post('/login', {password: $('pw').value}); location.href = '/?fresh=1'; }
  catch (e) { $('err').textContent = t('wrong_password'); }
}
async function openCookies() {
  $('cookie-overlay').hidden = false;
  try { $('cookie-body').innerHTML = await (await fetch('/cookies?lang=' + LANG)).text(); } catch (e) {}
}
function closeCookies() { $('cookie-overlay').hidden = true; }
$('email').addEventListener('keydown', e => { if (e.key === 'Enter') sendCode(); });
$('code').addEventListener('keydown', e => { if (e.key === 'Enter') verify(); });
$('code').addEventListener('input', e => { if (e.target.value.trim().length === 6) verify(); });
$('pw').addEventListener('keydown', e => { if (e.key === 'Enter') legacy(); });
$('email').focus();
</script></body></html>"""


def render_login_page() -> str:
    page = LOGIN_PAGE.replace("__LOGIN_I18N__", json.dumps(LOGIN_I18N, ensure_ascii=False))
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
<div class="sub"><a href="/">← חזרה לאפליקציה</a></div>
<div class="kpis" id="kpis"></div>
<div class="wrap"><table>
<thead><tr><th>מייל</th><th>סטטוס</th><th>נרשם</th><th>כניסה אחרונה</th>
<th>כניסות</th><th>פתיחות אפליקציה</th><th>משחקים שנפתחו</th><th>תקצירים שנצפו</th>
<th>ליגות מובילות</th><th>פעילות אחרונה</th><th></th></tr></thead>
<tbody id="rows"><tr><td colspan="11" class="muted">טוען...</td></tr></tbody>
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
    const lg = (u.top_leagues || []).map(l => LEAGUES[l] || esc(l)).join(', ') || '<span class="muted">—</span>';
    return `<tr><td dir="ltr">${e}${u.is_admin ? ' ⭐' : ''}</td>
      <td><span class="st ${u.status}">${ST[u.status] || u.status}</span></td>
      <td>${when(u.created_at)}</td><td>${when(u.last_login)}</td>
      <td>${u.login_count || 0}</td><td>${u.app_open || 0}</td><td>${u.match_open || 0}</td>
      <td>${u.highlight_play || 0}</td><td>${lg}</td><td>${when(u.last_active)}</td>
      <td>${u.is_admin ? '' : btns}</td></tr>`;
  }).join('') || '<tr><td colspan="11" class="muted">אין משתמשים עדיין</td></tr>';
}
async function setStatus(email, status) {
  const r = await fetch('/admin/api/users/' + encodeURIComponent(email), {
    method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({status})});
  if (!r.ok) alert('נכשל'); load();
}
load();
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


class _LibsqlConn:
    """עוטף חיבור libsql כך שיתנהג כמו sqlite3 עם row_factory=Row.
    commit() גם מסנכרן מול הענן, כדי שקריאות עוקבות יראו את הכתיבה."""

    def __init__(self, conn):
        self._conn = conn

    def execute(self, sql, params=()):
        return _LibsqlCursor(self._conn.execute(sql, tuple(params)))

    def executemany(self, sql, seq):
        self._conn.executemany(sql, [tuple(p) for p in seq])

    def commit(self):
        self._conn.commit()
        try:
            self._conn.sync()
        except Exception as e:
            print(f"[turso] sync after commit failed: {e}")

    def close(self):
        try:
            self._conn.close()
        except Exception:
            pass


def get_db():
    if TURSO_DATABASE_URL and libsql is not None:
        # embedded replica: קובץ מקומי (קריאות מהירות) שמסונכרן ל-Turso.
        # connect() כבר מבצע סנכרון מהענן — אחרי deploy (דיסק ריק) הוא
        # מושך את כל ה-DB; אחר כך המשיכות אינקרמנטליות וזולות.
        try:
            conn = libsql.connect("turso_replica.db",
                                  sync_url=TURSO_DATABASE_URL,
                                  auth_token=TURSO_AUTH_TOKEN)
            return _LibsqlConn(conn)
        except Exception as e:
            # Turso לא זמין? האתר ממשיך על sqlite מקומי במקום ליפול
            print(f"[turso] connect failed — falling back to local sqlite: {e}")

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

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
    premier_clubs = [
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
               "date_utc", "time_utc", "venue", "matchday", "status")


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
            if all(old[c] == v[c] for c in _MATCH_COLS):
                continue
        writes.append((mid, league_key, *(v[c] for c in _MATCH_COLS), now))

    deletes = []
    if purge and incoming:
        for mid, old in existing.items():
            if mid in incoming:
                continue
            if hard or (old["status"] not in _OVER_STATUSES
                        and not str(mid).startswith("manual-")):
                deletes.append((mid,))

    if deletes:
        conn.executemany("DELETE FROM matches WHERE id=?", deletes)
    if writes:
        conn.executemany("""
            INSERT OR REPLACE INTO matches
            (id, league_key, home_team, away_team, home_team_id, away_team_id,
             date_utc, time_utc, venue, matchday, status, fetched_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
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
        rows[str(event_id)] = {
            "home_team": e.get("strHomeTeam"), "away_team": e.get("strAwayTeam"),
            "home_team_id": None, "away_team_id": None,
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
        rows[str(m["id"])] = {
            "home_team": m["homeTeam"]["name"], "away_team": m["awayTeam"]["name"],
            "home_team_id": str(m["homeTeam"]["id"]),
            "away_team_id": str(m["awayTeam"]["id"]),
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


def display_team(name: str, lang: str = "he") -> str:
    """שם הקבוצה כפי שמוצג למשתמש בשפה שבחר."""
    if not name:
        return name
    if lang == "he":
        return TEAM_NAMES["he"].get(name) or to_hebrew_team(name)
    return TEAM_NAMES.get(lang, {}).get(name) or _short_en(name)


# ── מפתח קבוצה אחיד (למועדפים — אותה קבוצה בכל מפעל) ───
# "Liverpool FC" (football-data, פרמייר) = "Liverpool" (TheSportsDB, צ'מפיונס).
TEAM_KEY_ALIASES = {
    "tottenham hotspur": "tottenham",
    "brighton hove albion": "brighton",
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


def is_match_highlight(title: str, home: str, away: str,
                       home_alt: str = None, away_alt: str = None,
                       require_team: bool = False,
                       implicit_team: str = None) -> bool:
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
        if any(a in t for a in TEAM_ALIASES.get(team, [])):
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
                     "fifaworldcup", "full match", "resumen",
                     "zusammenfassung",
                     # ליג 1: הפורמט "TEAM - TEAM () | Week N" בלי מילת
                     # תקציר; resume/journee = Résumé/journée אחרי deaccent
                     "week", "resume", "journee",
                     # ערוצי מועדונים: טורקית (özet = תקציר, hafta = מחזור),
                     # הולנדית, איטלקית, פורטוגזית
                     "ozet", "hafta", "samenvatting", "sintesi",
                     "resumo", "melhores momentos",
                     # סלובקית (Slovan Bratislava: "ZOSTRIH | PSG – ŠK Slovan")
                     "zostrih"])
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


def _video_durations(video_ids: list) -> dict:
    """videos.list — משך כל וידאו בשניות. יחידת quota אחת לעד 50 IDs."""
    if not video_ids or not YOUTUBE_API_KEY or _yt_units_today() >= YT_DAILY_BRAKE:
        return {}
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


def search_youtube(home: str, away: str, match_date: str,
                   channel_id: str, query: str = None,
                   title_exclude: list = None,
                   title_include: list = None,
                   home_alt: str = None, away_alt: str = None,
                   require_team: bool = False,
                   implicit_team: str = None,
                   headline: bool = False,
                   il_both: bool = False) -> list:
    """Search YouTube for match highlights. Returns list of videos."""
    if not channel_id:
        return []

    def _keep(title: str, published: str = "") -> bool:
        tl = title.lower()
        # סינון ברמת המקור (למשל: רק הגרסה בספרדית של Fanatiz)
        if title_exclude and any(x.lower() in tl for x in title_exclude):
            return False
        if title_include and not any(x.lower() in tl for x in title_include):
            return False
        if il_both:    # ערוצים ישראליים לא רשמיים — כלל מחמיר
            return is_il_both_teams(title, home_alt or home, away_alt or away,
                                    published, match_date)
        if headline:   # ONE — כותרות חדשותיות בעברית
            return is_headline_highlight(title, home_alt or home, away_alt or away,
                                         published, match_date)
        return is_match_highlight(title, home, away, home_alt, away_alt,
                                  require_team, implicit_team)

    def _video(video_id: str, title: str) -> dict:
        tl = title.lower()
        return {"video_id": video_id,
                "extended": "extended" in tl or "מורחב" in title,
                "_title":   tl}

    # 1. RSS (חינם). אם הפיד מגיע אחורה עד יום המשחק ואין בו תקציר —
    #    התקציר פשוט עוד לא עלה, ואין טעם לשלם על חיפוש.
    results = None
    feed = _rss_feed(channel_id)
    if feed is not None:
        results = [_video(v, t) for v, t, p in feed
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
        if not YOUTUBE_API_KEY:
            return []
        if _yt_units_today() >= YT_DAILY_BRAKE:
            # None = לא נשמר בקאש כ"לא נמצא" — יחפש שוב אחרי האיפוס היומי
            print(f"[yt] daily brake {YT_DAILY_BRAKE} reached — no API for {channel_id}")
            return None

        # 2א. רשימת ההעלאות: יחידה לכל 50 סרטונים
        uploads = _uploads_since(channel_id, match_date)
        if uploads is not None:
            items_u, complete = uploads
            results = [_video(v, t) for v, t, p in items_u if v and _keep(t, p)]
            if not results and not complete:
                # הרשימה לא הגיעה עד יום המשחק — אחרת היה נקבע "לא נמצא" בטעות
                print(f"[yt] uploads cap before {match_date} — falling back to search")
                uploads = None
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
            results = [_video(item["id"]["videoId"], t) for item in items
                       for t in [_unescape(item["snippet"]["title"])]
                       if _keep(t, item["snippet"].get("publishedAt", ""))]

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
        regular = next((v for v in pool if not v["extended"]), None)
        for v in (regular, titled_ext):
            if v:
                final.append({"video_id": v["video_id"],
                              "label": "תקציר מורחב" if v["extended"] else "תקציר",
                              "extended": v["extended"]})
    return final


def get_sources_for_match(row) -> list:
    league_key = row["league_key"]
    league     = LEAGUES.get(league_key, {})

    if "club_channels" in league:
        # צ'מפיונס: ערוצי שני המועדונים (לפי שם ב-sportsdb), ואחריהם מקורות
        # הליגה. club_team: בערוץ של מועדון, שמו לא חייב להופיע בכותרת.
        cc = league["club_channels"]
        q = f"{row['home_team']} {row['away_team']}"
        club_sources = [
            {"id": f"club_{_fixture_slug(team)}", "name": to_hebrew_team(team),
             "channel_id": cc[team], "allow_embed": False,
             "query_override": q, "club_team": team}
            for team in (row["home_team"], row["away_team"]) if team in cc]
        return club_sources + league.get("sources", [])

    if "sources" in league:
        return league["sources"]

    # Premier League — search by club tier
    conn = get_db()
    home_club = conn.execute(
        "SELECT * FROM clubs WHERE fd_team_id=? AND league_key=?",
        (row["home_team_id"], league_key)
    ).fetchone()
    away_club = conn.execute(
        "SELECT * FROM clubs WHERE fd_team_id=? AND league_key=?",
        (row["away_team_id"], league_key)
    ).fetchone()
    conn.close()

    clubs = []
    for club in [home_club, away_club]:
        if club and club["yt_channel_id"]:
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

    club_sources = [{"id": f"club_{c['id']}", "name": c["short_name"],
                     "channel_id": c["yt_channel_id"], "allow_embed": False,
                     "query_override": short_q}
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


COOKIES_HTML = """<h2>הגדרות עוגיות ופרטיות</h2>
<p>אנחנו משתמשים בעוגיות ובטכנולוגיות דומות כדי שהאתר יעבוד, כדי לזכור את
ההתחברות שלך וכדי לשפר את השירות.</p>
<h3>עוגיות הכרחיות</h3>
<p>נדרשות להתחברות ולאבטחה (עוגיית התחברות למשך עד 90 יום). אי אפשר לבטל אותן.</p>
<h3>אחסון מקומי</h3>
<p>לוח המשחקים והדף נשמרים במכשיר שלך, כדי שהאתר ייפתח מהר גם בחיבור חלש.</p>
<h3>נתוני שימוש</h3>
<p>אנחנו שומרים את כתובת המייל שלך, מועדי התחברות, ואילו ליגות, משחקים ותקצירים
פתחת — לצורך תפעול ושיפור השירות. המידע לא נמכר ולא מועבר לצדדים שלישיים.</p>
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


@app.get("/matches/{league_key}")
def get_matches(request: Request, league_key: str,
                refresh: bool = False, matchday: int = None, lang: str = "he"):
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
    conn.close()

    # ליגה ריקה לגמרי — שליפה ראשונה
    if not rows and not matchday and not refresh:
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
            "status":   row["status"],
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
def get_matches_by_date(request: Request, date_il: str, lang: str = "he"):
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
            # הפתיחה עברה מזמן אבל לא מסומן כגמור — הדפדפן ירענן את הליגה
            "needs_refresh": not is_over(row["status"]) and kickoff_passed(row),
        })
    matches.sort(key=lambda m: (order.get(m["league_key"], 99), m["time"]))
    heb = ["שני", "שלישי", "רביעי", "חמישי", "שישי", "שבת", "ראשון"]
    return {"date": day.isoformat(), "weekday": heb[day.weekday()],
            "count": len(matches), "matches": matches}


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


def _not_found_retry(row):
    """אחרי כמה זמן לחפש שוב כש"לא נמצא" — לפי גיל המשחק. None = לא מחפשים
    שוב (משחק בן שבוע+ — התקציר כבר לא יעלה; "חפש שוב" עדיין עובד)."""
    try:
        kick = datetime.fromisoformat(f"{row['date_utc']}T{row['time_utc']}+00:00")
    except Exception:
        return timedelta(minutes=30)
    match_age = datetime.now(timezone.utc) - kick
    if match_age < timedelta(days=2):
        return timedelta(minutes=30)
    if match_age < timedelta(days=7):
        return timedelta(hours=6)
    return None


def _source_highlights(row, source) -> dict:
    """תקציר ממקור אחד למשחק: מהקאש, או חיפוש ושמירה בקאש.
    משותף ל-/highlights ולחיפוש-מראש ברקע."""
    match_id    = row["id"]
    source_id   = source["id"]
    channel_id  = source.get("channel_id", "")
    allow_embed = source.get("allow_embed", False)
    base = {"source_id": source_id, "name": source["name"], "allow_embed": allow_embed}

    if not channel_id:
        return {**base, "videos": [], "status": "no_channel"}

    conn = get_db()
    cached = conn.execute(
        "SELECT videos_json, found_at FROM highlight_cache WHERE match_id=? AND source_id=?",
        (match_id, source_id)
    ).fetchone()
    conn.close()

    if cached:
        videos = json.loads(cached["videos_json"])
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
    )
    if videos is None:
        # שגיאת API / בלם יומי — לא שומרים בקאש, ינוסה שוב בהמשך
        return {**base, "videos": [], "status": "api_error"}

    conn = get_db()
    conn.execute("""
        INSERT OR REPLACE INTO highlight_cache
        (match_id, source_id, videos_json, found_at)
        VALUES (?,?,?,?)
    """, (match_id, source_id, json.dumps(videos),
          datetime.now(timezone.utc).isoformat()))
    conn.commit()
    conn.close()
    return {**base, "videos": videos, "status": "found" if videos else "not_found"}


# ── חיפוש מראש ברקע ────────────────────────────────────
# משחקים שהסתיימו ב-48 השעות האחרונות ועוד אין להם קאש — השרת מחפש לבד.
# התקציר מוכן לפני שמישהו פותח, והעלות תלויה במספר המשחקים — לא במשתמשים.
PREFETCH_EVERY_MIN   = 30
PREFETCH_MAX_MATCHES = 20


def prefetch_highlights_once() -> int:
    since = (datetime.now(timezone.utc) - timedelta(hours=48)).strftime("%Y-%m-%d")
    conn = get_db()
    rows = conn.execute("SELECT * FROM matches WHERE date_utc >= ?", (since,)).fetchall()
    have = {(r["match_id"], r["source_id"]) for r in
            conn.execute("SELECT match_id, source_id FROM highlight_cache").fetchall()}
    conn.close()
    done = 0
    for row in rows:
        if done >= PREFETCH_MAX_MATCHES:
            break
        if not likely_over(row) or kickoff_passed(row, hours=48):
            continue
        todo = [s for s in get_sources_for_match(row)
                if s.get("channel_id") and (row["id"], s["id"]) not in have]
        if not todo:
            continue
        if _yt_units_today() >= YT_DAILY_BRAKE:
            break
        for s in todo:
            _source_highlights(row, s)
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


@app.get("/highlights/{match_id}")
def get_highlights(request: Request, match_id: str, lang: str = "he"):
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

    # קישורי אתר (same-day): השרת מחלץ את הכתבה הישירה ושומר בקאש
    league = LEAGUES.get(row["league_key"], {})
    web_links = []
    for w in league.get("web_sources", []):
        wq = w["query"].format(home=to_hebrew_team(row["home_team"]),
                               away=to_hebrew_team(row["away_team"]))
        cache_key = f"web_{w['name']}"

        conn = get_db()
        cached = conn.execute(
            "SELECT videos_json FROM highlight_cache WHERE match_id=? AND source_id=?",
            (match_id, cache_key)
        ).fetchone()
        conn.close()

        if cached:
            url = json.loads(cached["videos_json"])["url"]
        else:
            # 1. עמודי האתר עצמו (VOD/ליגה) — קישור ישיר, בלי מנוע חיפוש
            url = None
            if w.get("scrape_pages"):
                url = find_web_highlight(w["scrape_pages"], w["link_pattern"],
                                         _he_names(row["home_team"]),
                                         _he_names(row["away_team"]),
                                         base=w.get("base", ""))
            # 2. Google CSE — רק אם הוגדר מפתח
            url = url or resolve_web_link(wq, w["domain"])
            if url:
                # קאש רק לקישור ישיר — כישלון ינוסה שוב בפתיחה הבאה
                conn = get_db()
                conn.execute("""
                    INSERT OR REPLACE INTO highlight_cache
                    (match_id, source_id, videos_json, found_at)
                    VALUES (?,?,?,?)
                """, (match_id, cache_key, json.dumps({"url": url}),
                      datetime.now(timezone.utc).isoformat()))
                conn.commit()
                conn.close()
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
    conn.execute("DELETE FROM highlight_cache WHERE match_id=? AND found_at<?",
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
    """השורה הגולמית של משחק מה-DB — סטטוס, תאריך, מתי נשלף."""
    require_admin(request)
    conn = get_db()
    rows = conn.execute(
        "SELECT id, league_key, home_team, away_team, date_utc, time_utc, "
        "matchday, status, fetched_at FROM matches "
        "WHERE home_team LIKE ? OR away_team LIKE ? "
        "ORDER BY date_utc DESC LIMIT 5",
        (f"%{q}%", f"%{q}%")
    ).fetchall()
    conn.close()
    return {"matches": [dict(r) for r in rows]}


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

def _email_from(payload) -> str:
    email = str(payload.get("email") or "").strip().lower()
    if len(email) > 200 or not EMAIL_RE.match(email):
        raise HTTPException(400, "כתובת מייל לא תקינה")
    return email


@app.post("/auth/request_code")
def auth_request_code(payload: dict = Body(...)):
    email = _email_from(payload)
    now = _now()
    is_admin_email = email in ADMIN_EMAILS
    conn = get_db()
    user = conn.execute("SELECT status FROM users WHERE email=?", (email,)).fetchone()
    new_pending = False
    if user is None:
        status = "approved" if is_admin_email else "pending"
        conn.execute(
            "INSERT INTO users (email, status, is_admin, created_at, approved_at, login_count) "
            "VALUES (?,?,?,?,?,0)",
            (email, status, int(is_admin_email), now.isoformat(),
             now.isoformat() if is_admin_email else None))
        conn.commit()
        new_pending = status == "pending"
    else:
        status = user["status"]
        if is_admin_email and status != "approved":
            conn.execute("UPDATE users SET status='approved', is_admin=1 WHERE email=?", (email,))
            conn.commit()
            status = "approved"
    if status != "approved":
        conn.close()
        if new_pending:
            _notify_admins_new_user(email)
        # ממתין או חסום — אותה תשובה (לא חושפים חסימה)
        return {"status": "pending"}

    row = conn.execute("SELECT sent_at FROM login_codes WHERE email=?", (email,)).fetchone()
    if row:
        try:
            if (now - datetime.fromisoformat(row["sent_at"])).total_seconds() < CODE_RESEND_SEC:
                conn.close()
                return {"status": "code_sent"}   # נשלח לפני פחות מדקה — משתמשים בו
        except Exception:
            pass
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
    user = conn.execute("SELECT status FROM users WHERE email=?", (email,)).fetchone()
    if not user or user["status"] != "approved":
        conn.close()
        raise HTTPException(403, "החשבון ממתין לאישור")

    token = secrets.token_urlsafe(32)
    conn.execute("DELETE FROM login_codes WHERE email=?", (email,))
    conn.execute("INSERT INTO sessions (token_hash, email, created_at, expires_at) VALUES (?,?,?,?)",
                 (_sha(token), email, now.isoformat(),
                  (now + timedelta(days=SESSION_DAYS)).isoformat()))
    conn.execute("UPDATE users SET last_login=?, login_count=COALESCE(login_count,0)+1 WHERE email=?",
                 (now.isoformat(), email))
    conn.execute("INSERT INTO events (email, ts, type) VALUES (?,?,'login')", (email, now.isoformat()))
    conn.commit()
    conn.close()
    resp = JSONResponse({"ok": True})
    resp.set_cookie("sf_session", token, max_age=SESSION_DAYS * 24 * 3600,
                    httponly=True, samesite="lax", secure=bool(os.environ.get("RENDER")))
    return resp


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
    return {"auth_on": AUTH_ON, "email": u.get("email"),
            "is_admin": bool(u.get("is_admin")) or not AUTH_ON,
            "legacy": bool(u.get("legacy"))}


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
    for table in ("events", "sessions", "login_codes", "favorites", "users"):
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
        return {"favorites": [], "per_device": True}
    conn = get_db()
    rows = conn.execute("SELECT team FROM favorites WHERE email=? ORDER BY team",
                        (email,)).fetchall()
    conn.close()
    return {"favorites": [r["team"] for r in rows]}


@app.post("/favorites")
def set_favorite(request: Request, payload: dict = Body(...)):
    require_auth(request)
    email = (current_user(request) or {}).get("email")
    if not email:
        raise HTTPException(400, "בלי חשבון אישי — המועדפים נשמרים במכשיר")
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


# ── Admin: משתמשים ─────────────────────────────────────

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


@app.get("/app")
def serve_frontend(request: Request):
    if not is_authed(request):
        return HTMLResponse(render_login_page())
    # X-SF-App: ה-service worker שומר בקאש רק את הדף הזה, לא את מסך הכניסה
    return FileResponse("index.html", headers={"X-SF-App": "1"})


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
