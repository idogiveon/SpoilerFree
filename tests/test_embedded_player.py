"""צפייה בתוך האתר, בלי שיוטיוב יסגיר את התוצאה (#35).

נמדד בדפדפן מול תקציר אמיתי (Man City–Norwich, 22.9.26). יוטיוב חושף
את התוצאה בארבעה מקומות, לא באחד:
  1. הכותרת מעל הנגן — "Man City 5-0 Norwich | Highlights"
  2. התמונה הממוזערת לפני ההפעלה — "5 : 0" על כל המסך
  3. "More videos" בפינה — תמונות ממוזערות של משחקים אחרים ("5 : 3")
  4. מסך הסיום — אותן תמונות, בגדול
הכותרת וההצעות מופיעות גם בהשהיה דרך הכפתור שלנו, בלי שום נגיעה
בעכבר — ולכן המסכות קבועות ולא מותנות באינטראקציה.
"""
import main

HTML = open("index.html", encoding="utf-8").read()


def _css(selector):
    i = HTML.index(selector)
    return HTML[i:HTML.index("}", i)]


MASK_TOP = ".video-container.shielded.chrome-risk::after"
MASK_CORNER = ".video-container.shielded.chrome-risk::before"


def test_the_title_and_the_suggestions_are_both_covered():
    top = _css(MASK_TOP)
    assert "top:0" in top and "background:#000" in top
    corner = _css(MASK_CORNER)
    assert "bottom:0" in corner and "background:#000" in corner
    # right פיזי, לא inset-inline-end: הפקדים של יוטיוב תמיד בימין,
    # וב-RTL המסכה עברה שמאלה והשאירה את ההצעות חשופות (22.9.26)
    assert "right:0" in corner and "inset-inline-end" not in corner


def test_the_masks_are_not_tied_to_hovering():
    """השהיה דרך הכפתור שלנו מציגה את הכותרת בלי מגע עכבר."""
    for sel in (MASK_TOP, MASK_CORNER):
        assert ":hover" not in _css(sel)
    # הן תלויות במצב הנגן, לא באינטראקציה: כל מצב שאינו "מתנגן" מכסה
    assert "function coverChrome()" in HTML
    assert "if (e.data !== YT.PlayerState.PLAYING) coverChrome();" in HTML
    # והשהיה שלנו מכסה לפני הקריאה, כדי שלא תהיה הבלחה
    block = HTML[HTML.index("document.getElementById('vid-play').onclick"):]
    block = block[:block.index("};")]
    assert block.index("coverChrome()") < block.index("pauseVideo()")


def test_the_frame_never_receives_the_pointer():
    assert "pointer-events:none" in _css(".video-container.shielded iframe")


def test_youtube_chrome_is_switched_off():
    block = HTML[HTML.index("playerVars:"):]
    block = block[:block.index("}")]
    for off in ("controls: 0", "rel: 0", "fs: 0", "iv_load_policy: 3"):
        assert off in block, off


def test_the_shield_waits_for_real_playback():
    """הורדת המגן לפני שהניגון התחיל חושפת את התמונה הממוזערת."""
    block = HTML[HTML.index("onStateChange:"):]
    block = block[:block.index("onError:")]
    assert "YT.PlayerState.PLAYING" in block
    assert "shield.style.display = 'none'" in block


def test_the_end_screen_is_covered_too():
    block = HTML[HTML.index("onStateChange:"):]
    block = block[:block.index("onError:")]
    assert "YT.PlayerState.ENDED" in block
    assert "t('watch_again')" in block


def test_a_blocked_channel_falls_back_to_youtube():
    block = HTML[HTML.index("onError:"):]
    block = block[:block.index("});")]
    assert "openOnYoutube(" in block


def test_a_phone_that_blocks_autoplay_gets_a_play_button():
    """בטלפון הניגון האוטומטי חסום; בלי זה המגן נתקע על "טוען"."""
    assert "function startVideo()" in HTML
    assert "t('tap_to_play')" in HTML
    assert "ytPlayer.playVideo();" in HTML


def test_the_controls_are_ours_and_sit_outside_the_picture():
    assert "class=\"vid-bar\"" in HTML or "vid-bar" in HTML
    bar = _css(".vid-bar")
    assert "position:absolute" not in bar          # מתחת לנגן, לא מעליו


def test_embedding_is_one_decision_not_twenty_three():
    """קודם כל מקור נשא דגל משלו, וכולם אמרו "אסור"."""
    src = open("main.py", encoding="utf-8").read()
    assert src.count('"allow_embed": False') == 0
    assert 'EMBED_IN_APP = os.environ.get("EMBED_IN_APP", "1") != "0"' in src
    assert 'allow_embed = EMBED_IN_APP and source.get("allow_embed", True)' in src


def test_a_source_can_still_be_excluded(monkeypatch):
    monkeypatch.setattr(main, "EMBED_IN_APP", False)
    src = {"id": "s", "name": "n", "channel_id": ""}
    assert main._source_highlights({"id": "m"}, src)["allow_embed"] is False


def test_the_player_interface_language_is_pinned():
    """בלי זה מיקום הפקדים משתנה לפי שפת הצופה, והמסכה מפספסת."""
    block = HTML[HTML.index("playerVars:"):]
    assert "hl: 'en'" in block[:block.index("}")]


def test_expanding_keeps_the_masks_on_the_picture():
    """בתצוגה מורחבת הקופסה נשארת 16:9. אילו נמתחה למסך שלם, המסכות
    היו יושבות על שולי המסך במקום על הכותרת ועל ההצעות."""
    theatre = _css(".video-container.theatre")
    assert "aspect-ratio:16 / 9" in theatre        # הקופסה = התמונה
    assert "position:fixed" in theatre
    # מוגבל גם בגובה: בלי זה סיבוב לרוחב חתך את התמונה (22.9.26)
    assert "min(100vw" in theatre and "* 16 / 9)" in theatre
    assert "function toggleTheatre()" in HTML
    # החלון מוסר את ה-transform שלו, אחרת fixed נמדד יחסית אליו
    assert ".modal-overlay.theatre-on .modal { transform:none;" in HTML
    # בלי רקע נפרד ב-body: הוא היה בשכבה מעל החלון והסתיר את הווידאו
    assert "theatre-backdrop" not in HTML


def test_leaving_the_video_leaves_the_expanded_view():
    for fn in ("function closeModal()", "function hideVideoBar()"):
        block = HTML[HTML.index(fn):]
        assert "exitTheatre();" in block[:block.index("\n  }")]


# ── מסך הסיום של יוטיוב (QA, 26.9.26) ──────────────────────────────
def test_the_corner_masks_come_back_before_the_end():
    """כרטיסי "עוד סרטונים" עולים ~20 שניות לפני הסוף, והמצב עדיין
    PLAYING — אין אירוע שיחזיר את המסכות, ולכן הטיימר עושה את זה."""
    assert "d - c <= 25) coverChrome()" in HTML


def test_the_full_cover_does_not_eat_the_highlight():
    """כיסוי מלא של 25 השניות האחרונות היה מסתיר את סוף התקציר עצמו —
    בתקציר של 90 שניות זה השליש האחרון."""
    assert "d - c <= 1.5) container.classList.add('ending')" in HTML
    assert ".video-container.shielded.ending::before { inset:0" in HTML


def test_replay_clears_the_end_cover():
    assert "classList.remove('ending')" in HTML
