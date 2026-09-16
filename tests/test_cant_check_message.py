""""לא ניתן לבדוק כרגע" במקום "התקציר לא הועלה" כשלא הצלחנו לבדוק בכלל."""
import json
import re
from datetime import datetime, timedelta, timezone

import main

HTML = open("index.html", encoding="utf-8").read()


def test_api_error_shows_an_honest_message():
    assert "s.status === 'api_error'" in HTML and "t('cant_check')" in HTML


def test_message_exists_in_every_language():
    block = re.search(r'<script type="application/json" id="i18n">(.*?)</script>', HTML, re.S).group(1)
    i18n = json.loads(block)
    assert all(i18n[lang]["cant_check"] for lang in ("he", "en", "es", "fr"))


def test_server_reports_api_error_when_it_could_not_check(db, monkeypatch):
    """בלם המכסה / תקלת פיד — status=api_error, ולא "לא נמצא"."""
    past = datetime.now(timezone.utc) - timedelta(hours=20)
    db.execute("INSERT INTO matches (id, league_key, home_team, away_team, date_utc, time_utc, status) "
               "VALUES ('c1', 'israel', 'Maccabi Haifa', 'Hapoel Tel-Aviv', ?, ?, 'FINISHED')",
               (past.strftime("%Y-%m-%d"), past.strftime("%H:%M:%S")))
    db.commit()
    row = db.execute("SELECT * FROM matches WHERE id='c1'").fetchone()
    monkeypatch.setattr(main, "search_youtube", lambda *a, **k: None)
    res = main._source_highlights(row, main.LEAGUES["israel"]["sources"][0])
    assert res["status"] == "api_error" and res["videos"] == []
