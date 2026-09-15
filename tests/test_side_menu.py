"""תפריט צד (☰): החשבון, השפה וההגדרות עברו מהכותרת לתפריט."""
import re

HTML = open("index.html", encoding="utf-8").read()


def test_menu_button_and_drawer_exist():
    assert 'id="menu-btn"' in HTML and 'aria-controls="drawer"' in HTML
    drawer = re.search(r'<nav class="drawer" id="drawer".*?</nav>', HTML, re.S).group(0)
    assert 'id="lang-select"' in drawer                 # השפה בתוך התפריט
    assert 'id="drawer-cookies"' in drawer and 'id="drawer-logout"' in drawer


def test_old_header_bar_is_gone():
    assert 'id="user-bar"' not in HTML and "getElementById('user-bar')" not in HTML


def test_drawer_closes_on_escape_and_overlay():
    assert "e.key === 'Escape'" in HTML
    assert "getElementById('drawer-overlay').addEventListener('click', closeDrawer)" in HTML
