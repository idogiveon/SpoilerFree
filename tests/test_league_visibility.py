"""ליגה שהוסרה נעלמת גם מהכפתורים למעלה; מסך "ליגות" נפרד; פריסת הניווט."""
import re

HTML = open("index.html", encoding="utf-8").read()


def test_byday_is_its_own_row_above_the_leagues():
    panel = re.search(r'<div class="nav-panel">(.*?)<div class="matchday-nav', HTML, re.S).group(1)
    switch = re.search(r'<div class="view-switch">(.*?)</div>', panel, re.S).group(1)
    assert 'data-league="__byday"' in switch                     # "לפי יום" לבד בשורה שלו
    leagues = re.search(r'<div class="league-tabs">(.*?)</div>', panel, re.S).group(1)
    assert 'data-league="__byday"' not in leagues
    assert leagues.count('class="tab"') >= 11                    # כל הליגות


def test_hidden_league_button_is_not_displayed():
    assert ".tab.is-hidden { display:none; }" in HTML


def test_leaving_a_league_you_just_hid():
    assert "if (HIDDEN_LEAGUES.has(currentLeague))" in HTML


def test_leagues_screen_in_the_menu():
    assert "openLeaguePicker()" in HTML and "function openLeaguePicker()" in HTML
    assert 'id="lg-pick"' in HTML


def test_spacing_between_panel_and_navigation():
    panel = re.search(r"\.nav-panel \{([^}]*)\}", HTML).group(1)
    assert "margin:1rem auto 2.25rem" in panel                   # מרווח מתחת לכפתורים


def test_every_new_text_is_translated():
    block = re.search(r'<script type="application/json" id="i18n">(.*?)</script>', HTML, re.S).group(1)
    import json
    i18n = json.loads(block)
    for lang in ("he", "en", "es", "fr"):
        assert i18n[lang]["leagues_screen"] and i18n[lang]["leagues_hint"]
