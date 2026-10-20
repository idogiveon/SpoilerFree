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
    # ההשהיה עברה ל-togglePlay, שמשרת גם את הכפתור וגם לחיצה על הנגן
    block = HTML[HTML.index("function togglePlay()"):]
    block = block[:block.index("\n  }")]
    assert block.index("coverChrome()") < block.index("pauseVideo()")
    assert "document.getElementById('vid-play').onclick = togglePlay;" in HTML


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


# ── ביקורת מוצר (26.9.26): מבוי סתום אחרי בחירת גרסה ────────────────
def test_there_is_a_way_back_to_the_source_list():
    """loadVideo דורס את shield.innerHTML ומסיר picking. אחרי לחיצה על
    "ספורט 1 — תקציר מלא" לא הייתה שום דרך לנסות מקור אחר חוץ מלסגור
    את החלון ולפתוח את המשחק מחדש."""
    assert "function backToSources()" in HTML
    assert "pickerHTML = `" in HTML and "body.innerHTML = pickerHTML;" in HTML
    # כל מסך מגן מקבל את הכפתור, כולל סוף הווידאו ומסלול הכשל
    assert "backBtnHTML()" in HTML
    assert HTML.count('"other_source":') == 4


def test_the_list_of_another_match_is_not_offered_here():
    """pickerHTML מתאפס בפתיחת משחק — אחרת הכפתור היה מחזיר את המקורות
    של המשחק הקודם."""
    open_match = HTML[HTML.index("const body  = document.getElementById('modal-body')"):]
    assert "pickerHTML = '';" in open_match[:600]


def test_going_back_stops_the_player():
    back = HTML[HTML.index("function backToSources()"):]
    back = back[:back.index("\n  }")]
    for call in ("ytPlayer.destroy()", "clearInterval(vidTimer)", "hideVideoBar()"):
        assert call in back, call


# ── הנגן נלחץ (הבעלים, 10.10.26) ────────────────────────────────────
def test_the_player_itself_is_clickable():
    """ה-iframe חסום ללחיצות כדי שמעבר עכבר לא יוציא את הסרגל של
    יוטיוב, ולכן הקליקים נתפסים בשכבה משלנו."""
    assert 'id="vid-tap"' in HTML
    assert "pointer-events:none" in _css(".video-container.shielded iframe")
    tap = _css(".vid-tap")
    assert "position:absolute" in tap and "inset:0" in tap


def test_a_single_click_plays_and_a_double_click_skips():
    """בלי ההשהיה הקצרה, כל לחיצה כפולה הייתה גם מפעילה ומשהה בדרך."""
    assert "tapTimer = setTimeout(() => { tapTimer = null; togglePlay(); }, 260);" in HTML
    dbl = HTML[HTML.index("tap.ondblclick"):]
    dbl = dbl[:dbl.index("\n      };")]
    assert "clearTimeout(tapTimer)" in dbl
    assert "c + (back ? -10 : 10)" in dbl
    assert "box.width / 2" in dbl          # חצי שמאלי אחורה, ימני קדימה


def test_the_mask_outlives_the_title():
    """3.5 שניות לא הספיקו — הכותרת הסתננה רגע לפני שהמסכה ירדה."""
    assert "container.classList.remove('chrome-risk'), 6000)" in HTML


# ── "צריך ללחוץ נגן כמה פעמים" (הבעלים, 11.10.26) ───────────────────
def test_a_press_before_the_player_is_ready_is_not_lost():
    """playVideo לפני onReady נבלעת בשקט: 2.5 שניות אחר כך הכפתור חזר,
    הבעלים לחץ שוב, ואז זה עבד. הכוונה נזכרת ומופעלת ברגע המוכנות."""
    assert "onReady:" in HTML
    ready = HTML[HTML.index("onReady:"):]
    ready = ready[:ready.index("onStateChange:")]
    assert "ytReady = true" in ready
    assert "ytWantsPlay" in ready and "ytPlayer.playVideo()" in ready

    start = HTML[HTML.index("function startVideo()"):]
    start = start[:start.index("\n  }")]
    assert "if (ytReady) ytPlayer.playVideo();" in start
    assert "else ytWantsPlay = true;" in start


