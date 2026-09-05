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
import hashlib
import unicodedata
from fastapi import FastAPI, HTTPException, Request, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from datetime import datetime, timezone, timedelta

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

DB_PATH = "database.db"
ISRAEL_TZ = timezone(timedelta(hours=3))

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
LEAGUES = {
    "premier": {
        "name": "פרמייר ליג",
        "source": "football-data",
        "fd_code": "PL",
        "fd_season": "2026",
        "default_yt_search": "{home} {away}",
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
        ],
        # קישורי אתר (same-day): קפיצה ישירה לתוצאה הראשונה, בלי גלילה
        "web_sources": [
            {"name": "ספורט 1", "domain": "sport1.maariv.co.il",
             "resolver": "sport1_vod",
             "query": "תקציר {home} {away}"},
            {"name": "וואלה",   "domain": "sports.walla.co.il",
             "query": "תקציר {home} {away}"},
            {"name": "ספורט 5", "domain": "sport5.co.il",
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
            {"id": "one_laliga", "name": "ONE",
             "channel_id": "UCgbHJENV6UgIZl1Rp_GXCfw",
             "search_template": "תקציר {home} {away}",
             "hebrew_names": True,
             "require_team_match": True,
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
            # ONE מתייגים את איטליה באנגלית (ואת ספרד בעברית) — חיפוש אנגלי
            {"id": "one_seriea", "name": "ONE",
             "channel_id": "UCgbHJENV6UgIZl1Rp_GXCfw",
             "search_template": "{home} {away}",
             "require_team_match": True,
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
    },
    "ucl": {
        "name": "צ'מפיונס ליג",
        "source": "sportsdb",
        "sportsdb_ids": ["4480"],
        "sportsdb_season": "2026-2027",
        # אין ערוץ יוטיוב רשמי שמעלה תקצירים של כולם (אומת ידנית 5/9/26) —
        # התקצירים מפוזרים בערוצי הקבוצות (באיחור יום-יומיים).
        # המקור: ספורט 5, המשדרת בישראל — כתבה/VOD ישירים.
        "sources": [],
        "web_sources": [
            {"name": "ספורט 5", "domain": "sport5.co.il",
             "query": "תקציר {home} {away}"},
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

def _auth_token() -> str:
    return hashlib.sha256(APP_PASSWORD.encode()).hexdigest() if APP_PASSWORD else ""

def is_authed(request: Request) -> bool:
    if not APP_PASSWORD:
        return True  # אין סיסמה מוגדרת (פיתוח מקומי) — פתוח
    return request.cookies.get("sf_auth", "") == _auth_token()

def require_auth(request: Request):
    if not is_authed(request):
        raise HTTPException(401, "נדרשת התחברות")

LOGIN_PAGE = """<!DOCTYPE html>
<html lang="he" dir="rtl"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>SpoilerFree — כניסה</title>
<style>
body{background:#0a0a0f;color:#e8e8f0;font-family:sans-serif;display:flex;
align-items:center;justify-content:center;min-height:100vh;margin:0}
.box{background:#13131a;border:1px solid #2a2a3a;border-radius:16px;
padding:2.5rem;text-align:center;max-width:320px;width:90%}
h1{color:#00e5a0;font-size:1.4rem;letter-spacing:2px;margin:0 0 1.5rem}
input{width:100%;padding:0.7rem;border-radius:8px;border:1px solid #2a2a3a;
background:#1a1a24;color:#e8e8f0;font-size:1rem;box-sizing:border-box;
margin-bottom:1rem;text-align:center}
button{width:100%;padding:0.7rem;border-radius:100px;border:none;
background:#00e5a0;color:#000;font-weight:700;font-size:1rem;cursor:pointer}
.err{color:#ff4757;font-size:0.85rem;margin-top:0.8rem;min-height:1.2em}
</style></head><body>
<div class="box"><h1>SPOILERFREE</h1>
<input type="password" id="pw" placeholder="סיסמה" autofocus>
<button onclick="go()">כניסה</button>
<div class="err" id="err"></div></div>
<script>
async function go(){
  const r = await fetch('/login', {method:'POST',
    headers:{'Content-Type':'application/json'},
    body: JSON.stringify({password: document.getElementById('pw').value})});
  if (r.ok) location.reload();
  else document.getElementById('err').textContent = 'סיסמה שגויה';
}
document.getElementById('pw').addEventListener('keydown',
  e => { if (e.key === 'Enter') go(); });
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

def _store_sportsdb_events(conn, league_key: str, events: list, now: str) -> int:
    """Store a list of TheSportsDB events into our matches table."""
    stored = 0
    for e in events:
        event_id = e.get("idEvent")
        if not event_id:
            continue
        status = map_sportsdb_status(e)
        # מגן: endpoint אחד (eventsround) לפעמים מחזיר סטטוס ריק
        # למשחק שכבר ידוע כ-FINISHED — לא מורידים סטטוס אחורה
        if status == "SCHEDULED":
            existing = conn.execute(
                "SELECT status FROM matches WHERE id=?", (event_id,)
            ).fetchone()
            if existing and existing["status"] in ("FINISHED", "LIVE"):
                status = existing["status"]
        matchday = None
        try:
            matchday = int(e.get("intRound") or 0) or None
        except (ValueError, TypeError):
            pass
        conn.execute("""
            INSERT OR REPLACE INTO matches
            (id, league_key, home_team, away_team,
             date_utc, time_utc, venue, matchday, status, fetched_at)
            VALUES (?,?,?,?,?,?,?,?,?,?)
        """, (
            event_id, league_key,
            e.get("strHomeTeam"), e.get("strAwayTeam"),
            e.get("dateEvent"), e.get("strTime") or "00:00:00",
            e.get("strVenue") or "",
            matchday, status, now
        ))
        stored += 1
    return stored


def fetch_football_data(league_key: str, purge: bool = False):
    league = LEAGUES[league_key]
    r = requests.get(
        f"https://api.football-data.org/v4/competitions/{league['fd_code']}/matches",
        headers={"X-Auth-Token": FOOTBALL_DATA_KEY},
        params={"season": league["fd_season"]},
        timeout=15
    )
    matches = r.json().get("matches", [])
    conn = get_db()
    now = datetime.now(timezone.utc).isoformat()

    # purge רק אחרי ששליפה הצליחה — לא מוחקים אם ה-API החזיר ריק
    if purge and matches:
        # purge סלקטיבי: מוחק רק משחקים עתידיים של המקור —
        # היסטוריה שהסתיימה ושורות הלוח הידני לעולם לא נמחקות ברענון
        conn.execute(
            "DELETE FROM matches WHERE league_key=? "
            "AND status NOT IN ('FINISHED','FT','AET','PEN','AP','Match Finished') "
            "AND id NOT LIKE 'manual-%'", (league_key,))

    for m in matches:
        utc_dt = datetime.fromisoformat(m["utcDate"].replace("Z", "+00:00"))
        conn.execute("""
            INSERT OR REPLACE INTO matches
            (id, league_key, home_team, away_team, home_team_id, away_team_id,
             date_utc, time_utc, venue, matchday, status, fetched_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            str(m["id"]), league_key,
            m["homeTeam"]["name"], m["awayTeam"]["name"],
            str(m["homeTeam"]["id"]), str(m["awayTeam"]["id"]),
            utc_dt.strftime("%Y-%m-%d"), utc_dt.strftime("%H:%M:%S"),
            "", m.get("matchday"), m.get("status", "SCHEDULED"), now
        ))

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

    conn = get_db()
    now = datetime.now(timezone.utc).isoformat()
    if purge and all_events:
        # purge סלקטיבי: מוחק רק משחקים עתידיים של המקור —
        # היסטוריה שהסתיימה ושורות הלוח הידני לעולם לא נמחקות ברענון
        conn.execute(
            "DELETE FROM matches WHERE league_key=? "
            "AND status NOT IN ('FINISHED','FT','AET','PEN','AP','Match Finished') "
            "AND id NOT LIKE 'manual-%'", (league_key,))
    _store_sportsdb_events(conn, league_key, all_events, now)
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
        if real:
            r = real[0]
            if (r["date_utc"], r["time_utc"], r["venue"]) != (date_utc, time_utc, venue):
                updates.append((date_utc, time_utc, venue, r["id"]))
            deletes.extend((m["id"],) for m in manual)
        elif manual:
            m = manual[0]
            if (m["date_utc"], m["time_utc"], m["venue"]) != (date_utc, time_utc, venue):
                updates.append((date_utc, time_utc, venue, m["id"]))
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

def fetched_recently(row, minutes: int = 10) -> bool:
    """מגן נגד רענוני-אוטו חוזרים: אם השורה נשלפה ממש עכשיו, אין טעם לנסות שוב."""
    try:
        dt = datetime.fromisoformat(row["fetched_at"])
        return datetime.now(timezone.utc) - dt < timedelta(minutes=minutes)
    except Exception:
        return False

# ── Hebrew team names for YouTube search ──────────────
# ערוצים ישראליים מתייגים בעברית — חיפוש בשמות אנגליים מחזיר ריק.
# התאמה לפי הכלה (case-insensitive), הארוך/ספציפי קודם.
HEB_TEAMS = [
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

def scrape_sport1_vod(home_he: str, away_he: str):
    """קורא את עמוד ה-VOD של ספורט 1 ומאתר את התקציר של המשחק.
    מחזיר URL ישיר לכתבה, או None."""
    try:
        r = requests.get(
            "https://sport1.maariv.co.il/vod/",
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
            timeout=8,
        )
        if r.status_code != 200:
            return None
        html = r.text
        home_v = he_team_variants(home_he)
        away_v = he_team_variants(away_he)
        for m in re.finditer(
                r"<a[^>]+href=['\"]([^'\"]*?/video/\d+[^'\"]*)['\"][^>]*>(.*?)</a>",
                html, re.S):
            href = m.group(1)
            text = re.sub(r"<[^>]+>", " ", m.group(2))
            # מוסיפים גם title= של העוגן אם קיים
            text += " " + (re.search(r'title="([^"]*)"', m.group(0)) or [None, ""])[1]
            if any(v in text for v in home_v) and any(v in text for v in away_v):
                if href.startswith("/"):
                    href = "https://sport1.maariv.co.il" + href
                return href
    except Exception as ex:
        print(f"[sport1vod] {ex}")
    return None


def resolve_web_link(query: str, domain: str):
    """מחלץ URL ישיר לכתבה הראשונה מהדומיין המבוקש.
    מסלול ראשי: Google Custom Search API (אמין, 100/יום חינם).
    גיבוי: DuckDuckGo HTML — עם מפסק זרם כי Render לעיתים חסום שם."""
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

    # מסלול 2: DuckDuckGo, רק אם לא נכשל לאחרונה
    import time as _time
    if _time.time() < _ddg_fail_until[0]:
        return None
    try:
        r = requests.get(
            "https://html.duckduckgo.com/html/",
            params={"q": f"{query} {domain}"},
            headers={"User-Agent": "Mozilla/5.0 (SpoilerFree)"},
            timeout=4,
        )
        links = [unquote(m.group(1))
                 for m in re.finditer(r'uddg=([^&"\']+)', r.text)]
        for url in links:
            if domain in url:
                return url
        # יש תוצאות אבל אף אחת מהדומיין — זו לא תקלת DDG,
        # לא מפעילים מפסק (הדומיין הבא בתור עשוי דווקא להצליח).
        if r.status_code != 200 or not links:
            _ddg_fail_until[0] = _time.time() + 900
    except Exception as ex:
        print(f"[weblink/ddg] {domain}: {ex}")
        _ddg_fail_until[0] = _time.time() + 900
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

def is_match_highlight(title: str, home: str, away: str,
                       home_alt: str = None, away_alt: str = None,
                       require_team: bool = False) -> bool:
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
        if len(words) >= 1 and words[-1] in t:
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
                   "post-match press", "reaction",
                   "bench cam", "player cam", "fan cam", "tunnel",
                   "pitchside", "pitch side", "behind the scenes",
                   "unseen", "warm up", "warm-up", "arrival", "access all",
                   # ליג 1: שידור חוזר של אולפן טרום-משחק
                   "avant-match", "avant match", "tous les buts"])

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
                     "week", "resume", "journee"])
    return has_both and highlight and not exclude


def _video_durations(video_ids: list) -> dict:
    """videos.list — משך כל וידאו בשניות. יחידת quota אחת לעד 50 IDs."""
    if not video_ids:
        return {}
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


def search_youtube(home: str, away: str, match_date: str,
                   channel_id: str, query: str = None,
                   title_exclude: list = None,
                   title_include: list = None,
                   home_alt: str = None, away_alt: str = None,
                   require_team: bool = False) -> list:
    """Search YouTube for match highlights. Returns list of videos."""
    if not YOUTUBE_API_KEY or not channel_id:
        return []

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

    results = []
    for item in items:
        title = item["snippet"]["title"]
        tl = title.lower()
        # סינון ברמת המקור (למשל: רק הגרסה בספרדית של Fanatiz)
        if title_exclude and any(x.lower() in tl for x in title_exclude):
            continue
        if title_include and not any(x.lower() in tl for x in title_include):
            continue
        if is_match_highlight(title, home, away,
                              home_alt, away_alt, require_team):
            results.append({
                "video_id": item["id"]["videoId"],
                "extended": "extended" in tl or "מורחב" in title,
                "_title":   tl,
            })

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
def root():
    return {"status": "SpoilerFree API ✓"}


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
                refresh: bool = False, matchday: int = None):
    require_auth(request)
    if league_key not in LEAGUES:
        raise HTTPException(404, "ליגה לא נמצאה")

    if refresh:
        fetch_and_store(league_key, purge=True)

    conn = get_db()
    count = conn.execute(
        "SELECT COUNT(*) as c FROM matches WHERE league_key=?", (league_key,)
    ).fetchone()["c"]
    conn.close()

    if count == 0:
        fetch_and_store(league_key)

    conn = get_db()
    query  = "SELECT * FROM matches WHERE league_key=?"
    params = [league_key]
    if matchday:
        query += " AND matchday=?"
        params.append(matchday)
    query += " ORDER BY date_utc, time_utc"

    rows = conn.execute(query, params).fetchall()
    conn.close()

    league_name = LEAGUES[league_key]["name"]
    matches = []
    for row in rows:
        il = to_israel_time(row["date_utc"], row["time_utc"])
        matches.append({
            "id":       row["id"],
            "home":     row["home_team"],
            "away":     row["away_team"],
            "date":     il["date"],
            "time":     il["time"],
            "weekday":  il["weekday"],
            "venue":    row["venue"] or "",
            "matchday": row["matchday"],
            "league":   league_name,
            "is_over":  is_over(row["status"]),
            "status":   row["status"],
        })

    # מדד טריות: מתי הליגה רועננה לאחרונה. הפרונט משתמש בזה
    # כדי לרענן אוטומטית בלי לחיצה כשהנתונים מיושנים.
    last_fetch, stale = None, True
    fetch_times = [r["fetched_at"] for r in rows if r["fetched_at"]]
    if fetch_times:
        last_fetch = max(fetch_times)
        try:
            dt = datetime.fromisoformat(last_fetch)
            stale = (datetime.now(timezone.utc) - dt) > timedelta(hours=3)
        except Exception:
            stale = True

    return {"matches": matches, "count": len(matches),
            "stale": stale, "last_fetched": last_fetch}


@app.get("/matches/by_date/{date_il}")
def get_matches_by_date(request: Request, date_il: str):
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
            "date":       il["date"],
            "time":       il["time"],
            "weekday":    il["weekday"],
            "venue":      row["venue"] or "",
            "matchday":   row["matchday"],
            "league":     LEAGUES.get(lk, {}).get("name", lk),
            "league_key": lk,
            "is_over":    is_over(row["status"]),
            "status":     row["status"],
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
    now = datetime.now(timezone.utc).isoformat()
    # purge סלקטיבי: רק משחקים עתידיים — היסטוריה שהסתיימה ושורות
    # הלוח הידני שורדות רענון. לאיפוס מלא (עונה חדשה): "hard": true.
    if payload.get("purge") and events:
        if payload.get("hard"):
            conn.execute("DELETE FROM matches WHERE league_key=?",
                         (league_key,))
        else:
            conn.execute(
                "DELETE FROM matches WHERE league_key=? "
                "AND status NOT IN ('FINISHED','FT','AET','PEN','AP','Match Finished') "
                "AND id NOT LIKE 'manual-%'", (league_key,))
    stored = _store_sportsdb_events(conn, league_key, events, now)
    conn.commit()
    conn.close()

    # הלוח הרשמי הידני גובר על מה שהדפדפן שלח (placeholder-ים וכו')
    if league_key in MANUAL_FIXTURES:
        apply_manual_fixtures(league_key)

    return {"ok": True, "received": len(events), "stored": stored}


@app.get("/highlights/{match_id}")
def get_highlights(request: Request, match_id: str):
    require_auth(request)
    conn = get_db()
    row  = conn.execute("SELECT * FROM matches WHERE id=?", (match_id,)).fetchone()
    conn.close()

    if not row:
        raise HTTPException(404, "משחק לא נמצא")

    if not is_over(row["status"]):
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

        if not is_over(row["status"]):
            if kickoff_passed(row):
                # sportsdb חסום מצד השרת — הרענון חייב לבוא מהדפדפן
                return {"available": False,
                        "reason": "לפי הנתונים המשחק טרם נגמר, אבל שעת הפתיחה "
                                  "כבר עברה — לחץ ↻ רענן מ-API בטאב הליגה ופתח שוב",
                        "sources": []}
            return {"available": False, "reason": "המשחק עדיין לא נגמר",
                    "sources": []}

    sources = get_sources_for_match(row)
    results = []

    for source in sources:
        source_id   = source["id"]
        channel_id  = source.get("channel_id", "")
        allow_embed = source.get("allow_embed", False)

        if not channel_id:
            results.append({"source_id": source_id, "name": source["name"],
                            "videos": [], "status": "no_channel",
                            "allow_embed": allow_embed})
            continue

        # Check cache
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
                found_dt = datetime.fromisoformat(cached["found_at"])
                age = datetime.now(timezone.utc) - found_dt
            except:
                age = None
            if not videos:
                # קאש ריק — ניסיון חוזר אחרי 30 דקות
                if age is None or age > timedelta(minutes=30):
                    cache_age_ok = False
            elif not any(v.get("extended") for v in videos):
                # נמצא רק תקציר קצר — המלא עולה לרוב יום-יומיים אחרי.
                # מרעננים לכל היותר פעם ב-12 שעות, עד 3 ימים מהמציאה.
                if age is not None and timedelta(hours=12) < age < timedelta(days=3):
                    cache_age_ok = False

            if cache_age_ok:
                results.append({"source_id": source_id, "name": source["name"],
                                "videos": videos, "status": "cached",
                                "allow_embed": allow_embed})
                continue

        # Build query: עדיפות לשאילתה מוכנה (שמות קצרים למועדונים),
        # אחרת מתבנית המקור (+ עברית אם צריך)
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
        )

        if videos is None:
            # שגיאת API (מכסה?) — לא שומרים בקאש, ינוסה שוב בפתיחה הבאה
            results.append({"source_id": source_id, "name": source["name"],
                            "videos": [], "status": "api_error",
                            "allow_embed": allow_embed})
            continue

        # Save cache
        conn = get_db()
        conn.execute("""
            INSERT OR REPLACE INTO highlight_cache
            (match_id, source_id, videos_json, found_at)
            VALUES (?,?,?,?)
        """, (match_id, source_id, json.dumps(videos),
              datetime.now(timezone.utc).isoformat()))
        conn.commit()
        conn.close()

        results.append({"source_id": source_id, "name": source["name"],
                        "videos": videos,
                        "status": "found" if videos else "not_found",
                        "allow_embed": allow_embed})

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
            if w.get("resolver") == "sport1_vod":
                # עמוד ה-VOD מציג רק את הכתבות האחרונות — משחק בן שבוע
                # כבר גלל החוצה. אם הסקרייפר החטיא, נופלים לאותו מסלול
                # חילוץ שעובד לוואלה/ספורט 5 לפני שמוותרים לעמוד חיפוש.
                url = (scrape_sport1_vod(to_hebrew_team(row["home_team"]),
                                         to_hebrew_team(row["away_team"]))
                       or resolve_web_link(wq, w["domain"]))
            else:
                url = resolve_web_link(wq, w["domain"])
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
            else:
                url = "https://duckduckgo.com/?q=" + quote(f"{wq} {w['domain']}")
        web_links.append({"name": w["name"], "url": url})

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
    conn = get_db()
    conn.execute("DELETE FROM highlight_cache WHERE match_id=?", (match_id,))
    conn.commit()
    conn.close()
    return {"ok": True, "match_id": match_id}


