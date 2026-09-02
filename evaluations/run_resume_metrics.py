"""Freeze resume-facing routing, context, and official-price metrics.

This benchmark spends a bounded number of real model calls. It compares prompts
using provider-reported input tokens and calculates a counterfactual Pro-only
estimate from the exact same observed token counts. It is not a model-quality
benchmark or an actual provider bill.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import tempfile
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from learningloop.config import Settings
from learningloop.db import Database
from learningloop.llm import ModelGateway, call_context
from learningloop.models import AgentRole, CallContext, ModelRoute, TaskMetadata, UsageData
from learningloop.skills import SkillCatalog
from learningloop.usage import PRICING_VERSION, add_estimated_cost

ROUTING_CASES = (
    ("goal_intake", TaskMetadata(operation="chat"), "确认 Python 学习目标和当前基础。"),
    ("concept_explanation", TaskMetadata(operation="chat"), "解释 Python 迭代器。"),
    ("practice_generation", TaskMetadata(operation="chat"), "生成一道迭代器练习。"),
    ("answer_feedback", TaskMetadata(operation="chat"), "点评一份学习答案。"),
    ("daily_plan", TaskMetadata(operation="daily_plan"), "生成今天的学习任务摘要。"),
    ("daily_review", TaskMetadata(operation="daily_review"), "总结今天的学习记录。"),
    ("due_review", TaskMetadata(operation="review"), "为到期知识点生成复习建议。"),
    ("normal_plan", TaskMetadata(operation="chat", duration_days=30), "制定 30 天学习计划。"),
    ("long_plan", TaskMetadata(operation="deep_plan", duration_days=90), "制定 90 天跨阶段计划。"),
    (
        "major_recovery",
        TaskMetadata(operation="major_recovery", affected_fraction=0.45),
        "为大范围延期生成恢复方案。",
    ),
)


def benchmark_hash() -> str:
    payload = [
        {"id": case_id, "metadata": metadata.model_dump(mode="json"), "prompt": prompt}
        for case_id, metadata, prompt in ROUTING_CASES
    ]
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


def _counterfactual_pro_cost(row: dict[str, Any]) -> float | None:
    if row.get("input_tokens") is None or row.get("output_tokens") is None:
        return None
    usage = UsageData(
        input_tokens=int(row["input_tokens"]),
        cached_input_tokens=(
            int(row["cached_input_tokens"]) if row.get("cached_input_tokens") is not None else None
        ),
        cache_miss_input_tokens=(
            int(row["cache_miss_input_tokens"])
            if row.get("cache_miss_input_tokens") is not None
            else None
        ),
        output_tokens=int(row["output_tokens"]),
        total_tokens=(int(row["total_tokens"]) if row.get("total_tokens") is not None else None),
    )
    priced = add_estimated_cost(usage, ModelRoute.PRO.value, datetime.fromisoformat(row["started_at"]))
    return priced.estimated_cost_usd


async def _call(
    gateway: ModelGateway,
    db: Database,
    *,
    source: str,
    route: ModelRoute,
    prompt: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    run_id = f"resume-metric-{source}-{uuid.uuid4().hex}"
    context = CallContext(
        run_id=run_id,
        session_id="resume-metrics",
        turn_id=run_id,
        task_type="resume_metric",
        call_site=source,
        agent_role=AgentRole.INTERACTIVE,
    )
    with call_context(context, route):
        response = await gateway.llm.complete(
            system="Return a compact JSON object with one boolean field named ok.",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            max_completion_tokens=64,
            reasoning_effort="low",
            source=source,
        )
    parsed = json.loads(str(response.get("text") or "{}"))
    if not isinstance(parsed, dict):
        raise ValueError(f"{source} did not return a JSON object")
    rows = db.model_calls_for_run(run_id)
    if len(rows) != 1:
        raise RuntimeError(f"{source} expected one model call, got {len(rows)}")
    return parsed, rows[0]


async def _context_pair(
    gateway: ModelGateway,
    db: Database,
    *,
    name: str,
    baseline: str,
    optimized: str,
) -> dict[str, Any]:
    _, baseline_row = await _call(
        gateway, db, source=f"{name}_baseline", route=ModelRoute.FLASH, prompt=baseline
    )
    _, optimized_row = await _call(
        gateway, db, source=f"{name}_optimized", route=ModelRoute.FLASH, prompt=optimized
    )
    before = baseline_row.get("input_tokens")
    after = optimized_row.get("input_tokens")
    reduction = None
    if before and after is not None:
        reduction = max(0.0, 1 - float(after) / float(before))
    return {
        "baseline_input_tokens": before,
        "optimized_input_tokens": after,
        "reduction": round(reduction, 4) if reduction is not None else None,
        "usage_source": baseline_row.get("usage_source"),
    }


async def run(output: Path) -> dict[str, Any]:
    repo_root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix="learningloop-resume-metrics-", ignore_cleanup_errors=True) as tmp:
        settings = Settings(
            _env_file=repo_root / ".env",
            data_dir=Path(tmp),
            skills_dir=repo_root / "skills",
            enable_real_models=True,
            enable_relay_fallback=False,
            notification_scheduler_enabled=False,
        )
        settings.prepare_directories()
        if settings.deepseek_api_key is None:
            raise RuntimeError("official DeepSeek API key is not configured")
        db = Database(settings.database_path)
        gateway = ModelGateway(settings, db)

        routing_results: list[dict[str, Any]] = []
        for case_id, metadata, prompt in ROUTING_CASES:
            route = gateway.policy.choose(metadata)
            _, row = await _call(
                gateway, db, source=f"routing_{case_id}", route=route, prompt=prompt
            )
            routing_results.append(
                {
                    "case_id": case_id,
                    "route": route.value,
                    "input_tokens": row.get("input_tokens"),
                    "output_tokens": row.get("output_tokens"),
                    "estimated_cost_usd": row.get("estimated_cost_usd"),
                    "status": row.get("status"),
                }
            )

        catalog = SkillCatalog(settings.skills_dir)
        skill_names = sorted(catalog.REQUIRED)
        all_skills = "\n\n".join(catalog.get(name).render() for name in skill_names)
        selected_skill = catalog.get("daily-tutoring").render()
        skill_metric = await _context_pair(
            gateway,
            db,
            name="skill_loading",
            baseline=f"全部 Skill:\n{all_skills}\n\n任务:解释迭代器。",
            optimized=f"命中 Skill:\n{selected_skill}\n\n任务:解释迭代器。",
        )

        messages = [
            {"role": "user" if index % 2 == 0 else "assistant", "content": f"第 {index + 1} 轮学习记录：迭代器、生成器和错误反馈。" * 4}
            for index in range(24)
        ]
        summary = "较早对话摘要：目标为掌握迭代器；薄弱点是 StopIteration；下一步完成生成器练习。"
        state = {"course": "Python 基础", "mastery": 0.62, "due_reviews": ["iterator"]}
        full_context = json.dumps(
            {"messages": messages, "learning_state": state}, ensure_ascii=False
        )
        bounded_context = json.dumps(
            {"recent_messages": messages[-8:], "older_summary": summary, "learning_state": state},
            ensure_ascii=False,
        )
        context_metric = await _context_pair(
            gateway,
            db,
            name="bounded_context",
            baseline=f"{selected_skill}\n{full_context}",
            optimized=f"{selected_skill}\n{bounded_context}",
        )
        summary_metric = await _context_pair(
            gateway,
            db,
            name="summary_compression",
            baseline=json.dumps(messages[:-8], ensure_ascii=False),
            optimized=summary,
        )

        flash_calls = sum(item["route"] == ModelRoute.FLASH.value for item in routing_results)
        mixed_costs = [item["estimated_cost_usd"] for item in routing_results]
        call_rows = [
            db.model_calls_for_run(row["run_id"])[0]
            for row in db.fetch_all(
                "SELECT DISTINCT run_id FROM model_calls WHERE call_site LIKE 'routing_%' ORDER BY run_id"
            )
        ]
        pro_costs = [_counterfactual_pro_cost(row) for row in call_rows]
        mixed_cost = (
            sum(float(value) for value in mixed_costs if value is not None)
            if all(value is not None for value in mixed_costs)
            else None
        )
        pro_only_cost = (
            sum(float(value) for value in pro_costs if value is not None)
            if all(value is not None for value in pro_costs)
            else None
        )
        cost_reduction = None
        if mixed_cost is not None and pro_only_cost:
            cost_reduction = 1 - mixed_cost / pro_only_cost

        report = {
            "suite_id": "learningloop-resume-metrics-v1",
            "generated_at": datetime.now().astimezone().isoformat(),
            "benchmark_sha256": benchmark_hash(),
            "pricing_version": PRICING_VERSION,
            "provider": "official",
            "models": {
                "flash": settings.deepseek_flash_model,
                "pro": settings.deepseek_pro_model,
            },
            "routing": {
                "total_cases": len(routing_results),
                "flash_cases": flash_calls,
                "pro_cases": len(routing_results) - flash_calls,
                "flash_share": round(flash_calls / len(routing_results), 4),
                "cases": routing_results,
            },
            "context": {
                "skill_progressive_loading": skill_metric,
                "bounded_history": context_metric,
                "summary_compression": summary_metric,
            },
            "cost": {
                "mixed_route_estimated_usd": mixed_cost,
                "counterfactual_pro_only_estimated_usd": pro_only_cost,
                "estimated_reduction": (
                    round(cost_reduction, 4) if cost_reduction is not None else None
                ),
                "actual_bill": None,
                "method": "same observed token counts repriced with official Pro rates",
            },
            "limitations": [
                "Routing cases validate policy and JSON completion, not answer quality.",
                "Cost is an official-price estimate, not the provider bill.",
                "Context reductions use provider-reported input tokens for fixed prompts.",
            ],
        }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Confirm real billable model calls.")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("evaluations/results/resume-metrics-v1.json"),
    )
    args = parser.parse_args()
    if not args.live:
        raise SystemExit("Pass --live to acknowledge real model calls.")
    report = asyncio.run(run(args.output))
    print(json.dumps({
        "routing": report["routing"],
        "context": report["context"],
        "cost": report["cost"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
