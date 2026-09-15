"""האתר ב-Render נעול תמיד — גם אחרי מחיקת APP_PASSWORD / GMAIL_USER."""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _auth_on(**env):
    clean = {k: v for k, v in os.environ.items()
             if k not in ("APP_PASSWORD", "GMAIL_USER", "BREVO_API_KEY", "GMAIL_CLIENT_ID",
                          "AUTH_DEV", "RENDER", "TURSO_DATABASE_URL")}
    out = subprocess.run([sys.executable, "-c", "import main; print(main.AUTH_ON)"],
                         cwd=ROOT, env={**clean, **env}, capture_output=True, text=True)
    return out.stdout.strip().splitlines()[-1]


def test_render_without_any_secret_is_still_locked():
    assert _auth_on(RENDER="true") == "True"


def test_local_dev_without_secrets_is_open():
    assert _auth_on() == "False"
