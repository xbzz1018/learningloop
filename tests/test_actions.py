from __future__ import annotations

import json

import pytest

from learningloop.agent import AgentService
from learningloop.learning.state import LearningWorkspace
from learningloop.models import ActionDecision, CallContext, ModelRoute


class PlanLLM:
    async def complete(self, *args, **kwargs):
        return {
            "text": json.dumps(
                {
                    "title": "Python 计划",
                    "goal": "掌握 Python 基础",
                    "duration_days": 14,
                    "final_artifact": "一个练习项目",
                    "stages": [
                        {
                            "id": "syntax",
                            "title": "语法基础",
                            "objective": "掌握变量和循环",
                            "estimated_days": 3,
                            "prerequisite_ids": [],
                            "completed": False,
                        }
                    ],
                },
                ensure_ascii=False,
            )
        }


@pytest.mark.asyncio
async def test_action_execute_applies_plan_without_chat_message(settings, db) -> None:
    service = AgentService(settings, db)
    service.gateway.llm = PlanLLM()
    session = service.create_session()
    workspace = LearningWorkspace(settings.workspace_dir, session["id"])
    context = CallContext(run_id="run", session_id=session["id"], turn_id="turn")
    skill = service.skills.select("制定计划", has_course=False, has_due_reviews=False)
    await service._run_planning_flow("制定计划", workspace.snapshot(), skill, ModelRoute.FLASH, context)
    action = db.pending_actions(session["id"])[0]
    before_messages = db.message_count(session["id"])
    result = await service.decide_action(action["id"], ActionDecision.EXECUTE)
    assert result["today_plan"]["session_id"] == session["id"]
    assert db.message_count(session["id"]) == before_messages
    assert workspace.course().approved is True
    assert db.pending_actions(session["id"]) == []


@pytest.mark.asyncio
async def test_repeated_action_decision_returns_existing_state(settings, db) -> None:
    service = AgentService(settings, db)
    service.gateway.llm = PlanLLM()
    session = service.create_session()
    workspace = LearningWorkspace(settings.workspace_dir, session["id"])
    context = CallContext(run_id="run-idempotent", session_id=session["id"], turn_id="turn")
    skill = service.skills.select("制定计划", has_course=False, has_due_reviews=False)
    await service._run_planning_flow("制定计划", workspace.snapshot(), skill, ModelRoute.FLASH, context)
    action = db.pending_actions(session["id"])[0]
    first = await service.decide_action(action["id"], ActionDecision.EXECUTE)
    second = await service.decide_action(action["id"], ActionDecision.EXECUTE)
    assert first["today_plan"]["session_id"] == session["id"]
    assert second["idempotent"] is True
    assert second["status"] == "completed"
    assert db.message_count(session["id"]) == 0


@pytest.mark.asyncio
async def test_action_suggest_creates_new_proposal_without_chat_message(settings, db) -> None:
    service = AgentService(settings, db)
    service.gateway.llm = PlanLLM()
    session = service.create_session()
    workspace = LearningWorkspace(settings.workspace_dir, session["id"])
    context = CallContext(run_id="run", session_id=session["id"], turn_id="turn")
    skill = service.skills.select("制定计划", has_course=False, has_due_reviews=False)
    await service._run_planning_flow("制定计划", workspace.snapshot(), skill, ModelRoute.FLASH, context)
    action = db.pending_actions(session["id"])[0]
    result = await service.decide_action(action["id"], ActionDecision.SUGGEST, "减少每天任务")
    assert result["status"] == "suggested"
    pending = db.pending_actions(session["id"])
    assert len(pending) == 1
    assert pending[0]["id"] != action["id"]
    assert db.message_count(session["id"]) == 0


@pytest.mark.asyncio
async def test_complete_goal_creates_checkpoint_then_plan_proposal(settings, db) -> None:
    service = AgentService(settings, db)
    service.gateway.llm = PlanLLM()
    session = service.create_session()
    workspace = LearningWorkspace(settings.workspace_dir, session["id"])
    profile = workspace.learner().model_copy(
        update={
            "learning_topic": "Python",
            "target_outcome": "完成一个命令行项目",
            "duration_days": 14,
            "daily_minutes": 30,
            "background": "掌握基础语法",
        }
    )
    workspace.save_learner(profile)
    service._maybe_create_goal_checkpoint(
        session_id=session["id"], run_id="goal-run", selected_skill="goal-anchoring"
    )
    checkpoint = db.pending_actions(session["id"])[0]
    assert checkpoint["action_type"] == "workflow_checkpoint"
    result = await service.decide_action(checkpoint["id"], ActionDecision.NEXT)
    assert result["new_action"]["action_type"] == "plan_approval"
    assert LearningWorkspace(settings.workspace_dir, session["id"]).course().approved is False
