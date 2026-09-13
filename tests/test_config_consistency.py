"""ליגה שנוספה בשרת חייבת טאב ורענון בפרונט — ולהפך."""
import re

import main


def _html():
    return open("index.html", encoding="utf-8").read()


def test_every_league_has_a_tab():
    tabs = set(re.findall(r'data-league="([a-z0-9_]+)"', _html())) - {"__byday"}
    assert tabs == set(main.LEAGUES)


def test_sportsdb_leagues_match_frontend_refresh_config():
    html = _html()
    block = html[html.index("const SPORTSDB_LEAGUES"):]
    block = block[:block.index("};")]
    front = {k: (ids, season) for k, ids, season in
             re.findall(r"(\w+):\s*\{\s*ids:\s*\[([^\]]*)\],\s*season:\s*'([^']+)'", block)}
    server = {k: v for k, v in main.LEAGUES.items() if v["source"] == "sportsdb"}
    assert set(front) == set(server)
    for k, (ids, season) in front.items():
        assert re.findall(r"'(\d+)'", ids) == server[k]["sportsdb_ids"], k
        assert season == server[k]["sportsdb_season"], k
