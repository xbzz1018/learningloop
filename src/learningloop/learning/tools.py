from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import Any

from learningloop.config import Settings
from learningloop.db import Database
from learningloop.learning.content import enrich_course_plan
from learningloop.learning.scheduler import schedule_review
from learningloop.learning.schemas import (
    ConceptState,
    CoursePlan,
    ErrorRecord,
    LearningResult,
    MemoryCandidate,
)
from learningloop.learning.state import LearningWorkspace, MemoryGate
from learningloop.llm.context import current_call_context
from learningloop.llm.search import SearchService
from learningloop.models import (
    ActionDecision,
    ActionRequest,
    ActionType,
    ApprovalRecord,
    EventRecord,
)


def _context() -> Any:
    context = current_call_context.get()
    if context is None:
        raise RuntimeError("learning tool called outside an active session")
    return context


def _workspace(settings: Settings) -> LearningWorkspace:
    return LearningWorkspace(settings.workspace_dir, _context().session_id)


def _reserve_effect(
    db: Database, tool_name: str, args: dict[str, Any]
) -> tuple[str, dict[str, Any] | None]:
    context = _context()
    source_id = context.source_message_id or db.latest_message_id(context.session_id) or 0
    encoded = json.dumps(args, ensure_ascii=False, sort_keys=True, default=str)
    args_hash = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
    effect_key = hashlib.sha256(
        f"{context.session_id}:{source_id}:{tool_name}:{args_hash}".encode()
    ).hexdigest()
    existing = db.get_tool_effect(effect_key)
    if existing:
        if existing["status"] == "completed":
            return effect_key, existing.get("result") or {"status": "completed"}
        raise RuntimeError(f"tool effect requires recovery: {effect_key}")
    db.reserve_tool_effect(
        effect_key,
        run_id=context.run_id,
        session_id=context.session_id,
        tool_name=tool_name,
        args_hash=args_hash,
    )
    return effect_key, None


class GetLearnerProfile:
    name = "get_learner_profile"
    cacheable = False

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def execute(self) -> dict[str, Any]:
        return _workspace(self.settings).learner().model_dump(mode="json")


class GetCourseState:
    name = "get_course_state"
    cacheable = False

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def execute(self) -> dict[str, Any]:
        return _workspace(self.settings).course().model_dump(mode="json")


class GetConceptState:
    name = "get_concept_state"
    cacheable = False

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def execute(self, concept_id: str | None = None) -> dict[str, Any]:
        concepts = _workspace(self.settings).concepts()
        if concept_id:
            concept = concepts.get(concept_id)
            return concept.model_dump(mode="json") if concept else {"error": "concept not found"}
        return {key: value.model_dump(mode="json") for key, value in concepts.items()}


class GetDueReviews:
    name = "get_due_reviews"
    cacheable = False

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def execute(self) -> list[dict[str, Any]]:
        now = datetime.now(UTC)
        return [
            value.model_dump(mode="json")
            for value in _workspace(self.settings).reviews().values()
            if value.due_at <= now
        ]


class GetRecentErrors:
    name = "get_recent_errors"
    cacheable = False

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def execute(self, limit: int = 10) -> list[dict[str, Any]]:
        safe_limit = max(1, min(int(limit), 20))
        return [
            value.model_dump(mode="json")
            for value in _workspace(self.settings).errors()[-safe_limit:]
        ]


class UpdateLearnerProfile:
    name = "update_learner_profile"
    cacheable = False

    def __init__(self, settings: Settings, db: Database) -> None:
        self.settings = settings
        self.db = db

    async def execute(
        self,
        background: str | None = None,
        learning_topic: str | None = None,
        target_outcome: str | None = None,
        duration_days: int | None = None,
        weekly_days: int | None = None,
        daily_minutes: int | None = None,
        preferences: dict[str, str] | None = None,
        confidence: float = 1.0,
    ) -> dict[str, Any]:
        context = _context()
        source_id = self.db.latest_message_id(context.session_id)
        if source_id is None:
            return {"status": "rejected", "reason": "no source user message"}
        content: dict[str, Any] = {}
        if background is not None:
            content["background"] = background[:2_000]
        if learning_topic is not None:
            content["learning_topic"] = learning_topic[:300]
        if target_outcome is not None:
            content["target_outcome"] = target_outcome[:1_000]
        if duration_days is not None:
            content["duration_days"] = duration_days
        if weekly_days is not None:
            content["weekly_days"] = weekly_days
        if daily_minutes is not None:
            content["daily_minutes"] = daily_minutes
        if preferences:
            content["preferences"] = preferences
        effect_key, previous = _reserve_effect(self.db, self.name, content | {"confidence": confidence})
        if previous is not None:
            return previous
        candidate = MemoryCandidate(
            type="profile",
            content=content,
            source_message_id=source_id,
            confidence=confidence,
        )
        result = MemoryGate(_workspace(self.settings)).apply(candidate)
        self.db.complete_tool_effect(effect_key, result)
        return result


