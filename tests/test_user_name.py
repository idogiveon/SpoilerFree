"""שם למשתמש — אופציונלי בהרשמה, וניתן להוספה ידנית במסך הניהול.

מהבעלים (9.10.26): "שתהיה לי אפשרות להוסיף שם ליוזר שאני יודע את השם
שלו, וכתב מייל פיקטיבי/לא ברור." בטבלת המשתמשים יש כתובות כמו
hhah@ghd.co ו-li@test.com — והוא יודע מי עומד מאחוריהן.
"""
import main
from fastapi.testclient import TestClient
from test_auth import ADMIN, FRIEND, auth_on, client, login  # noqa: F401

PAGE = main.LOGIN_PAGE


def test_the_field_says_it_is_optional():
    """סטנדרט: שדה לא חובה אומר את זה, ולא נותן לנחש."""
    assert 'id="reg-name"' in PAGE
    assert "nm.placeholder = t('name_optional')" in PAGE
    for lang in ("he", "en", "es", "fr"):
        label = main.LOGIN_I18N[lang]["name_optional"]
        assert label and any(w in label.lower() for w in
                             ("לא חובה", "optional", "opcional", "facultatif")), lang


def test_signing_up_with_a_name_keeps_it(db, auth_on):
    c = client()
    c.post("/auth/register", json={"email": FRIEND, "password": "goodpass1",
                                   "name": "  יוסי   כהן "})
    row = db.execute("SELECT name FROM users WHERE email=?", (FRIEND,)).fetchone()
    assert row["name"] == "יוסי כהן"          # רווחים כפולים מתנקים
    assert c.get("/auth/me").json()["name"] == "יוסי כהן"


def test_signing_up_without_one_is_fine(db, auth_on):
    c = client()
    c.post("/auth/register", json={"email": FRIEND, "password": "goodpass1"})
    row = db.execute("SELECT name FROM users WHERE email=?", (FRIEND,)).fetchone()
    assert row["name"] is None               # ולא מחרוזת ריקה


def test_the_owner_can_name_someone_who_did_not(db, auth_on):
    """זו הבקשה עצמה: כתובת שלא אומרת כלום, והבעלים יודע מי זה."""
    client().post("/auth/register", json={"email": "hhah@ghd.co", "password": "goodpass1"})
    admin = login(auth_on, ADMIN)
    r = admin.post("/admin/api/users/hhah@ghd.co", json={"name": "אלון"})
    assert r.status_code == 200
    row = db.execute("SELECT name, status FROM users WHERE email='hhah@ghd.co'").fetchone()
    assert row["name"] == "אלון"
    assert row["status"] == "approved"       # שינוי שם לא נוגע בסטטוס


def test_an_empty_name_clears_it(db, auth_on):
    client().post("/auth/register", json={"email": FRIEND, "password": "goodpass1",
                                          "name": "זמני"})
    admin = login(auth_on, ADMIN)
    admin.post(f"/admin/api/users/{FRIEND}", json={"name": "  "})
    row = db.execute("SELECT name FROM users WHERE email=?", (FRIEND,)).fetchone()
    assert row["name"] is None


def test_a_name_cannot_be_a_paragraph(db, auth_on):
    c = client()
    c.post("/auth/register", json={"email": FRIEND, "password": "goodpass1",
                                   "name": "א" * 500})
    row = db.execute("SELECT name FROM users WHERE email=?", (FRIEND,)).fetchone()
    assert len(row["name"]) == main.NAME_MAX_LEN


def test_only_an_admin_can_rename(db, auth_on):
    client().post("/auth/register", json={"email": FRIEND, "password": "goodpass1"})
    friend = login(auth_on, FRIEND)
    assert friend.post(f"/admin/api/users/{FRIEND}", json={"name": "אני"}).status_code == 403


def test_the_app_shows_the_name_where_the_identity_sits():
    html = open("index.html", encoding="utf-8").read()
    assert "user.textContent = me.name || me.email || t('account');" in html
