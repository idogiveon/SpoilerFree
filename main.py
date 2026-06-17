import sqlite3
import requests
import re
import os
import json
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
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

# ── League config ──────────────────────────────────────
LEAGUES = {
    "worldcup": {
        "name": "מונדיאל 2026",
        "source": "sportsdb",
        "sportsdb_id": "4429",
        "sportsdb_season": "2026",
        "sources": [
            {
                "id": "kan11",
                "name": "כאן 11 🇮🇱",
                "channel_id": "UCKqFqiCe1dCUxRe0_YNZ6gg",
                "search_template": "תקציר {home} {away} מונדיאל",
                "allow_embed": False,
            },
            {
                "id": "fifa",
                "name": "FIFA Official",
                "channel_id": "UCpcTrCXblq78GZrTUTLWeBw",
                "search_template": "{home} {away}",
                "allow_embed": False,
            },
        ],
    },
    "premier": {
        "name": "ליגת פרמייר",
        "source": "football-data",
        "fd_code": "PL",
        "fd_season": "2025",
        "default_yt_search": "{home} {away}",
    },
}

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

    premier_clubs = [
        ("PL-1",  "Arsenal",            "Arsenal",       "premier", 1, "UCpryVRk_VDudG8SHXgWcG0w", "57"),
        ("PL-2",  "Chelsea FC",         "Chelsea",       "premier", 1, "UCF5ZHdBHgQFvCDMxnLNEDsQ", "61"),
        ("PL-3",  "Liverpool FC",       "Liverpool",     "premier", 1, "UCNCHLOFZu2hEBbGVDzUBiTQ", "64"),
        ("PL-4",  "Manchester City",    "Man City",      "premier", 1, "UCmIBDP4OFjJcQZ1pNWMArFg", "65"),
        ("PL-5",  "Manchester United",  "Man United",    "premier", 1, "UCSmqU7bLAEFMsq9hHgqlILg", "66"),
        ("PL-6",  "Tottenham Hotspur", "Spurs",          "premier", 1, "UCEm2zHMGFxaFDRMHEbxZ5dw", "73"),
        ("PL-7",  "Newcastle United",  "Newcastle",      "premier", 2, "UCf6RkTMfvn2LFnbX5CqNkBw", "67"),
        ("PL-8",  "Aston Villa",       "Aston Villa",    "premier", 2, "UCnGMrEJdFn8aXzWjIiXpEaA", "58"),
        ("PL-9",  "Everton FC",        "Everton",        "premier", 2, "", "62"),
        ("PL-10", "West Ham United",   "West Ham",       "premier", 2, "", "563"),
        ("PL-11", "Brighton",          "Brighton",       "premier", 2, "", "397"),
        ("PL-12", "Fulham FC",         "Fulham",         "premier", 2, "", "63"),
        ("PL-13", "Brentford FC",      "Brentford",      "premier", 3, "", "402"),
        ("PL-14", "Crystal Palace",    "Crystal Palace", "premier", 3, "", "354"),
        ("PL-15", "Wolverhampton",     "Wolves",         "premier", 3, "", "76"),
        ("PL-16", "Nottingham Forest", "Forest",         "premier", 3, "", "351"),
        ("PL-17", "AFC Bournemouth",   "Bournemouth",    "premier", 3, "", "1044"),
        ("PL-18", "Leicester City",    "Leicester",      "premier", 3, "", "338"),
        ("PL-19", "Ipswich Town",      "Ipswich",        "premier", 3, "", "349"),
        ("PL-20", "Southampton FC",    "Southampton",    "premier", 3, "", "340"),
    ]

    conn.executemany("""
        INSERT OR IGNORE INTO clubs
        (id, name, short_name, league_key, tier, yt_channel_id, fd_team_id)
        VALUES (?,?,?,?,?,?,?)
    """, premier_clubs)

    conn.commit()
    conn.close()

# ── TheSportsDB status mapping ────────────────────────

def map_sportsdb_status(event: dict) -> str:
    """Map TheSportsDB event to our internal status.
    
    Uses strStatus field, falls back to checking intHomeScore.
    TheSportsDB statuses include:
      "Match Finished", "FT", "AET", "AP" — finished
      "Not Started", "NS" — scheduled
      "Postponed", "Cancelled", "Abandoned"
      Various live statuses: "1H", "HT", "2H", "ET", etc.
    """
    raw = (event.get("strStatus") or "").strip()

    # Finished variants
    if raw in ("Match Finished", "FT", "AET", "AP", "PEN"):
        return "FINISHED"
    
    # Live variants
    if raw in ("1H", "HT", "2H", "ET", "BT", "P", "LIVE"):
        return "LIVE"
    
    # Postponed / cancelled
    if raw in ("Postponed", "PPD"):
        return "POSTPONED"
    if raw in ("Cancelled", "CANC", "Abandoned", "ABD"):
        return "CANCELLED"
    
    # Fallback: if we have scores, it's finished
    if event.get("intHomeScore") is not None and event.get("intAwayScore") is not None:
        return "FINISHED"

    return "SCHEDULED"

