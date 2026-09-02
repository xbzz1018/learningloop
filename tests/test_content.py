from __future__ import annotations

from datetime import date

from learningloop.learning.content import enrich_course_plan, fallback_course_plan
from learningloop.learning.daily import DailyLearningService
from learningloop.learning.schemas import CoursePlan, CourseStage, DailyTask
from learningloop.learning.state import LearningWorkspace


def test_incomplete_course_is_enriched_with_actionable_lesson() -> None:
    plan = CoursePlan(
        title="Python 计划",
        goal="掌握 Python 基础",
        duration_days=14,
        stages=[
            CourseStage(
                id="python-basics",
                title="基础语法",
                objective="掌握变量、函数和控制流",
                estimated_days=3,
            )
        ],
    )
    enriched = enrich_course_plan(plan, "Python")
    stage = enriched.stages[0]
    lesson = stage.lessons[0]
    assert enriched.content_source == "fallback"
    assert stage.content_status == "fallback"
    assert stage.key_concepts
    assert lesson.example and lesson.exercise and lesson.acceptance_criteria


def test_fallback_plan_supports_unknown_topic_without_empty_fields() -> None:
    plan = fallback_course_plan("量子计算", duration_days=10)
    assert plan.content_source == "fallback"
    assert len(plan.stages) == 5
    assert all(stage.lessons and stage.lessons[0].exercise for stage in plan.stages)


def test_daily_task_completed_boolean_normalizes_status() -> None:
    task = DailyTask(id="task-1", title="练习", due_date=date.today(), completed=True)
    assert task.status == "completed"


def test_daily_plan_uses_enriched_lesson_fields(settings, db) -> None:
    workspace = LearningWorkspace(settings.workspace_dir, "content-session")
    workspace.save_course(fallback_course_plan("Python", duration_days=10))
    daily = DailyLearningService(settings, db)
    plan = daily.save_deterministic_plan("content-session")
    assert plan.tasks
    assert plan.tasks[0].exercise
    assert plan.tasks[0].acceptance_criteria
