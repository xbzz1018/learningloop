from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import platform
import statistics
import tempfile
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import SecretStr

from learningloop import __version__
from learningloop.agent import AgentService
from learningloop.config import Settings
from learningloop.db import Database
from learningloop.learning.content import fallback_course_plan
from learningloop.learning.daily import DailyLearningService
from learningloop.learning.state import LearningWorkspace
from learningloop.models import ActionDecision, CallContext, ModelRoute, RunRecord
from learningloop.notifications import MailService, NotificationScheduler

Case = Callable[[Path], Awaitable[dict[str, Any]]]


def make_settings(root: Path) -> Settings:
    return Settings(
        _env_file=None,
        data_dir=root,
        enable_real_models=False,
        notification_scheduler_enabled=False,
        vibe_flash_key=SecretStr("functional-eval-flash"),
        vibe_pro_key=SecretStr("functional-eval-pro"),
    )


def make_runtime(root: Path) -> tuple[Settings, Database, AgentService]:
    settings = make_settings(root)
    settings.prepare_directories()
    db = Database(settings.database_path)
    return settings, db, AgentService(settings, db)


async def react_tool_loop(root: Path) -> dict[str, Any]:
    class ChatLLM:
        def __init__(self) -> None:
            self.calls = 0

        async def complete(self, *args: Any, **kwargs: Any) -> dict[str, str]:
            self.calls += 1
            payload = (
                {"thought": "读取课程", "action": "get_course_state", "args": {}}
                if self.calls == 1
                else {
                    "thought": "状态已读取",
                    "action": "finish",
                    "answer": "当前还没有已批准的课程计划。",
                    "confidence": 1.0,
                }
            )
            return {"text": json.dumps(payload, ensure_ascii=False)}

    _, _, service = make_runtime(root)
    fake = ChatLLM()
    service.gateway.llm = fake
    session = service.create_session()
    answer = await service._run_agent(
        "查看当前课程",
        service.runtime.context_builder.build(session["id"]),
        service.skills.get("daily-tutoring"),
        ModelRoute.FLASH,
        CallContext(run_id="eval-react", session_id=session["id"], turn_id="turn"),
    )
    assert fake.calls == 2 and "没有已批准" in answer
    return {"model_calls": fake.calls, "answer_present": bool(answer)}


async def structured_plan(root: Path) -> dict[str, Any]:
    _, db, service = make_runtime(root)
    session = service.create_session()
    plan = fallback_course_plan("Python", duration_days=14).model_copy(
        update={"content_source": "model"}
    )

    class PlanLLM:
        async def complete(self, *args: Any, **kwargs: Any) -> dict[str, str]:
            return {"text": plan.model_dump_json()}

    service.gateway.llm = PlanLLM()
    await service._run_planning_flow(
        "制定 Python 计划",
        LearningWorkspace(service.settings.workspace_dir, session["id"]).snapshot(),
        service.skills.get("course-planning"),
        ModelRoute.FLASH,
        CallContext(run_id="eval-plan", session_id=session["id"], turn_id="turn"),
    )
    candidate = db.pending_actions(session["id"])[0]["payload"]["plan"]
    assert candidate["stages"] and candidate["stages"][0]["lessons"][0]["exercise"]
    return {
        "content_source": candidate["content_source"],
        "stages": len(candidate["stages"]),
    }


async def empty_plan_fallback(root: Path) -> dict[str, Any]:
    _, db, service = make_runtime(root)
    session = service.create_session()

    class EmptyLLM:
        async def complete(self, *args: Any, **kwargs: Any) -> dict[str, str]:
            return {"text": "{}"}

    service.gateway.llm = EmptyLLM()
    await service._run_planning_flow(
        "制定 SQL 学习计划",
        LearningWorkspace(service.settings.workspace_dir, session["id"]).snapshot(),
        service.skills.get("course-planning"),
        ModelRoute.FLASH,
        CallContext(run_id="eval-fallback", session_id=session["id"], turn_id="turn"),
    )
    candidate = db.pending_actions(session["id"])[0]["payload"]["plan"]
    assert candidate["content_source"] == "fallback"
    assert all(stage["lessons"] for stage in candidate["stages"])
    return {"content_source": "fallback", "stages": len(candidate["stages"])}


async def approval_idempotency(root: Path) -> dict[str, Any]:
    _, db, service = make_runtime(root)
    session = service.create_session()
    workspace = LearningWorkspace(service.settings.workspace_dir, session["id"])
    await service._run_planning_flow(
        "制定 Python 学习计划",
        workspace.snapshot(),
        service.skills.get("course-planning"),
        ModelRoute.FLASH,
        CallContext(run_id="eval-approval", session_id=session["id"], turn_id="turn"),
        plan_override=fallback_course_plan("Python").model_dump(mode="json"),
    )
    action = db.pending_actions(session["id"])[0]
    first = await service.decide_action(action["id"], ActionDecision.EXECUTE)
    version = workspace.course().version
    second = await service.decide_action(action["id"], ActionDecision.EXECUTE)
    assert first["today_plan"] and second["idempotent"] is True
    assert workspace.course().version == version
    return {"idempotent": True, "course_version": version}


