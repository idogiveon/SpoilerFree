"""תקרה על הרשמה — לפני שהאתר נפתח לאנשים.

היה בלם על סיסמה שגויה ועל קוד חוזר לאותו מייל, אבל ההרשמה עצמה הייתה
פתוחה: בוט יכול היה ליצור אלפי חשבונות, למלא את ה-DB ולהציף את הבעלים
בהתראות. כל בקשת קוד גם שולחת מייל אמיתי דרך Brevo.
"""
import pytest

import main
from test_auth import ADMIN, client


@pytest.fixture
def auth(monkeypatch, mails):
    monkeypatch.setattr(main, "AUTH_ON", True)
    monkeypatch.setattr(main, "ADMIN_EMAILS", {ADMIN})
    return mails


def _signup(n, prefix="u"):
    out = []
    for i in range(n):
        c = client()
        out.append(c.post("/auth/register",
                          json={"email": f"{prefix}{i}@example.com",
                                "password": "goodpass1"}).status_code)
    return out


def test_a_flood_from_one_address_is_stopped(auth):
    codes = _signup(main.REGISTER_PER_IP_HOUR + 3)
    assert codes[:main.REGISTER_PER_IP_HOUR] == [200] * main.REGISTER_PER_IP_HOUR
    assert set(codes[main.REGISTER_PER_IP_HOUR:]) == {429}


def test_a_person_who_fumbles_is_not_punished(auth):
    """סיסמה קצרה, מייל תפוס — אלה לא יוצרים כלום ולא נספרים. אחרת
    מי שטועה פעמיים ומתקן היה נחסם לשעה."""
    c = client()
    for _ in range(6):
        assert c.post("/auth/register",
                      json={"email": "me@example.com", "password": "short"}).status_code == 400
    assert c.post("/auth/register",
                  json={"email": "me@example.com", "password": "goodpass1"}).status_code == 200
    for _ in range(4):
        assert c.post("/auth/register",
                      json={"email": "me@example.com", "password": "goodpass1"}).status_code == 409


def test_the_limit_counts_accounts_that_were_really_created(auth):
    """אחרי הרשמה מוצלחת אחת נשארות עוד שתיים — לא פחות."""
    assert _signup(1) == [200]
    assert _signup(main.REGISTER_PER_IP_HOUR - 1, prefix="later") == \
        [200] * (main.REGISTER_PER_IP_HOUR - 1)
    assert _signup(1, prefix="over") == [429]


def test_sending_codes_is_capped_too(auth, monkeypatch):
    """כל בקשה כזו שולחת מייל אמיתי."""
    monkeypatch.setattr(main, "EMAIL_CODE_REQUIRED", False)
    codes = [client().post("/auth/request_code", json={"email": f"c{i}@example.com"}).status_code
             for i in range(main.REGISTER_PER_IP_HOUR + 2)]
    assert codes[-1] == 429


def test_the_two_doors_share_one_budget(auth):
    """בוט לא יעקוף את התקרה בכך שיתחלף בין הרשמה לבקשת קוד."""
    _signup(main.REGISTER_PER_IP_HOUR)
    assert client().post("/auth/request_code",
                         json={"email": "x@example.com"}).status_code == 429


def test_a_real_address_is_read_from_behind_the_proxy():
    """ב-Render כל הבקשות מגיעות מה-proxy; בלי הכותרת הזו כל
    המשתמשים היו חולקים מונה אחד."""
    src = open("main.py", encoding="utf-8").read()
    assert 'request.headers.get("x-forwarded-for"' in src
    block = src[src.index("def _client_ip("):]
    assert 'split(",")[0]' in block[:block.index("\n\n")]


def test_there_is_a_ceiling_for_everyone_together(auth, monkeypatch):
    """רשת ביטחון מפני הצפה מכמה כתובות."""
    monkeypatch.setattr(main, "REGISTER_PER_IP_HOUR", 1000)
    monkeypatch.setattr(main, "REGISTER_PER_HOUR", 2)
    assert _signup(3, prefix="all") == [200, 200, 429]


def test_both_limits_can_be_moved_without_a_deploy():
    src = open("main.py", encoding="utf-8").read()
    assert 'os.environ.get("REGISTER_PER_IP_HOUR"' in src
    assert 'os.environ.get("REGISTER_PER_HOUR"' in src