# ── Fetch matches ──────────────────────────────────────

def _store_sportsdb_events(conn, league_key: str, events: list, now: str):
    """Store a list of TheSportsDB events into our matches table."""
    for e in events:
        event_id = e.get("idEvent")
        if not event_id:
            continue
        status = map_sportsdb_status(e)
        conn.execute("""
            INSERT OR REPLACE INTO matches
            (id, league_key, home_team, away_team,
             date_utc, time_utc, venue, status, fetched_at)
            VALUES (?,?,?,?,?,?,?,?,?)
        """, (
            event_id, league_key,
            e.get("strHomeTeam"), e.get("strAwayTeam"),
            e.get("dateEvent"), e.get("strTime", "00:00:00"),
            e.get("strVenue", ""),
            status, now
        ))


def fetch_football_data(league_key: str):
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


def fetch_sportsdb(league_key: str):
    """Fetch matches from TheSportsDB using multiple endpoints for completeness."""
    league = LEAGUES[league_key]
    conn = get_db()
    now = datetime.now(timezone.utc).isoformat()

    # 1. Season endpoint — gets the full schedule
    try:
        r = requests.get(
            "https://www.thesportsdb.com/api/v1/json/3/eventsseason.php",
            params={"id": league["sportsdb_id"], "s": league["sportsdb_season"]},
            timeout=15
        )
        events = r.json().get("events") or []
        print(f"[sportsdb] eventsseason: {len(events)} events")
        _store_sportsdb_events(conn, league_key, events, now)
    except Exception as ex:
        print(f"[sportsdb] eventsseason failed: {ex}")

    # 2. Past events — last 15 completed matches (has updated scores!)
    try:
        r = requests.get(
            "https://www.thesportsdb.com/api/v1/json/3/eventspastleague.php",
            params={"id": league["sportsdb_id"]},
            timeout=15
        )
        events = r.json().get("events") or []
        print(f"[sportsdb] eventspast: {len(events)} events")
        _store_sportsdb_events(conn, league_key, events, now)
    except Exception as ex:
        print(f"[sportsdb] eventspast failed: {ex}")

    # 3. Next events — next 15 upcoming matches
    try:
        r = requests.get(
            "https://www.thesportsdb.com/api/v1/json/3/eventsnextleague.php",
            params={"id": league["sportsdb_id"]},
            timeout=15
        )
        events = r.json().get("events") or []
        print(f"[sportsdb] eventsnext: {len(events)} events")
        _store_sportsdb_events(conn, league_key, events, now)
    except Exception as ex:
        print(f"[sportsdb] eventsnext failed: {ex}")

    conn.commit()
    conn.close()


def fetch_and_store(league_key: str):
    league = LEAGUES.get(league_key)
    if not league:
        return
    if league["source"] == "football-data":
        fetch_football_data(league_key)
    else:
        fetch_sportsdb(league_key)

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
        # full name match, or last word (main identifier)
        if c in t:
            return True
        if len(words) >= 1 and words[-1] in t:
            return True
        # Also check first word for multi-word names like "South Korea"
        if len(words) >= 2 and words[0] in t and words[-1] in t:
            return True
        return False

    has_both  = team_in(home) and team_in(away)
    highlight = any(w in t for w in
                        ["highlight", "match", "goals", "extended",
                        "תקציר", "שערים", "sign off", "vs", "v.",
                        "full match", "resumen", "zusammenfassung",
                        "\U0001f19a", "fifaworldcup", "#fifaworldcup"])
    exclude   = any(w in t for w in
                    ["compilation", "best of", "every goal", "parade", "bts",
                     "training", "press conference", "interview", "#shorts",
                     "season review", "all goals season", "preview",
                     "prediction", "lineup", "tactical", "pre-match",
                     "post-match press", "reaction"])
    if "תקציר" in t and not exclude:
        return True
    return has_both and highlight and not exclude


def search_youtube(home: str, away: str, match_date: str,
                   channel_id: str, query: str = None) -> list:
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
        if is_match_highlight(title, home, away):
            is_extended = "extended" in title.lower()
            results.append({
                "video_id": item["id"]["videoId"],
                "label":    "תקציר מורחב" if is_extended else "תקציר",
                "extended": is_extended,
            })

    # One of each type max
    regular  = next((v for v in results if not v["extended"]), None)
    extended = next((v for v in results if v["extended"]),     None)

    final = []
    if regular:  final.append(regular)
    if extended: final.append(extended)

    # Check embeddable
    if final:
        ids = [v["video_id"] for v in final]
        try:
            check = requests.get(
                "https://www.googleapis.com/youtube/v3/videos",
                params={"key": YOUTUBE_API_KEY, "id": ",".join(ids), "part": "status"},
                timeout=10
            ).json()
            embeddable_ids = {
                item["id"] for item in check.get("items", [])
                if item["status"].get("embeddable")
            }
            for v in final:
                v["embeddable"] = v["video_id"] in embeddable_ids
        except:
            for v in final:
                v["embeddable"] = True  # assume yes on error

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

    return [{"id": f"club_{c['id']}", "name": c["short_name"],
             "channel_id": c["yt_channel_id"]} for c in clubs]