@app.delete("/cache")
def clear_all_cache(request: Request):
    """Clear ALL highlight cache — useful when debugging."""
    require_auth(request)
    conn = get_db()
    conn.execute("DELETE FROM highlight_cache")
    conn.commit()
    conn.close()
    return {"ok": True}


@app.get("/clubs/{league_key}")
def get_clubs(request: Request, league_key: str):
    require_auth(request)
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM clubs WHERE league_key=? ORDER BY tier, name", (league_key,)
    ).fetchall()
    conn.close()
    return {"clubs": [dict(r) for r in rows]}


@app.put("/clubs/{club_id}/channel")
def update_club_channel(request: Request, club_id: str, channel_id: str):
    require_auth(request)
    conn = get_db()
    conn.execute("UPDATE clubs SET yt_channel_id=? WHERE id=?", (channel_id, club_id))
    conn.commit()
    conn.close()
    return {"ok": True}


@app.get("/debug/db")
def debug_db(request: Request):
    """Quick debug endpoint — shows counts per league."""
    require_auth(request)
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
    require_auth(request)
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
    require_auth(request)
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
    require_auth(request)
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
    require_auth(request)
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
    require_auth(request)

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
    require_auth(request)
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
    require_auth(request)
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
    require_auth(request)
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
    require_auth(request)
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
@app.get("/app")
def serve_frontend(request: Request):
    if not is_authed(request):
        return HTMLResponse(LOGIN_PAGE)
    return FileResponse("index.html")


# ── Init ───────────────────────────────────────────────
init_db()