class RecordLearningResultTool:
    name = "record_learning_result"
    cacheable = False

    def __init__(self, settings: Settings, db: Database) -> None:
        self.settings = settings
        self.db = db

    async def execute(
        self,
        concept_id: str,
        concept_name: str,
        score: float,
        answer: str = "",
        feedback: str = "",
        stage_id: str | None = None,
        error_category: str | None = None,
    ) -> dict[str, Any]:
        context = _context()
        source_id = self.db.latest_message_id(context.session_id)
        if source_id is None:
            return {"status": "rejected", "reason": "no source user message"}
        result = LearningResult(
            concept_id=concept_id,
            concept_name=concept_name,
            stage_id=stage_id,
            score=score,
            source_message_id=source_id,
            answer=answer,
            feedback=feedback,
            error_category=error_category,
        )
        effect_key, previous = _reserve_effect(
            self.db, self.name, result.model_dump(mode="json")
        )
        if previous is not None:
            return previous
        workspace = _workspace(self.settings)
        concepts = workspace.concepts()
        current = concepts.get(result.concept_id)
        attempts = (current.attempts if current else 0) + 1
        prior_mastery = current.mastery if current else 0.0
        mastery = max(0.0, min(1.0, prior_mastery * 0.65 + result.score * 0.35))
        evidence = list(current.evidence_message_ids if current else [])
        if source_id not in evidence:
            evidence.append(source_id)
        concepts[result.concept_id] = ConceptState(
            id=result.concept_id,
            name=result.concept_name,
            stage_id=result.stage_id,
            mastery=mastery,
            attempts=attempts,
            last_score=result.score,
            evidence_message_ids=evidence[-20:],
            updated_at=datetime.now(UTC),
        )
        workspace.save_concepts(concepts)
        errors = workspace.errors()
        if result.score < 0.7 and result.error_category:
            errors.append(
                ErrorRecord(
                    id=str(uuid.uuid4()),
                    concept_id=result.concept_id,
                    category=result.error_category,
                    answer=result.answer[:4_000],
                    feedback=result.feedback[:4_000],
                    source_message_id=source_id,
                )
            )
            workspace.save_errors(errors[-200:])
        reviews = workspace.reviews()
        reviews[result.concept_id] = schedule_review(
            result.concept_id, result.score, reviews.get(result.concept_id)
        )
        workspace.save_reviews(reviews)
        response = {
            "status": "recorded",
            "concept_id": result.concept_id,
            "mastery": mastery,
            "next_review": reviews[result.concept_id].due_at.isoformat(),
        }
        self.db.complete_tool_effect(effect_key, response)
        return response


class ProposeCoursePlan:
    name = "create_or_replace_course_plan"
    cacheable = False

    def __init__(self, settings: Settings, db: Database) -> None:
        self.settings = settings
        self.db = db

    async def execute(self, plan: dict[str, Any], reason: str = "") -> dict[str, Any]:
        context = _context()
        validated = CoursePlan.model_validate(plan)
        effect_key, previous = _reserve_effect(
            self.db,
            self.name,
            {
                "plan": validated.model_dump(mode="json", exclude={"updated_at"}),
                "reason": reason[:1_000],
            },
        )
        if previous is not None:
            return previous
        approval = ApprovalRecord(
            id=str(uuid.uuid4()),
            session_id=context.session_id,
            run_id=context.run_id,
            tool=self.name,
            args={"plan": validated.model_dump(mode="json")},
            message=reason[:1_000] or "Replace the current course plan",
        )
        self.db.create_approval(approval)
        self.db.create_action(
            ActionRequest(
                id=approval.id,
                session_id=context.session_id,
                run_id=context.run_id,
                action_type=ActionType.PLAN_APPROVAL,
                title="确认学习计划",
                description="批准后会写入课程计划并生成今日学习任务。",
                payload={"approval_id": approval.id, "plan": validated.model_dump(mode="json")},
                available_decisions=[
                    ActionDecision.EXECUTE,
                    ActionDecision.NEXT,
                    ActionDecision.SUGGEST,
                    ActionDecision.REJECT,
                ],
            )
        )
        self.db.add_event(
            EventRecord(
                session_id=context.session_id,
                run_id=context.run_id,
                type="approval_required",
                payload={
                    "approval_id": approval.id,
                    "action_id": approval.id,
                    "tool": approval.tool,
                    "message": approval.message,
                },
            )
        )
        self.db.add_event(
            EventRecord(
                session_id=context.session_id,
                run_id=context.run_id,
                type="action_required",
                payload={"action_id": approval.id, "action_type": ActionType.PLAN_APPROVAL.value},
            )
        )
        self.db.update_session(context.session_id, status="awaiting_approval")
        result = {"status": "awaiting_approval", "approval_id": approval.id}
        self.db.complete_tool_effect(effect_key, result)
        return result


class SearchWebTool:
    name = "search_web"
    cacheable = True

    def __init__(self, service: SearchService) -> None:
        self.service = service

    async def execute(self, query: str, max_results: int = 5) -> dict[str, Any]:
        return await self.service.search(query[:1_000], max(1, min(max_results, 8)))


def apply_approved_tool(settings: Settings, approval: dict[str, Any]) -> dict[str, Any]:
    workspace = LearningWorkspace(settings.workspace_dir, approval["session_id"])
    if approval["tool"] == "create_or_replace_course_plan":
        plan = CoursePlan.model_validate(approval["args"]["plan"])
        current = workspace.course()
        plan = enrich_course_plan(plan, plan.goal or plan.title)
        plan.version = max(current.version + 1, plan.version)
        plan.approved = True
        plan.updated_at = datetime.now(UTC)
        workspace.save_course(plan)
        return {"status": "applied", "version": plan.version}
    raise ValueError(f"unsupported approved tool: {approval['tool']}")


def build_tools(settings: Settings, db: Database, search: SearchService) -> dict[str, Any]:
    instances = [
        GetLearnerProfile(settings),
        GetCourseState(settings),
        GetConceptState(settings),
        GetDueReviews(settings),
        GetRecentErrors(settings),
        UpdateLearnerProfile(settings, db),
        RecordLearningResultTool(settings, db),
        ProposeCoursePlan(settings, db),
        SearchWebTool(search),
    ]
    return {tool.name: tool for tool in instances}
