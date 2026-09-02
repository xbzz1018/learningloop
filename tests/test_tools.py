from __future__ import annotations

from learningloop.learning.state import LearningWorkspace
from learningloop.learning.tools import apply_approved_tool, build_tools
from learningloop.llm.context import call_context
from learningloop.llm.search import SearchService
from learningloop.models import CallContext, ModelRoute


async def test_record_result_updates_concept_and_review(settings, db) -> None:
    db.create_session("session-1")
    db.add_message("session-1", "user", "My answer")
    tools = build_tools(settings, db, SearchService(settings, db))
    context = CallContext(run_id="run", session_id="session-1", turn_id="turn")
    with call_context(context, ModelRoute.FLASH):
        result = await tools["record_learning_result"].execute(
            concept_id="tool-calling",
            concept_name="Tool Calling",
            score=0.5,
            answer="answer",
            feedback="needs work",
            error_category="concept-gap",
        )
    assert result["status"] == "recorded"
    workspace = LearningWorkspace(settings.workspace_dir, "session-1")
    assert workspace.concepts()["tool-calling"].attempts == 1
    assert "tool-calling" in workspace.reviews()
    assert len(workspace.errors()) == 1


async def test_course_plan_requires_approval(settings, db) -> None:
    db.create_session("session-2")
    db.add_message("session-2", "user", "Create a plan")
    tools = build_tools(settings, db, SearchService(settings, db))
    context = CallContext(run_id="run", session_id="session-2", turn_id="turn")
    plan = {
        "title": "Agent Basics",
        "goal": "Build an agent",
        "duration_days": 14,
        "final_artifact": "Demo",
        "stages": [
            {
                "id": "tool-calling",
                "title": "Tool Calling",
                "objective": "Use one tool safely",
                "estimated_days": 3,
                "prerequisite_ids": [],
            }
        ],
    }
    with call_context(context, ModelRoute.FLASH):
        proposed = await tools["create_or_replace_course_plan"].execute(plan=plan)
    approval = db.get_approval(proposed["approval_id"])
    assert approval["status"] == "pending"
    assert LearningWorkspace(settings.workspace_dir, "session-2").course().title == ""
    result = apply_approved_tool(settings, approval)
    assert result["status"] == "applied"
    assert LearningWorkspace(settings.workspace_dir, "session-2").course().approved is True
