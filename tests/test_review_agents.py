"""סוכני הביקורת והמיומנות שלהם נמצאים בגיט.

B2 בבקלוג: שישה סוכנים ומיומנות אחת חיו רק במחשב של הבעלים, כי
.gitignore הדיר את כל .claude/. כל re-clone היה מאבד אותם, והם ידע על
הפרויקט — לא הגדרה אישית. הבדיקה רצה ב-CI על checkout נקי, ולכן היא
נכשלת בדיוק במקרה שהיא נועדה למנוע: שהם לא נדחפו.
"""
import re
from pathlib import Path

AGENTS = Path(".claude/agents")
EXPECTED = {"qa", "code", "data", "design", "product", "devops"}


def _front(path):
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n"), f"{path}: אין frontmatter"
    return text.split("---\n", 2)[1]


def test_every_review_agent_is_in_the_repo():
    assert {p.stem for p in AGENTS.glob("*.md")} == EXPECTED


def test_each_agent_declares_who_it_is_and_when_to_run_it():
    """description הוא מה שמחליט אם הסוכן נבחר בכלל — בלעדיו הוא קיים
    אך לא ייקרא לעולם."""
    for path in AGENTS.glob("*.md"):
        front = _front(path)
        for key in ("name:", "description:", "model:", "tools:"):
            assert key in front, f"{path.name}: חסר {key}"
        name = re.search(r"^name:\s*(\S+)", front, re.M).group(1)
        assert name == path.stem, f"{path.name}: name={name}"
        assert "הפעל" in front, f"{path.name}: ה-description לא אומר מתי להפעיל"


def test_the_review_board_skill_is_in_the_repo():
    skill = Path(".claude/skills/review-board/SKILL.md")
    assert skill.exists()
    front = _front(skill)
    assert "name: review-board" in front and "description:" in front


def test_local_settings_stay_out():
    """settings.local.json יכול להחזיק הרשאות ונתיבים של מכונה אחת."""
    ignore = Path(".gitignore").read_text(encoding="utf-8")
    assert ".claude/settings.local.json" in ignore
    assert not re.search(r"^\.claude/\s*$", ignore, re.M), "כל .claude/ מודר שוב"
