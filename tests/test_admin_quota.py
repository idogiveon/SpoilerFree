"""דף הניהול מציג את צריכת מכסת יוטיוב של היום."""
from fastapi.testclient import TestClient

import main


def test_admin_kpis_show_youtube_units_today():
    c = TestClient(main.app)
    assert c.get("/admin/api/users").json()["kpis"]["yt_units_today"] == 0
    main._yt_units(100)
    main._yt_units(1)
    assert c.get("/admin/api/users").json()["kpis"]["yt_units_today"] == 101
    assert "יוטיוב היום" in c.get("/admin/users").text
