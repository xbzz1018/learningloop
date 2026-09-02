"""Deterministic measurement helpers for Agent routing and context boundaries."""

from __future__ import annotations

import json
import math
from typing import Any

from learningloop.agent.context import ContextBuilder
from learningloop.config import Settings
from learningloop.db import Database


def estimate_tokens(value: Any) -> int:
    """Use a documented UTF-8 estimate when a provider tokenizer is unavailable."""
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    return max(1, math.ceil(len(text.encode("utf-8")) / 4))


def context_metrics(settings: Settings, db: Database, session_id: str | None) -> dict[str, Any]:
    if not session_id:
        return {
            "full_context_tokens": None,
            "bounded_context_tokens": None,
            "context_reduction": None,
        }
    messages = db.fetch_all(
        "SELECT role,content,created_at FROM messages WHERE session_id=? ORDER BY id",
        (session_id,),
    )
    if not messages:
        return {"full_context_tokens": 0, "bounded_context_tokens": 0, "context_reduction": None}
    full_tokens = estimate_tokens(messages)
    bounded_tokens = estimate_tokens(ContextBuilder(settings, db).build(session_id).render(""))
    reduction = max(0.0, 1 - bounded_tokens / full_tokens) if full_tokens else None
    return {
        "full_context_tokens": full_tokens,
        "bounded_context_tokens": bounded_tokens,
        "context_reduction": round(reduction, 4) if reduction is not None else None,
    }


def usage_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    calls = len(rows)
    by_role: dict[str, int] = {}
    by_route: dict[str, int] = {}
    costs = [row.get("estimated_cost_usd") for row in rows]
    for row in rows:
        role = str(row.get("agent_role") or "interactive")
        route = str(row.get("model_route") or "unknown")
        by_role[role] = by_role.get(role, 0) + 1
        by_route[route] = by_route.get(route, 0) + 1
    total_cost = (
        sum(float(cost) for cost in costs if cost is not None)
        if costs and all(cost is not None for cost in costs)
        else None
    )
    return {
        "calls": calls,
        "calls_by_agent_role": by_role,
        "calls_by_model_route": by_route,
        "flash_call_share": round(by_route.get("flash", 0) / calls, 4) if calls else None,
        "estimated_cost_usd": total_cost,
        "cost_comparison_vs_pro_only": None,
    }