# ── Endpoints ──────────────────────────────────────────

@app.get("/")
def root():
    return {"status": "SpoilerFree API ✓"}

@app.get("/matches/{league_key}")
def get_matches(league_key: str, refresh: bool = False, matchday: int = None):
    if league_key not in LEAGUES:
        raise HTTPException(404, "ליגה לא נמצאה")

    if refresh:
        fetch_and_store(league_key)

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


@app.get("/highlights/{match_id}")
def get_highlights(match_id: str):
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
        source_id  = source["id"]
        channel_id = source.get("channel_id", "")

        if not channel_id:
            results.append({"source_id": source_id, "name": source["name"],
                            "videos": [], "status": "no_channel"})
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
                                "videos": videos, "status": "cached"})
                continue

        # Search YouTube
        template = source.get("search_template", "{home} {away}")
        allow_embed = source.get("allow_embed", False)
        q = template.format(home=row["home_team"], away=row["away_team"])
        videos = search_youtube(
                    home=row["home_team"],
                    away=row["away_team"],
                    match_date=row["date_utc"],
                    channel_id=channel_id,
                    query=q,
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

        for v in videos:
            v["embeddable"] = allow_embed and v.get("embeddable", False)
        results.append({"source_id": source_id, "name": source["name"],
                        "videos": videos,
                        "status": "found" if videos else "not_found"})

    return {
        "available": True,
        "match":     f"{row['home_team']} vs {row['away_team']}",
        "sources":   results,
    }


@app.delete("/cache/{match_id}")
def clear_cache(match_id: str):
    """Clear highlight cache for a match — forces re-search on next request."""
    conn = get_db()
    conn.execute("DELETE FROM highlight_cache WHERE match_id=?", (match_id,))
    conn.commit()
    conn.close()
    return {"ok": True, "match_id": match_id}


@app.delete("/cache")
def clear_all_cache():
    """Clear ALL highlight cache — useful when debugging."""
    conn = get_db()
    conn.execute("DELETE FROM highlight_cache")
    conn.commit()
    conn.close()
    return {"ok": True}


@app.get("/clubs/{league_key}")
def get_clubs(league_key: str):
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM clubs WHERE league_key=? ORDER BY tier, name", (league_key,)
    ).fetchall()
    conn.close()
    return {"clubs": [dict(r) for r in rows]}


@app.put("/clubs/{club_id}/channel")
def update_club_channel(club_id: str, channel_id: str):
    conn = get_db()
    conn.execute("UPDATE clubs SET yt_channel_id=? WHERE id=?", (channel_id, club_id))
    conn.commit()
    conn.close()
    return {"ok": True}


@app.get("/debug/db")
def debug_db():
    """Quick debug endpoint — shows counts and recent matches."""
    conn = get_db()
    leagues = conn.execute(
        "SELECT league_key, COUNT(*) as c, "
        "SUM(CASE WHEN status='FINISHED' THEN 1 ELSE 0 END) as finished "
        "FROM matches GROUP BY league_key"
    ).fetchall()
    cache_count = conn.execute("SELECT COUNT(*) as c FROM highlight_cache").fetchone()["c"]
    recent = conn.execute(
        "SELECT id, league_key, home_team, away_team, date_utc, status "
        "FROM matches WHERE league_key='worldcup' ORDER BY date_utc, time_utc"
    ).fetchall()
    conn.close()
    return {
        "leagues": [dict(r) for r in leagues],
        "cache_entries": cache_count,
        "worldcup_matches": [dict(r) for r in recent],
    }


@app.get("/debug/sportsdb")
def debug_sportsdb():
    try:
        r = requests.get(
            "https://www.thesportsdb.com/api/v1/json/3/lookupevent.php",
            params={"id": "2391728"},
            timeout=15
        )
        return {"status_code": r.status_code, "body_preview": r.text[:500]}
    except Exception as e:
        return {"error": str(e)}

@app.post("/refresh/{league_key}")
def client_refresh(league_key: str, payload: dict):
    """Receive match data from client-side TheSportsDB fetch."""
    if league_key not in LEAGUES:
        raise HTTPException(404, "ליגה לא נמצאה")
    events = payload.get("events", [])
    if not events:
        return {"ok": False, "reason": "no events"}
    conn = get_db()
    now = datetime.now(timezone.utc).isoformat()
    _store_sportsdb_events(conn, league_key, events, now)
    conn.commit()
    conn.close()
    return {"ok": True, "stored": len(events)}

# Serve frontend
@app.get("/app")
def serve_frontend():
    return FileResponse("index.html")


# ── Init ───────────────────────────────────────────────
init_db()