def test_each_video_gets_a_fresh_readiness_flag():
    """נגן חדש נוצר לכל סרטון. דגל שנשאר דולק מהנגן הקודם היה מחזיר
    בדיוק את אותו באג מהסרטון השני והלאה."""
    load = HTML[HTML.index("async function loadVideo("):HTML.index("new YT.Player(")]
    assert "ytReady = ytWantsPlay = ytFailed = false;" in load
    back = HTML[HTML.index("function backToSources()"):]
    assert "ytReady = ytWantsPlay = ytFailed = false;" in back[:back.index("\n  }")]


def test_the_shield_does_not_get_stuck_on_loading():
    """קודם היה כאן return שקט כשהנגן לא היה מוכן, והמגן נשאר על
    "טוען" בלי שום כפתור."""
    nudge = HTML[HTML.index("function armPlayNudge("):]
    nudge = nudge[:nudge.index("\n  }")]
    assert "if (!ytPlayer || !ytPlayer.getPlayerState) return;" not in nudge
    assert "ytReady && ytPlayer.getPlayerState" in nudge


def test_our_play_pause_waits_for_the_player():
    toggle = HTML[HTML.index("function togglePlay()"):]
    assert "!ytReady" in toggle[:toggle.index("\n")+200]


def test_a_blocked_video_is_not_overwritten_by_a_play_button():
    """ריאל–רומא (הבעלים, 15.10.26): יוטיוב סירב להטמיע, ההודעה הכנה
    הופיעה לשנייה, ואז טיימר ההפעלה דרס אותה בכפתור "נגן" שלא יכול היה
    לעבוד. כל לחיצה הציגה "טוען", חימשה את הטיימר, והכפתור חזר — לולאה
    שנראית כמו נגן שלא מגיב."""
    err = HTML[HTML.index("onError:"):]
    err = err[:err.index("\n        },")]
    assert "ytFailed = true" in err
    assert "clearTimeout(ytNudge)" in err
    nudge = HTML[HTML.index("function armPlayNudge("):]
    assert "if (!ytPlayer || ytFailed) return;" in nudge[:nudge.index("\n  }")]
    start = HTML[HTML.index("function startVideo()"):]
    assert "if (!ytPlayer || ytFailed) return;" in start[:start.index("\n  }")]


def test_the_failure_flag_falls_with_every_new_player():
    assert HTML.count("ytReady = ytWantsPlay = ytFailed = false;") == 2


# ── תצוגה מורחבת בטלפון (הבעלים, 20.10.26) ─────────────────────────
def test_the_black_margins_do_not_close_the_match():
    """בתצוגה מורחבת התמונה 16:9 ממורכזת, והשטח לצדיה הוא שכבת החלון
    עצמה. לחיצה עליה סגרה את המשחק — ולכן דאבל קליק לדילוג בקצה
    הווידאו "זרק אותי החוצה"."""
    fn = HTML[HTML.index("function backdropClick("):]
    fn = fn[:fn.index("\n  }")]
    assert "classList.contains('theatre-on')" in fn and "return;" in fn
    assert "addEventListener('click', backdropClick)" in HTML
    # ובלי התצוגה המורחבת ההתנהגות נשמרת: לחיצה ברקע סוגרת
    assert "closeModal();" in fn


def test_the_window_chrome_is_hidden_behind_the_picture():
    """החלון שקוף בתצוגה מורחבת, אבל ✕, שם המשחק וכפתורי המועדפים
    המשיכו להצטייר והציצו משני צדי התמונה בסיבוב לרוחב."""
    assert ".modal-overlay.theatre-on .modal-header { display:none; }" in HTML