async def task_mastery(root: Path) -> dict[str, Any]:
    _, db, service = make_runtime(root)
    session = service.create_session()
    workspace = LearningWorkspace(service.settings.workspace_dir, session["id"])
    workspace.save_course(fallback_course_plan("Python").model_copy(update={"approved": True}))
    db.add_message(session["id"], "user", "开始学习")
    plan = service.daily.save_deterministic_plan(session["id"])
    task = plan.tasks[0]
    result = await service.record_task_result(
        session["id"],
        plan.plan_date,
        task.id,
        score=0.85,
        answer="完成练习",
        notes="理解主要步骤",
        error_category=None,
        completed=True,
    )
    concepts = workspace.concepts()
    assert result["plan"]["tasks"][0]["completed"] is True and concepts
    concept = next(iter(concepts.values()))
    return {"task_completed": True, "mastery": concept.mastery}


async def low_score_error(root: Path) -> dict[str, Any]:
    _, db, service = make_runtime(root)
    session = service.create_session()
    workspace = LearningWorkspace(service.settings.workspace_dir, session["id"])
    workspace.save_course(fallback_course_plan("Agent").model_copy(update={"approved": True}))
    db.add_message(session["id"], "user", "开始练习")
    plan = service.daily.save_deterministic_plan(session["id"])
    await service.record_task_result(
        session["id"],
        plan.plan_date,
        plan.tasks[0].id,
        score=0.45,
        answer="工具结果",
        notes="参数校验不完整",
        error_category="application-failure",
        completed=True,
    )
    assert len(workspace.errors()) == 1 and len(workspace.reviews()) == 1
    return {"errors": 1, "review_cards": 1}


async def review_reschedule(root: Path) -> dict[str, Any]:
    _, db, service = make_runtime(root)
    session = service.create_session()
    workspace = LearningWorkspace(service.settings.workspace_dir, session["id"])
    workspace.save_course(fallback_course_plan("SQL").model_copy(update={"approved": True}))
    db.add_message(session["id"], "user", "开始复习")
    plan = service.daily.save_deterministic_plan(session["id"])
    await service.record_task_result(
        session["id"],
        plan.plan_date,
        plan.tasks[0].id,
        score=0.5,
        answer="第一次回答",
        notes="需要复习",
        error_category="concept-gap",
        completed=True,
    )
    concept_id = next(iter(workspace.concepts()))
    before = workspace.reviews()[concept_id]
    await service.record_review_result(
        session["id"],
        concept_id,
        score=0.9,
        answer="重新回答正确",
        notes="已掌握",
        error_category=None,
    )
    after = workspace.reviews()[concept_id]
    assert after.review_count == before.review_count + 1 and after.due_at > before.due_at
    return {"review_count": after.review_count, "due_extended": True}


async def notification_idempotency(root: Path) -> dict[str, Any]:
    settings, db, service = make_runtime(root)
    session = service.create_session()
    workspace = LearningWorkspace(settings.workspace_dir, session["id"])
    workspace.save_course(fallback_course_plan("Python").model_copy(update={"approved": True}))
    db.save_notification_settings(
        session["id"],
        email="learner@example.com",
        enabled=True,
        timezone="Asia/Shanghai",
        morning_time="08:30",
        evening_time="20:30",
    )
    scheduler = NotificationScheduler(
        settings,
        db,
        DailyLearningService(settings, db),
        MailService(settings),
    )
    now = datetime(2026, 9, 2, 13, 0, tzinfo=UTC)
    first = await scheduler.run_once(now=now, force=True)
    second = await scheduler.run_once(now=now, force=True)
    outbox = list(settings.notification_outbox_dir.glob("*.txt"))
    assert len(first) == 2 and second == [] and len(outbox) == 2
    return {"first_deliveries": 2, "duplicate_deliveries": 0}


async def owner_isolation(root: Path) -> dict[str, Any]:
    _, db, _ = make_runtime(root)
    db.create_user("owner-a", "alice", "functional-eval-hash-a")
    db.create_user("owner-b", "bob", "functional-eval-hash-b")
    session = db.create_session("owner-a-session", owner_id="owner-a")
    assert db.get_session_for_owner(session["id"], "owner-a") is not None
    assert db.get_session_for_owner(session["id"], "owner-b") is None
    return {"owner_a_visible": True, "owner_b_visible": False}


