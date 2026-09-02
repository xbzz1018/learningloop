from __future__ import annotations

from datetime import UTC, datetime

import pytest

from learningloop.learning.daily import DailyLearningService
from learningloop.learning.schemas import CoursePlan, CourseStage
from learningloop.learning.state import LearningWorkspace
from learningloop.notifications import MailService, NotificationScheduler


@pytest.mark.asyncio
async def test_daily_plan_is_persisted_and_task_completion_updates_stage(settings, db) -> None:
    session = db.create_session("daily-session")
    workspace = LearningWorkspace(settings.workspace_dir, session["id"])
    workspace.save_course(
        CoursePlan(
            title="Python",
            goal="掌握 Python 基础",
            approved=True,
            stages=[
                CourseStage(
                    id="syntax",
                    title="语法基础",
                    objective="掌握变量、条件和循环",
                    estimated_days=3,
                )
            ],
        )
    )
    daily = DailyLearningService(settings, db)
    plan = await daily.generate_daily_plan(session["id"])
    assert plan.tasks
    assert db.get_daily_plan(session["id"], plan.plan_date.isoformat())
    updated = daily.mark_task_complete(session["id"], plan.plan_date, plan.tasks[0].id)
    assert updated.tasks[0].completed is True


@pytest.mark.asyncio
async def test_scheduler_sends_each_type_once_and_uses_outbox(settings, db) -> None:
    session = db.create_session("notify-session")
    db.save_notification_settings(
        session["id"],
        email="learner@example.com",
        enabled=True,
        timezone="Asia/Shanghai",
        morning_time="08:30",
        evening_time="20:30",
    )
    daily = DailyLearningService(settings, db)
    scheduler = NotificationScheduler(settings, db, daily, MailService(settings))
    first = await scheduler.run_once(datetime.now(UTC), force=True)
    assert {item["schedule_type"] for item in first} == {"morning_plan", "evening_review"}
    second = await scheduler.run_once(datetime.now(UTC), force=True)
    assert second == []
    deliveries = db.notification_deliveries(session["id"])
    assert {row["status"] for row in deliveries} == {"sent"}
    assert all(row["attempts"] == 1 for row in deliveries)


@pytest.mark.asyncio
async def test_scheduler_skips_morning_after_catchup_window(settings, db) -> None:
    session = db.create_session("late-session")
    db.save_notification_settings(
        session["id"],
        email="learner@example.com",
        enabled=True,
        timezone="Asia/Shanghai",
        morning_time="08:30",
        evening_time="20:30",
    )
    daily = DailyLearningService(settings, db)
    scheduler = NotificationScheduler(settings, db, daily, MailService(settings))
    now = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
    result = await scheduler.run_once(now)
    assert any(item["schedule_type"] == "morning_plan" and item["status"] == "skipped" for item in result)


def test_mailer_local_outbox_does_not_require_smtp(settings) -> None:
    result = MailService(settings).send(
        recipient="learner@example.com",
        subject="test",
        text="hello",
    )
    assert result["delivery_mode"] == "local_outbox"
