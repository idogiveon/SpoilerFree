"""מועדפים: נשמרים בחשבון, נפרדים בין משתמשים, נמחקים עם החשבון."""
import pytest

import main
from test_auth import ADMIN, FRIEND, client, login


@pytest.fixture
def auth_on(monkeypatch, mails):
    monkeypatch.setattr(main, "AUTH_ON", True)
    monkeypatch.setattr(main, "ADMIN_EMAILS", {ADMIN})
    return mails


def _friend(mails):
    client().post("/auth/request_code", json={"email": FRIEND})
    login(mails, ADMIN).post(f"/admin/api/users/{FRIEND}", json={"status": "approved"})
    return login(mails, FRIEND)


def test_add_list_remove(auth_on):
    admin = login(auth_on, ADMIN)
    assert admin.get("/favorites").json() == {"favorites": []}
    admin.post("/favorites", json={"league_key": "premier", "team": "Liverpool FC", "on": True})
    admin.post("/favorites", json={"league_key": "championship", "team": "Newell's Old Boys", "on": True})
    admin.post("/favorites", json={"league_key": "premier", "team": "Liverpool FC", "on": True})   # פעמיים — פעם אחת
    assert admin.get("/favorites").json()["favorites"] == [
        ["championship", "Newell's Old Boys"], ["premier", "Liverpool FC"]]
    admin.post("/favorites", json={"league_key": "premier", "team": "Liverpool FC", "on": False})
    assert admin.get("/favorites").json()["favorites"] == [["championship", "Newell's Old Boys"]]


def test_favorites_are_per_user(auth_on):
    admin = login(auth_on, ADMIN)
    admin.post("/favorites", json={"league_key": "laliga", "team": "Barcelona"})
    friend = _friend(auth_on)
    assert friend.get("/favorites").json()["favorites"] == []


def test_invalid_input_rejected(auth_on):
    admin = login(auth_on, ADMIN)
    assert admin.post("/favorites", json={"league_key": "nope", "team": "X"}).status_code == 400
    assert admin.post("/favorites", json={"league_key": "laliga", "team": " "}).status_code == 400


def test_requires_login(auth_on):
    assert client().get("/favorites").status_code == 401


def test_deleting_account_removes_favorites(auth_on):
    friend = _friend(auth_on)
    friend.post("/favorites", json={"league_key": "laliga", "team": "Barcelona"})
    friend.post("/auth/delete_account", json={"confirm": FRIEND})
    conn = main.get_db()
    assert conn.execute("SELECT COUNT(*) AS c FROM favorites WHERE email=?", (FRIEND,)).fetchone()["c"] == 0
    conn.close()


def test_without_personal_account_favorites_are_per_device(auth_on, monkeypatch):
    monkeypatch.setattr(main, "APP_PASSWORD", "pw")
    c = client()
    c.post("/login", json={"password": "pw"})
    assert c.get("/favorites").json() == {"favorites": [], "per_device": True}
    assert c.post("/favorites", json={"league_key": "laliga", "team": "Barcelona"}).status_code == 400
