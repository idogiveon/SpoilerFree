import sqlite3
import requests
import re
import os
import json
import hashlib
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
             "allow_embed": False},
            {"id": "sport5", "name": "ערוץ הספורט",
             "channel_id": "UCyXf5cz6E9IIL40aivg7tOw",
             "search_template": "תקציר {home} {away}",
             "allow_embed": False},
            {"id": "ipfl", "name": "ליגת העל",
             "channel_id": "UCxjaVFauWASy0CuJfHKZeiw",
             "search_template": "{home} {away}",
             "allow_embed": False},
        ],
    },
    "bundesliga": {
        "name": "בונדסליגה",
        "source": "sportsdb",
        "sportsdb_ids": ["4331"],
        "sportsdb_season": "2026-2027",
        "sources": [
            {"id": "bundesliga_official", "name": "Bundesliga",
             "channel_id": "", "search_template": "{home} {away} highlights",
             "allow_embed": False},
        ],
    },
    "laliga": {
        "name": "לה ליגה",
        "source": "sportsdb",
        "sportsdb_ids": ["4335"],
        "sportsdb_season": "2026-2027",
        "sources": [
            {"id": "laliga_official", "name": "LALIGA",
             "channel_id": "", "search_template": "{home} {away} resumen",
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
             "channel_id": "", "search_template": "{home} {away} highlights",
             "allow_embed": False},
        ],
    },
    "ucl": {
        "name": "צ'מפיונס ליג",
        "source": "sportsdb",
        "sportsdb_ids": ["4480"],
        "sportsdb_season": "2026-2027",
        "sources": [
            {"id": "ucl_official", "name": "UEFA",
             "channel_id": "", "search_template": "{home} {away} highlights",
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

def get_db():
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

    # מועדוני פרמייר ליג 2026-27 — ערוצים מופו ואומתו ידנית (29/8/26).
    # הקוד הוא מקור האמת: בכל עלייה הטבלה נבנית מחדש מהרשימה הזו.
    premier_clubs = [
        ("PL-fd57",   "Arsenal FC",                "Arsenal",        "premier", 1, "UCpryVRk_VDudG8SHXgWcG0w", "57"),
        ("PL-fd61",   "Chelsea FC",                "Chelsea",        "premier", 1, "UCF5ZHdBHgQFvCDMxnLNEDsQ", "61"),
        ("PL-fd64",   "Liverpool FC",              "Liverpool",      "premier", 1, "UCNCHLOFZu2hEBbGVDzUBiTQ", "64"),
        ("PL-fd65",   "Manchester City FC",        "Man City",       "premier", 1, "UCmIBDP4OFjJcQZ1pNWMArFg", "65"),
        ("PL-fd66",   "Manchester United FC",      "Man United",     "premier", 1, "UCSmqU7bLAEFMsq9hHgqlILg", "66"),
        ("PL-fd73",   "Tottenham Hotspur FC",      "Spurs",          "premier", 1, "UCEm2zHMGFxaFDRMHEbxZ5dw", "73"),
        ("PL-fd1044", "AFC Bournemouth",           "Bournemouth",    "premier", 2, "UCeOCuVSSweaEj6oVtJZEKQw", "1044"),
        ("PL-fd58",   "Aston Villa FC",            "Aston Villa",    "premier", 2, "UCnGMrEJdFn8aXzWjIiXpEaA", "58"),
        ("PL-fd402",  "Brentford FC",              "Brentford",      "premier", 2, "UCAalMUm3LIf504ItA3rqfug", "402"),
        ("PL-fd397",  "Brighton & Hove Albion FC", "Brighton",       "premier", 2, "UCf-cpC9WAdOsas19JHipukA", "397"),
        ("PL-fd1076", "Coventry City FC",          "Coventry",       "premier", 2, "UCch_NWdo3JWKngAyO9XlycA", "1076"),
        ("PL-fd354",  "Crystal Palace FC",         "Crystal Palace", "premier", 2, "UCWB9N0012fG6bGyj486Qxmg", "354"),
        ("PL-fd62",   "Everton FC",                "Everton",        "premier", 2, "UCtK4QAczAN2mt2ow_jlGinQ", "62"),
        ("PL-fd63",   "Fulham FC",                 "Fulham",         "premier", 2, "UC2VLfz92cTT8jHIFOecC-LA", "63"),
        ("PL-fd322",  "Hull City AFC",             "Hull",           "premier", 2, "UC8MRV5E-Bi5qWomGjOF0ZQg", "322"),
        ("PL-fd349",  "Ipswich Town FC",           "Ipswich",        "premier", 2, "UCjNwxJec96lMWgCXjEDhXgQ", "349"),
        ("PL-fd341",  "Leeds United FC",           "Leeds",          "premier", 2, "UCyQcJHDN4uYfPa1DHzKVSnw", "341"),
        ("PL-fd67",   "Newcastle United FC",       "Newcastle",      "premier", 2, "UCf6RkTMfvn2LFnbX5CqNkBw", "67"),
        ("PL-fd351",  "Nottingham Forest FC",      "Forest",         "premier", 2, "UCyAxjuAr8f_BFDGCO3Htbxw", "351"),
        ("PL-fd71",   "Sunderland AFC",            "Sunderland",     "premier", 2, "UCrw-7k6yJc0EMJdf-0BAkoQ", "71"),
    ]

    # ניקוי שורות ישנות (סגלים קודמים) והכנסה מחדש — דטרמיניסטי
    conn.execute("DELETE FROM clubs WHERE league_key='premier'")
    conn.executemany("""
        INSERT OR REPLACE INTO clubs
        (id, name, short_name, league_key, tier, yt_channel_id, fd_team_id)
        VALUES (?,?,?,?,?,?,?)
    """, premier_clubs)

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
        conn.execute("DELETE FROM matches WHERE league_key=?", (league_key,))

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
        conn.execute("DELETE FROM matches WHERE league_key=?", (league_key,))
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

# ── YouTube ────────────────────────────────────────────

# Regex to detect scores in titles like "2-0", "3:1", "(2-1)"
SCORE_PATTERN = re.compile(r'\b\d+\s*[-:]\s*\d+\b')

def clean_title_for_display(title: str) -> str:
    """Remove anything that looks like a score from a video title."""
    return SCORE_PATTERN.sub("", title).strip()

def is_match_highlight(title: str, home: str, away: str) -> bool:
    t = title.lower()

    def clean(team):
        return (team.lower()
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
        # multi-word names like "South Korea"
        if len(words) >= 2 and words[0] in t and words[-1] in t:
            return True
        return False

    exclude = any(w in t for w in
                  ["compilation", "best of", "every goal", "parade", "bts",
                   "training", "press conference", "interview", "#shorts",
                   "season review", "all goals season", "preview",
                   "prediction", "lineup", "tactical", "pre-match",
                   "post-match press", "reaction",
                   "bench cam", "player cam", "fan cam", "tunnel",
                   "pitchside", "pitch side", "behind the scenes",
                   "unseen", "warm up", "warm-up", "arrival", "access all"])

    # "תקציר" בכותרת = תקציר. החיפוש כבר scoped לערוץ הנכון.
    # חשוב: הבדיקה הזו חייבת להיות אחרי הגדרת exclude (UnboundLocalError)
    if "תקציר" in t and not exclude:
        return True

    has_both  = team_in(home) and team_in(away)
    highlight = any(w in t for w in
                    ["highlight", "match", "goals", "extended",
                     "שערים", "sign off", "vs", "v.", "\U0001f19a",
                     "fifaworldcup", "full match", "resumen",
                     "zusammenfassung"])
    return has_both and highlight and not exclude


def search_youtube(home: str, away: str, match_date: str,
                   channel_id: str, query: str = None,
                   title_exclude: list = None,
                   title_include: list = None) -> list:
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
        items = requests.get(
            "https://www.googleapis.com/youtube/v3/search",
            params=params, timeout=10
        ).json().get("items", [])
    except Exception as e:
        print(f"YouTube search error: {e}")
        return []

    results = []
    for item in items:
        title = item["snippet"]["title"]
        tl = title.lower()
        # סינון ברמת המקור (למשל: רק הגרסה בספרדית של Fanatiz)
        if title_exclude and any(x.lower() in tl for x in title_exclude):
            continue
        if title_include and not any(x.lower() in tl for x in title_include):
            continue
        if is_match_highlight(title, home, away):
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

    regular  = next((v for v in pool if not v["extended"]), None)
    extended = next((v for v in pool if v["extended"]),     None)

    final = []
    for v in (regular, extended):
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

    club_sources = [{"id": f"club_{c['id']}", "name": c["short_name"],
                     "channel_id": c["yt_channel_id"], "allow_embed": False}
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

    return {"matches": matches, "count": len(matches)}


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
    # purge: מנקה את הליגה לפני הכנסה — מסלק נתוני עונות ישנות.
    # רק אם הגיעו אירועים, כדי לא למחוק לוח קיים על רענון כושל.
    if payload.get("purge") and events:
        conn.execute("DELETE FROM matches WHERE league_key=?", (league_key,))
    stored = _store_sportsdb_events(conn, league_key, events, now)
    conn.commit()
    conn.close()

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
        return {"available": False, "reason": "המשחק עדיין לא נגמר", "sources": []}

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
            # If cache is empty and older than 30 min, re-search
            cache_age_ok = True
            if not videos:
                try:
                    found_dt = datetime.fromisoformat(cached["found_at"])
                    age = datetime.now(timezone.utc) - found_dt
                    if age > timedelta(minutes=30):
                        cache_age_ok = False
                except:
                    cache_age_ok = False

            if cache_age_ok:
                results.append({"source_id": source_id, "name": source["name"],
                                "videos": videos, "status": "cached",
                                "allow_embed": allow_embed})
                continue

        # Build query from source's search template
        template = source.get("search_template", "{home} {away}")
        query = template.format(home=row["home_team"], away=row["away_team"])

        videos = search_youtube(
            home=row["home_team"],
            away=row["away_team"],
            match_date=row["date_utc"],
            channel_id=channel_id,
            query=query,
            title_exclude=source.get("title_exclude"),
            title_include=source.get("title_include"),
        )

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

    return {
        "available": True,
        "match":     f"{row['home_team']} vs {row['away_team']}",
        "sources":   results,
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

        template = source.get("search_template", "{home} {away}")
        query = template.format(home=home, away=away)
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
            elif not is_match_highlight(title, home, away):
                verdict = "נפסל: לא זוהה כתקציר"
            else:
                verdict = "עבר ✓"
            titles.append({"title": clean_title_for_display(title),
                           "verdict": verdict})
        entry["results"] = titles
        entry["total"] = len(titles)
        report["sources"].append(entry)

    return report


@app.get("/admin/resolve_channel")
def admin_resolve_channel(request: Request, url: str):
    """פותר handle של יוטיוב ל-channel ID, בלי לכתוב כלום.
    שימוש: /admin/resolve_channel?url=@sport1sport2"""
    require_auth(request)
    url = url.strip()
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


# Serve frontend (מוגן בסיסמה — מציג דף כניסה אם אין cookie)
@app.get("/app")
def serve_frontend(request: Request):
    if not is_authed(request):
        return HTMLResponse(LOGIN_PAGE)
    return FileResponse("index.html")


# ── Init ───────────────────────────────────────────────
init_db()