async def restart_recovery(root: Path) -> dict[str, Any]:
    settings, db, service = make_runtime(root)
    session = service.create_session()
    run_id = "recoverable-run"
    db.create_run(RunRecord(id=run_id, session_id=session["id"], turn_id="turn"))
    db.update_session(session["id"], status="running", current_run_id=run_id)
    db.save_checkpoint(
        f"{run_id}:context_ready",
        session["id"],
        run_id,
        {"stage": "context_ready"},
    )
    AgentService(settings, db)
    recovered = db.get_session(session["id"])
    run = db.get_run(run_id)
    assert recovered["status"] == "recovering" and run["status"] == "recovering"
    return {"session_status": "recovering", "run_status": "recovering"}


CASES: list[tuple[str, str, Case]] = [
    ("react_tool_loop", "agent_runtime", react_tool_loop),
    ("structured_plan", "structured_output", structured_plan),
    ("empty_plan_fallback", "structured_output", empty_plan_fallback),
    ("approval_idempotency", "recovery", approval_idempotency),
    ("task_mastery", "state_integrity", task_mastery),
    ("low_score_error", "state_integrity", low_score_error),
    ("review_reschedule", "state_integrity", review_reschedule),
    ("notification_idempotency", "idempotency", notification_idempotency),
    ("owner_isolation", "isolation", owner_isolation),
    ("restart_recovery", "recovery", restart_recovery),
]


async def run_case(base: Path, name: str, category: str, case: Case) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        details = await case(base / name)
        status = "passed"
        error = None
    except Exception as exc:  # noqa: BLE001 - evaluation must preserve every failure
        details = {}
        status = "failed"
        error = f"{type(exc).__name__}: {exc}"
    return {
        "name": name,
        "category": category,
        "status": status,
        "latency_ms": round((time.perf_counter() - started) * 1000, 2),
        "details": details,
        "error": error,
    }


def ratio(cases: list[dict[str, Any]], names: set[str]) -> float | None:
    selected = [case for case in cases if case["name"] in names]
    if not selected:
        return None
    return round(sum(case["status"] == "passed" for case in selected) / len(selected), 4)


def markdown_summary(report: dict[str, Any]) -> str:
    aggregate = report["aggregate"]
    rows = "\n".join(
        f"| {case['name']} | {case['category']} | {case['status']} | {case['latency_ms']:.2f} |"
        for case in report["cases"]
    )
    return f"""# LearningLoop Functional Evaluation V1

Generated at: `{report['generated_at']}`

## Aggregate

- Scenarios: {aggregate['passed']}/{aggregate['total']} passed
- Scenario pass rate: {aggregate['scenario_pass_rate']:.1%}
- Final structured artifact rate: {aggregate['structured_artifact_rate']:.1%}
- Recovery success rate: {aggregate['recovery_success_rate']:.1%}
- State integrity rate: {aggregate['state_integrity_rate']:.1%}
- Idempotency rate: {aggregate['idempotency_rate']:.1%}
- Offline scenario latency P50/P95: {aggregate['p50_latency_ms']:.2f}/{aggregate['p95_latency_ms']:.2f} ms

These are deterministic functional scenarios, not model-quality or production-load metrics.

## Cases

| Case | Category | Status | Latency ms |
|---|---|---:|---:|
{rows}
"""


async def main_async(output_dir: Path) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="learningloop-functional-eval-", ignore_cleanup_errors=True
    ) as temp:
        base = Path(temp)
        cases = [await run_case(base, name, category, case) for name, category, case in CASES]
    latencies = sorted(float(case["latency_ms"]) for case in cases)
    p95_index = max(0, min(len(latencies) - 1, int(0.95 * len(latencies) + 0.9999) - 1))
    passed = sum(case["status"] == "passed" for case in cases)
    report = {
        "suite_id": "learningloop-functional-v1",
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "environment": {
            "learningloop_version": __version__,
            "python": platform.python_version(),
            "platform": platform.platform(),
            "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        },
        "cases": cases,
        "aggregate": {
            "total": len(cases),
            "passed": passed,
            "failed": len(cases) - passed,
            "scenario_pass_rate": round(passed / len(cases), 4),
            "structured_artifact_rate": ratio(
                cases, {"structured_plan", "empty_plan_fallback"}
            ),
            "recovery_success_rate": ratio(
                cases, {"approval_idempotency", "restart_recovery"}
            ),
            "state_integrity_rate": ratio(
                cases, {"task_mastery", "low_score_error", "review_reschedule"}
            ),
            "idempotency_rate": ratio(
                cases, {"approval_idempotency", "notification_idempotency"}
            ),
            "p50_latency_ms": round(statistics.median(latencies), 2),
            "p95_latency_ms": round(latencies[p95_index], 2),
        },
    }
    (output_dir / "functional-v1.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (output_dir / "functional-v1.md").write_text(
        markdown_summary(report), encoding="utf-8"
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=Path("evaluations/results"))
    args = parser.parse_args()
    report = asyncio.run(main_async(args.output_dir))
    print(json.dumps(report["aggregate"], ensure_ascii=False, indent=2))
    return 0 if report["aggregate"]["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
