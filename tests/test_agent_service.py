from __future__ import annotations

import json

from learningloop.agent import AgentService
from learningloop.learning.content import fallback_course_plan
from learningloop.learning.state import LearningWorkspace
from learningloop.models import AgentRole, CallContext, ModelRoute, TaskMetadata


class PlanLLM:
    async def complete(self, *args, **kwargs):
        return {
            "text": """
            {
              "title": "Agent Foundations",
              "goal": "Build a stateful tool-calling agent",
              "duration_days": 30,
              "final_artifact": "A local agent demo",
              "stages": [
                {
                  "id": "tool-calling",
                  "title": "Tool Calling",
                  "objective": "Call one typed tool safely",
                  "estimated_days": 5,
                  "prerequisite_ids": [],
                  "completed": false
                }
              ]
            }
            """
        }


async def test_planning_flow_always_creates_approval(settings, db) -> None:
    service = AgentService(settings, db)
    service.gateway.llm = PlanLLM()
    session = service.create_session()
    workspace = LearningWorkspace(settings.workspace_dir, session["id"])
    skill = service.skills.select("制定计划", has_course=True, has_due_reviews=False)
    context = CallContext(run_id="run", session_id=session["id"], turn_id="turn")
    answer = await service._run_planning_flow(
        "制定30天计划", workspace.snapshot(), skill, ModelRoute.PRO, context
    )
    pending = db.fetch_all(
        "SELECT * FROM approvals WHERE session_id=? AND status='pending'", (session["id"],)
    )
    assert len(pending) == 1
    assert workspace.course().title == ""
    assert "尚未生效" in answer


async def test_react_tool_loop_completes_with_async_working_memory(settings, db) -> None:
    """回归 Harness fire(None) 故障：工具结果为 dict 时也必须正常完成。"""

    class ChatLLM:
        def __init__(self) -> None:
            self.calls = 0

        async def complete(self, *args, **kwargs):
            self.calls += 1
            response = (
                {"thought": "读取课程状态", "action": "get_course_state", "args": {}}
                if self.calls == 1
                else {
                    "thought": "课程状态已读取",
                    "action": "finish",
                    "answer": "当前还没有已批准的课程计划。",
                    "confidence": 1.0,
                }
            )
            return {"text": json.dumps(response, ensure_ascii=False)}

    service = AgentService(settings, db)
    fake = ChatLLM()
    service.gateway.llm = fake
    session = service.create_session()
    bundle = service.runtime.context_builder.build(session["id"])
    skill = service.skills.get("daily-tutoring")
    context = CallContext(run_id="chat-run", session_id=session["id"], turn_id="chat-turn")

    answer = await service._run_agent(
        "请查看当前课程状态。", bundle, skill, ModelRoute.FLASH, context
    )

    assert answer == "当前还没有已批准的课程计划。"
    assert fake.calls == 2


async def test_planning_failure_uses_non_empty_deterministic_fallback(settings, db) -> None:
    class BrokenLLM:
        async def complete(self, *args, **kwargs):
            raise TimeoutError("provider timeout")

    service = AgentService(settings, db)
    service.gateway.llm = BrokenLLM()
    session = service.create_session()
    workspace = LearningWorkspace(settings.workspace_dir, session["id"])
    skill = service.skills.get("course-planning")
    context = CallContext(run_id="fallback-run", session_id=session["id"], turn_id="fallback-turn")

    answer = await service._run_planning_flow(
        "制定 Python 14 天学习计划",
        workspace.snapshot(),
        skill,
        ModelRoute.FLASH,
        context,
    )

    action = db.pending_actions(session["id"])[0]
    plan = action["payload"]["plan"]
    assert "本地模板补全" in answer
    assert plan["content_source"] == "fallback"
    assert plan["stages"][0]["lessons"][0]["exercise"]


def test_submit_rejects_concurrent_session_run(settings, db) -> None:
    service = AgentService(settings, db)
    session = service.create_session()
    service._active_sessions.add(session["id"])
    try:
        service.submit(session["id"], "continue", TaskMetadata())
    except RuntimeError as exc:
        assert "active run" in str(exc)
    else:
        raise AssertionError("concurrent submit was accepted")


async def test_autonomous_plan_records_role_and_structured_artifact(settings, db) -> None:
    service = AgentService(settings, db)
    session = service.create_session()
    workspace = LearningWorkspace(settings.workspace_dir, session["id"])
    workspace.save_course(
        fallback_course_plan("Python", duration_days=10).model_copy(update={"approved": True})
    )

    plan = await service.run_autonomous_plan(session["id"])

    runs = db.agent_runs_for_session(session["id"])
    assert runs and runs[0]["agent_role"] == AgentRole.AUTONOMOUS.value
    assert runs[0]["status"] == "completed"
    artifacts = db.agent_artifacts_for_run(runs[0]["id"])
    assert artifacts and artifacts[0]["artifact_type"] == "daily_plan"
    assert artifacts[0]["payload"]["id"] == plan.id
