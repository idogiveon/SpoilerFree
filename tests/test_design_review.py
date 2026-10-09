"""ביקורת עיצוב (2.10.26) — כללי CSS שנשברו בשקט.

כל אחד מאלה נמדד בדפדפן ברוחב 375, לא נקרא מהקוד: כלל כפול שמחק
מרווח, כפתור שגולש מהמסך בצרפתית, ויעדי מגע של 17 פיקסלים.
"""
import re

HTML = open("index.html", encoding="utf-8").read()


def _mobile_block():
    i = HTML.index("@media (max-width:600px)")
    return HTML[i:HTML.index("</style>", i)]


def test_the_score_keeps_its_distance_from_the_team_buttons():
    """ההגנה הייתה מרווח אנכי, ושני כללים ל-.match-score מחקו אותו
    בשקט (נמדד 4.8px במקום 14.4). עכשיו ההפרדה היא מבנית: התוצאה
    יושבת בפינה של ה-✕ ולא מתחת לכפתורי הקבוצות (הבעלים, 9.10.26)."""
    head = HTML[HTML.index('<div class="modal-header">'):]
    head = head[:head.index("</div>\n    <div id=\"modal-body\"")]
    # לא באותו בלוק עם שמות הקבוצות
    assert head.index('id="modal-favs"') < head.index('class="modal-side"')
    assert 'id="modal-score"' in head[head.index('class="modal-side"'):]
    # ומרווח אמיתי מה-✕, שלחיצה לא תסגור את החלון בטעות
    side = re.search(r"\.modal-side \{([^}]*)\}", HTML).group(1)
    assert "gap:1.5rem" in side
    # וכלל אחד בלבד ל-.match-score
    assert len(re.findall(r"\.match-score \{", HTML)) == 2      # פריסה + טיפוגרפיה
    assert sum("margin-top" in d for d in
               re.findall(r"\.match-score \{([^}]*)\}", HTML)) == 0


def test_the_day_nav_can_wrap():
    """"Revenir à aujourd'hui" לא מתכווץ מתחת לרוחב min-content שלו,
    והדף כולו נעשה 398px ונגלל לצדדים — בצרפתית בלבד."""
    nav = re.search(r"\.matchday-nav \{([^}]*)\}", HTML).group(1)
    assert "flex-wrap:wrap" in nav


def test_the_player_controls_can_be_hit_with_a_finger():
    """נמדד 17.5×17.6 ו-16.1×17.6, ופס גרירה של 3px — במסך שנמצא
    בשימוש יומיומי."""
    btn = re.search(r"\.vid-btn \{([^}]*)\}", HTML).group(1)
    assert "min-width:44px" in btn and "min-height:44px" in btn
    seek = re.search(r"\.vid-seek \{([^}]*)\}", HTML).group(1)
    assert "height:28px" in seek


def test_live_is_not_hidden_on_a_phone():
    """בדיוק הטעות שתוקנה לחיווי התקציר שורה אחת מעל: עם תוצאות
    דלוקות משבצת הזמן מציגה "2 : 1" ולא "LIVE", ואז שום דבר בכרטיס
    לא אומר שהמשחק רץ."""
    mobile = _mobile_block()
    assert ".live-badge { display:none; }" not in mobile
    assert ".live-badge { position:static" in mobile


def test_switching_language_updates_the_scores_button():
    """הטקסט שלו נקבע ב-JS ולא ב-data-i18n, ולכן הוא נשאר בשפה
    הקודמת עד רענון."""
    handler = HTML[HTML.index("document.getElementById('lang-select').addEventListener"):]
    handler = handler[:handler.index("\n  });")]
    for fn in ("applyStatic()", "updateRefreshBtn()", "updateScoresBtn()"):
        assert fn in handler, fn


def test_the_hidden_note_is_above_the_fold():
    """בתחתית הפיד הוא ישב 11 מסכים מתחת לקיפול בשבת עם 92 משחקים."""
    status = HTML[HTML.index('<div class="status-bar">'):]
    assert 'id="hidden-note"' in status[:400]
    note = re.search(r"\.hidden-note \{([^}]*)\}", HTML).group(1)
    assert "padding:0.5rem" in note                      # יעד מגע, היה 18.5px
