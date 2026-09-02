from pathlib import Path

from learningloop.skills import SkillCatalog


def catalog() -> SkillCatalog:
    return SkillCatalog(Path(__file__).resolve().parents[1] / "skills")


def test_loads_five_utf8_skills() -> None:
    loaded = catalog()
    assert len(loaded.metadata()) == 5
    assert "goal-anchoring" in {item["name"] for item in loaded.metadata()}


def test_skill_routing() -> None:
    loaded = catalog()
    assert (
        loaded.select("我想学习 Python", has_course=False, has_due_reviews=False).name
        == "goal-anchoring"
    )
    assert (
        loaded.select("制定30天学习计划", has_course=False, has_due_reviews=False).name
        == "course-planning"
    )
    assert (
        loaded.select("继续今天内容", has_course=True, has_due_reviews=False).name
        == "daily-tutoring"
    )
    assert loaded.select("重新排期", has_course=True, has_due_reviews=False).name == "plan-recovery"
    assert loaded.select("继续", has_course=True, has_due_reviews=True).name == "review-coaching"
