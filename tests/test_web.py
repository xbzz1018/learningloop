from fastapi.testclient import TestClient

from learningloop.learning.content import fallback_course_plan
from learningloop.learning.daily import DailyLearningService
from learningloop.learning.state import LearningWorkspace
from learningloop.web import create_app


def test_health_and_session_flow(settings) -> None:
    client = TestClient(create_app(settings))
    health = client.get("/health")
    assert health.status_code == 200
    assert health.headers["x-request-id"]
    assert health.json()["providers"]["vibe_flash"]["configured"] is True
    session = client.post("/api/v1/sessions")
    assert session.status_code == 201
    session_id = session.json()["id"]
    state = client.get(f"/api/v1/sessions/{session_id}/state")
    assert state.status_code == 200
    assert state.json()["learning"]["learner"]["daily_minutes"] == 45
    activity = client.get(f"/api/v1/sessions/{session_id}/activity")
    assert activity.status_code == 200
    assert "events" in activity.json() and "runs" in activity.json()
    page = client.get(f"/?session_id={session_id}")
    assert page.status_code == 200
    assert "LearningLoop" in page.text
    assert "学习助手" in page.text
    for view in ("plan", "progress", "review", "usage", "notifications"):
        response = client.get("/", params={"session_id": session_id, "view": view})
        assert response.status_code == 200


def test_notification_enable_requires_verified_smtp(settings) -> None:
    client = TestClient(create_app(settings))
    session_id = client.post("/api/v1/sessions").json()["id"]
    result = client.put(
        f"/api/v1/notifications/settings/{session_id}",
        json={
            "email": "learner@example.com",
            "enabled": True,
            "timezone": "Asia/Shanghai",
            "morning_time": "08:30",
            "evening_time": "20:30",
        },
    )
    assert result.status_code == 200
    assert result.json()["enabled"] is False
    assert result.json()["activation_required"] is True
    test_mail = client.post(f"/api/v1/notifications/test/{session_id}")
    assert test_mail.status_code == 200
    assert test_mail.json()["delivery_mode"] == "local_outbox"


def test_usage_missing_values_are_not_zero(settings) -> None:
    client = TestClient(create_app(settings))
    usage = client.get("/api/v1/usage").json()
    assert usage["calls"] == 0
    assert usage["input_tokens"] is None
    assert usage["estimated_cost_usd"] is None


def test_task_result_updates_plan_mastery_and_review(settings, db) -> None:
    client = TestClient(create_app(settings))
    session_id = client.post("/api/v1/sessions").json()["id"]
    workspace = LearningWorkspace(settings.workspace_dir, session_id)
    workspace.save_course(
        fallback_course_plan("Python", duration_days=10).model_copy(update={"approved": True})
    )
    db.add_message(session_id, "user", "我开始学习 Python")
    plan = DailyLearningService(settings, db).save_deterministic_plan(session_id)
    task = plan.tasks[0]

    started = client.post(f"/api/v1/plans/{session_id}/tasks/{task.id}/start")
    assert started.status_code == 200
    result = client.post(
        f"/api/v1/plans/{session_id}/tasks/{task.id}/result",
        json={
            "score": 0.55,
            "answer": "完成了练习",
            "notes": "循环边界还需要复习",
            "error_category": "concept-gap",
            "completed": True,
        },
    )
    assert result.status_code == 200
    assert result.json()["plan"]["tasks"][0]["score"] == 0.55
    state = client.get(f"/api/v1/sessions/{session_id}/state").json()["learning"]
    assert state["concepts"]
    assert state["recent_errors"]
    assert LearningWorkspace(settings.workspace_dir, session_id).reviews()
    concept_id = next(iter(state["concepts"]))
    review = client.post(
        f"/api/v1/reviews/{session_id}/items/{concept_id}/result",
        json={"score": 0.9, "answer": "复述完成", "notes": "已能解释核心概念"},
    )
    assert review.status_code == 200
    assert review.json()["status"] == "recorded"


def test_search_prefers_capability_checked_provider(settings) -> None:
    from learningloop.db import Database
    from learningloop.llm.search import SearchService

    db = Database(settings.database_path)
    checked_at = "2026-08-31T00:00:00+00:00"
    for alias, ok in (("vibe", 0), ("kcne", 1)):
        db.execute(
            "INSERT OR REPLACE INTO provider_capabilities("
            "provider_alias,model_route,checked_at,web_search_ok"
            ") VALUES(?,?,?,?)",
            (alias, "flash", checked_at, ok),
        )
    assert SearchService(settings, db)._provider_order() == ("kcne", "vibe")


def test_agent_trace_and_role_usage_endpoints(settings) -> None:
    import asyncio

    app = create_app(settings)
    client = TestClient(app)
    session_id = client.post("/api/v1/sessions").json()["id"]
    workspace = LearningWorkspace(settings.workspace_dir, session_id)
    workspace.save_course(
        fallback_course_plan("Python", duration_days=10).model_copy(update={"approved": True})
    )
    run_service = app.state.service
    asyncio.run(run_service.run_autonomous_plan(session_id))
    run_id = app.state.db.agent_runs_for_session(session_id)[0]["id"]

    trace = client.get(f"/api/v1/runs/{run_id}/trace")
    assert trace.status_code == 200
    assert trace.json()["run"]["agent_role"] == "autonomous"
    assert trace.json()["artifacts"]
    status = client.get(f"/api/v1/sessions/{session_id}/agent-status")
    assert status.status_code == 200
    assert status.json()["latest"]["agent_role"] == "autonomous"
    usage = client.get(f"/api/v1/usage/agents?session_id={session_id}")
    assert usage.status_code == 200
    assert usage.json()["agents"] == []
