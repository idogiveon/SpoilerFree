"""שורת הליגות: אחת שנגללת, במקום קיר של כפתורים.

נמדד ב-375 פיקסל (26.9.26): 17 ליגות גלשו ל-8 שורות בגובה 358 פיקסל,
והפיד נדחק ל-711 מתוך 812 — כלומר פתיחת הרשימה בלעה 44% מהמסך.
אחרי: שורה אחת בגובה 40, והפיד חוזר ל-393.
"""
HTML = open("index.html", encoding="utf-8").read()


def _css(selector):
    i = HTML.index(selector)
    return HTML[i:HTML.index("}", i)]


def test_the_row_does_not_wrap():
    row = _css("    .league-tabs {")
    assert "flex-wrap:wrap" not in row
    scroll = _css(".league-scroll {")
    assert "overflow-x:auto" in scroll
    assert "white-space:nowrap" in _css(".league-scroll .tab")


def test_there_is_a_hint_that_more_exists():
    """גוללן בלי סרגל וללא רמז נראה כמו רשימה שנגמרה."""
    assert "mask-image:linear-gradient" in _css(".league-scroll {")


def test_the_settings_button_stays_reachable():
    """הוא מחוץ לגוללן — אחרת צריך לגלול עד הסוף כדי להגיע אליו."""
    row = HTML[HTML.index('<div class="league-tabs collapsed"'):]
    row = row[:row.index("</div>\n</div>") + 20]
    scroll_end = row.index("</div>")
    assert row.index('id="edit-leagues"') > scroll_end


def test_favourites_come_first_and_cups_come_after_a_divider():
    fn = HTML[HTML.index("function orderLeagueTabs()"):]
    fn = fn[:fn.index("\n  }")]
    assert "FAV_LEAGUES.has(t.dataset.league)" in fn
    assert "isCup(t.dataset.league)" in fn
    assert "cup-sep" in fn


def test_the_divider_hides_when_no_cups_are_shown():
    fn = HTML[HTML.index("function orderLeagueTabs()"):]
    assert "sep.hidden = !cups.some" in fn[:fn.index("\n  }")]


def test_the_chosen_league_is_brought_into_view():
    fn = HTML[HTML.index("function revealActiveTab()"):]
    fn = fn[:fn.index("\n  }")]
    # instant ולא auto: auto פירושו "לפי ה-CSS", ושם זה smooth
    assert "behavior: 'instant'" in fn
    # הפרש בפיקסלים, כי ב-RTL ערכי הגלילה שליליים
    assert "scrollBy" in fn and "a.width / 2" in fn
    assert "scrollIntoView" not in fn      # גורר גם את הדף אנכית


def test_the_reveal_runs_after_the_reorder():
    """הסידור מאפס את מיקום הגלילה."""
    fn = HTML[HTML.index("function orderLeagueTabs()"):]
    fn = fn[:fn.index("\n  }")]
    assert fn.index("scroll.append") < fn.index("revealActiveTab()")
