from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from learningloop.agent.context import ContextBuilder, ContextBundle
from learningloop.agent.hooks import RuntimeHooks
from learningloop.agent.policy import AgentPolicy
from learningloop.config import Settings
from learningloop.db import Database
from learningloop.models import (
    AgentArtifact,
    AgentRole,
    CallContext,
    ModelRoute,
    RunRecord,
    RunStage,
    SessionStatus,
    TaskMetadata,
)
from learningloop.skills import SkillCatalog

AgentExecutor = Callable[[str, ContextBundle, Any, ModelRoute, CallContext], Awaitable[str]]
GoalCheckpoint = Callable[..., None]
Compactor = Callable[[str, str, str], Awaitable[None]]


class LearningLoopRuntime:
    """Domain runtime around the upstream single-agent loop."""

    def __init__(
        self,
        *,
        settings: Settings,
        db: Database,
        skills: SkillCatalog,
        model_policy: Any,
        execute_agent: AgentExecutor,
        create_goal_checkpoint: GoalCheckpoint,
        compact: Compactor,
        runtime_metadata: dict[str, str] | None = None,
    ) -> None:
        self.settings = settings
        self.db = db
        self.skills = skills
        self.model_policy = model_policy
        self.execute_agent = execute_agent
        self.create_goal_checkpoint = create_goal_checkpoint
        self.compact = compact
        self.runtime_metadata = runtime_metadata or {}
        self.context_builder = ContextBuilder(settings, db)
        self.hooks = RuntimeHooks(db, settings.trace_dir)
        self._global_sem = asyncio.Semaphore(settings.global_concurrency)
        self._session_locks: dict[str, asyncio.Lock] = {}

    def mark_interrupted_runs(self) -> None:
        for run in self.db.incomplete_runs():
            checkpoint = self.db.latest_checkpoint_for_run(run["id"])
            stage = (checkpoint or {}).get("state", {}).get("stage") or run["stage"]
            if stage == RunStage.AWAITING_ACTION.value:
                self.db.update_run(
                    run["id"], stage=RunStage.AWAITING_ACTION.value, status="awaiting_action"
                )
                self.db.update_session(
                    run["session_id"], status=SessionStatus.AWAITING_APPROVAL.value
                )
                continue
            self.db.update_run(run["id"], status=SessionStatus.RECOVERING.value)
            self.db.update_session(run["session_id"], status=SessionStatus.RECOVERING.value)
            self.hooks.emit(
                run["session_id"],
                run["id"],
                "recovering",
                {"stage": stage, "message": "可从最近稳定阶段重试。"},
            )

    async def run_turn(
        self,
        *,
        session_id: str,
        run_id: str,
        text: str,
        metadata: TaskMetadata,
        persist_user: bool,
        agent_role: AgentRole = AgentRole.INTERACTIVE,
        parent_run_id: str | None = None,
    ) -> None:
        lock = self._session_locks.setdefault(session_id, asyncio.Lock())
        async with self._global_sem, lock:
            turn_id = str(uuid.uuid4())
            session = self.db.get_session(session_id)
            if session is None:
                raise KeyError("session not found")
            owner_id = str(session.get("owner_id") or "local")
            run = RunRecord(
                id=run_id,
                session_id=session_id,
                owner_id=owner_id,
                turn_id=turn_id,
                agent_role=agent_role,
                parent_run_id=parent_run_id,
            )
            self.db.create_run(run)
            self.db.update_session(
                session_id, status=SessionStatus.RUNNING.value, current_run_id=run_id
            )
            try:
                message_id = (
                    self.db.add_message(session_id, "user", text)
                    if persist_user
                    else self.db.latest_message_id(session_id)
                )
                if message_id is None:
                    raise RuntimeError("retry requested without a previous user message")
                self._checkpoint(
                    run_id,
                    session_id,
                    RunStage.RECEIVED,
                    {"message_id": message_id, "metadata": metadata.model_dump(mode="json")},
                )
                bundle = self.context_builder.build(session_id)
                self._checkpoint(run_id, session_id, RunStage.CONTEXT_READY, {})
                has_course = bool(bundle.snapshot["course"].get("title"))
                has_due_reviews = bool(bundle.snapshot["due_reviews"])
                goal_ready = self._goal_ready(bundle.snapshot["learner"])
                skill, route_reason = self.skills.select_with_reason(
                    text,
                    has_course=has_course,
                    has_due_reviews=has_due_reviews,
                    goal_ready=goal_ready,
                )
                route = self.model_policy.choose(metadata)
                skill_hash = self.skills.version_hash(skill)
                self.db.update_run(
                    run_id,
                    skill_name=skill.name,
                    skill_hash=skill_hash,
                    model_route=route.value,
                )
                self.hooks.emit(
                    session_id,
                    run_id,
                    "run_started",
                    {
                        "turn_id": turn_id,
                        "agent_role": agent_role.value,
                        "agent_profile": {
                            "name": AgentPolicy.profile_for(agent_role).name,
                            "allowed_skills": sorted(
                                AgentPolicy.profile_for(agent_role).allowed_skills
                            ),
                            "allowed_tools": sorted(
                                AgentPolicy.profile_for(agent_role).allowed_tools
                            ),
                            "max_steps": AgentPolicy.profile_for(agent_role).max_steps,
                        },
                        "model_route": route.value,
                        "skill": skill.name,
                        "skill_hash": skill_hash,
                        "route_reason": route_reason,
                        **self.runtime_metadata,
                    },
                )
                context = CallContext(
                    run_id=run_id,
                    session_id=session_id,
                    owner_id=owner_id,
                    turn_id=turn_id,
                    task_type=metadata.operation,
                    call_site="agent",
                    agent_role=agent_role,
                    source_message_id=message_id,
                )
                answer = await self.execute_agent(text, bundle, skill, route, context)
                self._checkpoint(
                    run_id,
                    session_id,
                    RunStage.MODEL_COMPLETED,
                    {"answer_present": bool(answer)},
                )
                if answer:
                    self.db.add_message(session_id, "assistant", answer)
                    artifact = AgentArtifact(
                        id=f"{run_id}:answer",
                        run_id=run_id,
                        session_id=session_id,
                        owner_id=owner_id,
                        artifact_type="assistant_answer",
                        payload={"text": answer},
                        source=agent_role,
                    )
                    self.db.create_agent_artifact(
                        artifact_id=artifact.id,
                        run_id=artifact.run_id,
                        session_id=artifact.session_id,
                        owner_id=artifact.owner_id,
                        artifact_type=artifact.artifact_type,
                        schema_version=artifact.schema_version,
                        payload=artifact.payload,
                        source=artifact.source.value,
                    )
                self.create_goal_checkpoint(
                    session_id=session_id,
                    run_id=run_id,
                    selected_skill=skill.name,
                )
                await self.compact(session_id, run_id, turn_id)
                current = self.db.get_session(session_id) or {}
                if current.get("status") == SessionStatus.AWAITING_APPROVAL.value:
                    self._checkpoint(run_id, session_id, RunStage.AWAITING_ACTION, {})
                    self.db.update_run(
                        run_id,
                        stage=RunStage.AWAITING_ACTION.value,
                        status="awaiting_action",
                    )
                else:
                    self.db.update_session(session_id, status=SessionStatus.COMPLETED.value)
                    self._checkpoint(run_id, session_id, RunStage.COMPLETED, {})
                    self.db.update_run(
                        run_id, stage=RunStage.COMPLETED.value, status="completed"
                    )
                self.hooks.emit(session_id, run_id, "done", {"answer": answer})
            except Exception as exc:  # noqa: BLE001 - runtime event boundary
                self.db.update_session(session_id, status=SessionStatus.FAILED.value)
                self.db.update_run(
                    run_id,
                    stage=RunStage.FAILED.value,
                    status="failed",
                    error_type=type(exc).__name__,
                    error_message=str(exc)[:2_000],
                )
                self._checkpoint(
                    run_id,
                    session_id,
                    RunStage.FAILED,
                    {"error_type": type(exc).__name__},
                )
                self.hooks.emit(
                    session_id,
                    run_id,
                    "error",
                    {"error": type(exc).__name__, "message": str(exc)},
                )

    def _checkpoint(
        self,
        run_id: str,
        session_id: str,
        stage: RunStage,
        state: dict[str, Any],
    ) -> None:
        self.db.update_run(run_id, stage=stage.value)
        self.db.save_checkpoint(
            f"{run_id}:{stage.value}",
            session_id,
            run_id,
            {"stage": stage.value, **state},
        )
        self.hooks.emit(session_id, run_id, "checkpoint", {"stage": stage.value})

    @staticmethod
    def _goal_ready(profile: dict[str, Any]) -> bool:
        return bool(
            str(profile.get("learning_topic") or "").strip()
            and str(profile.get("target_outcome") or "").strip()
            and profile.get("duration_days")
            and profile.get("daily_minutes")
        )
