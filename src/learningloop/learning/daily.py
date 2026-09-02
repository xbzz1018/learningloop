from __future__ import annotations

import json
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from learningloop.config import Settings
from learningloop.db import Database
from learningloop.learning.content import enrich_course_plan
from learningloop.learning.schemas import CoursePlan, DailyPlan, DailyReview, DailyTask
from learningloop.learning.state import LearningWorkspace
from learningloop.llm.context import call_context
from learningloop.models import AgentRole, CallContext, ModelRoute


class DailyLearningService:
    """Build persisted daily plans and reviews for one learning session."""

    def __init__(self, settings: Settings, db: Database, gateway: Any | None = None) -> None:
        self.settings = settings
        self.db = db
        self.gateway = gateway

    def local_today(self) -> date:
        return datetime.now(UTC).astimezone(ZoneInfo(self.settings.notification_timezone)).date()

    def _workspace(self, session_id: str) -> LearningWorkspace:
        return LearningWorkspace(self.settings.workspace_dir, session_id)

    def _deterministic_plan(self, session_id: str, plan_date: date) -> DailyPlan:
        snapshot = self._workspace(session_id).snapshot()
        course_model = enrich_course_plan(
            CoursePlan.model_validate(snapshot["course"]),
            str(snapshot["learner"].get("learning_topic") or snapshot["course"].get("goal") or "当前主题"),
        )
        course = course_model.model_dump(mode="json")
        budget = int(snapshot["learner"].get("daily_minutes", 45))
        tasks: list[DailyTask] = []
        remaining = budget
        for stage in course.get("stages", []):
            if stage.get("completed") or remaining < 5:
                continue
            lesson = (stage.get("lessons") or [{}])[0]
            minutes = min(remaining, max(15, min(60, int(budget / 2))))
            tasks.append(
                DailyTask(
                    id=f"stage:{stage['id']}:{plan_date.isoformat()}",
                    title=stage["title"],
                    category="课程阶段",
                    objective=stage["objective"],
                    lesson_id=lesson.get("id"),
                    concepts=list(lesson.get("concepts") or stage.get("key_concepts") or []),
                    explanation=str(lesson.get("explanation") or ""),
                    example=str(lesson.get("example") or ""),
                    exercise=str(lesson.get("exercise") or ""),
                    expected_output=str(lesson.get("expected_output") or ""),
                    acceptance_criteria=str(
                        lesson.get("acceptance_criteria")
                        or stage.get("stage_acceptance_criteria")
                        or ""
                    ),
                    estimated_minutes=minutes,
                    stage_id=stage["id"],
                    due_date=plan_date,
                )
            )
            remaining -= minutes
            if len(tasks) >= 3:
                break
        due_reviews = snapshot.get("due_reviews", [])
        priority_reviews = [str(item.get("concept_id")) for item in due_reviews if item.get("concept_id")]
        if priority_reviews and remaining >= 10:
            tasks.insert(
                0,
                DailyTask(
                    id=f"reviews:{plan_date.isoformat()}",
                    title="完成到期知识点复习",
                    category="间隔复习",
                    objective="优先复习今天到期的知识点，并记录练习结果。",
                    concepts=priority_reviews,
                    explanation="使用主动回忆复述知识点，再对照反馈修正理解。",
                    exercise="先不看资料回答知识点，再记录你的答案和不确定的地方。",
                    expected_output="提交答案和 0 到 1 的自评得分。",
                    acceptance_criteria="能指出一个正确要点和一个仍需复习的地方。",
                    estimated_minutes=min(remaining, 20),
                    due_date=plan_date,
                ),
            )
        if not tasks:
            tasks.append(
                DailyTask(
                    id=f"setup:{plan_date.isoformat()}",
                    title="补充学习目标和课程计划",
                    category="目标设定",
                    objective="先通过对话创建一个可执行的学习目标。",
                    explanation="补充主题、目标成果、学习周期和每日时间后，学习助手才能生成详细课程。",
                    exercise="回到当前对话，说明想学什么、已有基础和希望完成的成果。",
                    expected_output="得到一份经过审批的课程计划。",
                    acceptance_criteria="四项目标信息完整，且课程计划已通过审批。",
                    estimated_minutes=min(budget, 20),
                    due_date=plan_date,
                )
            )
        return DailyPlan(
            id=f"{session_id}:{plan_date.isoformat()}",
            session_id=session_id,
            plan_date=plan_date,
            goal=str(course.get("goal") or "建立可持续的学习节奏"),
            tasks=tasks,
            total_minutes=sum(task.estimated_minutes for task in tasks),
            priority_reviews=priority_reviews,
            practice="完成任务后记录答案、得分或遇到的错误。",
            completion_criteria="完成至少一个任务，并记录学习结果。",
            source="deterministic",
        )

    async def generate_daily_plan(
        self,
        session_id: str,
        plan_date: date | None = None,
        *,
        force: bool = False,
        agent_role: AgentRole = AgentRole.INTERACTIVE,
        run_id: str | None = None,
    ) -> DailyPlan:
        plan_date = plan_date or self.local_today()
        existing = self.db.get_daily_plan(session_id, plan_date.isoformat())
        if existing and not force:
            return DailyPlan.model_validate(existing["payload"])
        plan = self._deterministic_plan(session_id, plan_date)
        if self._model_enabled():
            try:
                plan = await self._model_plan(
                    session_id, plan, agent_role=agent_role, run_id=run_id
                )
            except Exception:
                plan = plan.model_copy(update={"source": "fallback"})
        self.db.save_daily_plan(plan)
        return plan

    def save_deterministic_plan(self, session_id: str, plan_date: date | None = None) -> DailyPlan:
        plan = self._deterministic_plan(session_id, plan_date or self.local_today())
        self.db.save_daily_plan(plan)
        return plan

    async def _model_plan(
        self,
        session_id: str,
        base: DailyPlan,
        *,
        agent_role: AgentRole = AgentRole.INTERACTIVE,
        run_id: str | None = None,
    ) -> DailyPlan:
        snapshot = self._workspace(session_id).snapshot()
        owner_id = str((self.db.get_session(session_id) or {}).get("owner_id") or "local")
        context = CallContext(
            run_id=run_id or f"daily-plan-{uuid.uuid4().hex}",
            session_id=session_id,
            owner_id=owner_id,
            turn_id=f"daily-plan-{base.plan_date.isoformat()}",
            task_type="daily_plan",
            call_site="daily_plan",
            agent_role=agent_role,
        )
        prompt = (
            "根据结构化学习状态生成今日计划，只返回 JSON。不要改变日期、session_id 或任务 id。"
            "任务必须控制在学习者每日时间内，不得虚构知识点。\n"
            + json.dumps({"base": base.model_dump(mode="json"), "state": snapshot}, ensure_ascii=False)
        )
        with call_context(context, ModelRoute.FLASH):
            response = await self.gateway.llm.complete(
                system="You generate a concise validated daily learning plan as JSON only.",
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
                max_completion_tokens=2_048,
                reasoning_effort="low",
                source="daily_plan",
            )
        candidate = DailyPlan.model_validate(json.loads(str(response.get("text") or "{}")))
        base_ids = {task.id for task in base.tasks}
        if (
            candidate.session_id != session_id
            or candidate.plan_date != base.plan_date
            or {task.id for task in candidate.tasks} - base_ids
            or any(task.due_date != base.plan_date for task in candidate.tasks)
            or candidate.total_minutes != sum(task.estimated_minutes for task in candidate.tasks)
            or candidate.total_minutes > snapshot["learner"].get("daily_minutes", 45)
        ):
            raise ValueError("model plan changed deterministic scheduling constraints")
        base_by_id = {task.id: task for task in base.tasks}
        normalized_tasks = []
        for task in candidate.tasks:
            deterministic = base_by_id[task.id]
            normalized_tasks.append(
                task.model_copy(
                    update={
                        "lesson_id": task.lesson_id or deterministic.lesson_id,
                        "concepts": task.concepts or deterministic.concepts,
                        "explanation": task.explanation or deterministic.explanation,
                        "example": task.example or deterministic.example,
                        "exercise": task.exercise or deterministic.exercise,
                        "expected_output": task.expected_output or deterministic.expected_output,
                        "acceptance_criteria": task.acceptance_criteria
                        or deterministic.acceptance_criteria,
                    }
                )
            )
        return candidate.model_copy(
            update={
                "id": base.id,
                "session_id": session_id,
                "plan_date": base.plan_date,
                "tasks": normalized_tasks,
                "source": "model",
            }
        )

    async def generate_review(
        self,
        session_id: str,
        review_date: date | None = None,
        *,
        force: bool = False,
        agent_role: AgentRole = AgentRole.INTERACTIVE,
        run_id: str | None = None,
    ) -> DailyReview:
        review_date = review_date or self.local_today()
        existing = self.db.get_daily_review(session_id, review_date.isoformat())
        if existing and not force:
            return DailyReview.model_validate(existing["payload"])
        plan_row = self.db.get_daily_plan(session_id, review_date.isoformat())
        plan = DailyPlan.model_validate(plan_row["payload"]) if plan_row else None
        completed = [task.id for task in plan.tasks if task.completed] if plan else []
        unfinished = [task.id for task in plan.tasks if not task.completed] if plan else []
        workspace = self._workspace(session_id)
        errors = workspace.errors()
        review = DailyReview(
            id=f"{session_id}:{review_date.isoformat()}",
            session_id=session_id,
            review_date=review_date,
            completed_task_ids=completed,
            unfinished_task_ids=unfinished,
            new_errors=[error.id for error in errors if error.created_at.date() == review_date],
            tomorrow_focus=[item.concept_id for item in workspace.reviews().values() if item.due_at.date() <= review_date + timedelta(days=1)],
            summary=(
                f"完成 {len(completed)} 项，未完成 {len(unfinished)} 项。"
                if plan
                else "今天还没有生成学习计划。"
            ),
            plan_adjustment_suggested=len(unfinished) >= 2,
            source="deterministic",
        )
        if self._model_enabled() and plan:
            try:
                review = await self._model_review(
                    session_id, review, agent_role=agent_role, run_id=run_id
                )
            except Exception:
                pass
        self.db.save_daily_review(review)
        return review

    async def _model_review(
        self,
        session_id: str,
        base: DailyReview,
        *,
        agent_role: AgentRole = AgentRole.INTERACTIVE,
        run_id: str | None = None,
    ) -> DailyReview:
        owner_id = str((self.db.get_session(session_id) or {}).get("owner_id") or "local")
        context = CallContext(
            run_id=run_id or f"daily-review-{uuid.uuid4().hex}",
            session_id=session_id,
            owner_id=owner_id,
            turn_id=f"daily-review-{base.review_date.isoformat()}",
            task_type="daily_review",
            call_site="daily_review",
            agent_role=agent_role,
        )
        with call_context(context, ModelRoute.FLASH):
            response = await self.gateway.llm.complete(
                system="You summarize a learning review faithfully as JSON only.",
                messages=[
                    {
                        "role": "user",
                        "content": "优化以下复盘摘要，不要添加不存在的事实："
                        + json.dumps(base.model_dump(mode="json"), ensure_ascii=False),
                    }
                ],
                response_format={"type": "json_object"},
                max_completion_tokens=1_024,
                reasoning_effort="low",
                source="daily_review",
            )
        candidate = DailyReview.model_validate(json.loads(str(response.get("text") or "{}")))
        return candidate.model_copy(
            update={"id": base.id, "session_id": session_id, "review_date": base.review_date, "source": "model"}
        )

    def mark_task_complete(self, session_id: str, plan_date: date, task_id: str) -> DailyPlan:
        row = self.db.get_daily_plan(session_id, plan_date.isoformat())
        if not row:
            raise KeyError("daily plan not found")
        plan = DailyPlan.model_validate(row["payload"])
        found = False
        tasks = []
        for task in plan.tasks:
            if task.id == task_id:
                task = task.model_copy(
                    update={
                        "completed": True,
                        "status": "completed",
                        "completed_at": datetime.now(UTC),
                    }
                )
                found = True
            tasks.append(task)
        if not found:
            raise KeyError("daily task not found")
        updated = plan.model_copy(update={"tasks": tasks})
        self.db.save_daily_plan(updated)
        if updated.tasks and all(task.completed for task in updated.tasks if task.stage_id):
            for task in updated.tasks:
                if task.stage_id:
                    try:
                        self._workspace(session_id).mark_stage_completed(task.stage_id)
                    except KeyError:
                        pass
        return updated

    def mark_task_started(self, session_id: str, plan_date: date, task_id: str) -> DailyPlan:
        row = self.db.get_daily_plan(session_id, plan_date.isoformat())
        if not row:
            raise KeyError("daily plan not found")
        plan = DailyPlan.model_validate(row["payload"])
        tasks = [
            task.model_copy(update={"status": "in_progress"})
            if task.id == task_id and not task.completed
            else task
            for task in plan.tasks
        ]
        if not any(task.id == task_id for task in plan.tasks):
            raise KeyError("daily task not found")
        updated = plan.model_copy(update={"tasks": tasks})
        self.db.save_daily_plan(updated)
        return updated

    def get_task(self, session_id: str, plan_date: date, task_id: str) -> DailyTask:
        row = self.db.get_daily_plan(session_id, plan_date.isoformat())
        if not row:
            raise KeyError("daily plan not found")
        plan = DailyPlan.model_validate(row["payload"])
        for task in plan.tasks:
            if task.id == task_id:
                return task
        raise KeyError("daily task not found")

    def save_task_result(
        self,
        session_id: str,
        plan_date: date,
        task_id: str,
        *,
        score: float,
        answer: str,
        notes: str,
        error_category: str | None,
        completed: bool,
    ) -> DailyPlan:
        row = self.db.get_daily_plan(session_id, plan_date.isoformat())
        if not row:
            raise KeyError("daily plan not found")
        plan = DailyPlan.model_validate(row["payload"])
        found = False
        tasks: list[DailyTask] = []
        for task in plan.tasks:
            if task.id == task_id:
                found = True
                task = task.model_copy(
                    update={
                        "completed": completed,
                        "status": "completed" if completed else "in_progress",
                        "score": score,
                        "answer": answer[:8_000],
                        "notes": notes[:4_000],
                        "error_category": error_category,
                        "completed_at": datetime.now(UTC) if completed else None,
                    }
                )
            tasks.append(task)
        if not found:
            raise KeyError("daily task not found")
        updated = plan.model_copy(update={"tasks": tasks})
        self.db.save_daily_plan(updated)
        if updated.tasks and all(task.completed for task in updated.tasks if task.stage_id):
            for task in updated.tasks:
                if task.stage_id:
                    try:
                        self._workspace(session_id).mark_stage_completed(task.stage_id)
                    except KeyError:
                        pass
        return updated

    def plan_rows(self, session_id: str) -> list[dict[str, Any]]:
        workspace = self._workspace(session_id)
        course = workspace.course()
        local_tz = ZoneInfo(self.settings.notification_timezone)
        start = course.updated_at.astimezone(local_tz).date()
        rows: list[dict[str, Any]] = []
        offset = 0
        for index, stage in enumerate(course.stages, start=1):
            planned = start + timedelta(days=offset)
            rows.append(
                {
                    "index": index,
                    "date": planned.isoformat(),
                    "title": stage.title,
                    "category": "课程阶段",
                    "days": stage.estimated_days,
                    "key_concepts": stage.key_concepts,
                    "lessons": [lesson.model_dump(mode="json") for lesson in stage.lessons],
                    "content_status": stage.content_status,
                    "status": "已完成" if stage.completed else ("进行中" if index == 1 else "未开始"),
                    "completed": stage.completed,
                    "stage_id": stage.id,
                }
            )
            offset += stage.estimated_days
        return rows

    def _model_enabled(self) -> bool:
        if not self.settings.enable_real_models or self.gateway is None:
            return False
        return any(provider.flash_key is not None for provider in self.settings.providers.values())


__all__ = ["DailyLearningService"]
