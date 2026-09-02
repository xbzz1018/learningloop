from __future__ import annotations

import math
from datetime import UTC, datetime
from statistics import median
from typing import Any

from learningloop.models import UsageData, UsageSummary

PRICING_VERSION = "deepseek-official-2026-08-16"
PRICES = {
    "flash": {
        "offpeak": {"cache": 0.007, "miss": 0.22, "output": 0.66},
        "peak": {"cache": 0.014, "miss": 0.44, "output": 1.32},
    },
    "pro": {
        "offpeak": {"cache": 0.022, "miss": 0.66, "output": 1.98},
        "peak": {"cache": 0.044, "miss": 1.32, "output": 3.96},
    },
}


def _nullable_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def normalize_chat_usage(raw: dict[str, Any] | None) -> UsageData:
    if not raw:
        return UsageData(usage_unknown=True, usage_source="chat")
    input_tokens = _nullable_int(raw.get("tokens_in", raw.get("prompt_tokens")))
    output_tokens = _nullable_int(raw.get("tokens_out", raw.get("completion_tokens")))
    cached = _nullable_int(raw.get("cached_input_tokens", raw.get("prompt_cache_hit_tokens")))
    miss = _nullable_int(raw.get("prompt_cache_miss_tokens"))
    if miss is None and input_tokens is not None and cached is not None:
        miss = max(input_tokens - cached, 0)
    total = _nullable_int(raw.get("total_tokens"))
    if total is None and input_tokens is not None and output_tokens is not None:
        total = input_tokens + output_tokens
    return UsageData(
        input_tokens=input_tokens,
        cached_input_tokens=cached,
        cache_miss_input_tokens=miss,
        output_tokens=output_tokens,
        reasoning_tokens=_nullable_int(raw.get("reasoning_tokens")),
        total_tokens=total,
        actual_cost_usd=raw.get("cost_usd"),
        usage_source="chat",
        usage_unknown=input_tokens is None and output_tokens is None,
    )


def normalize_responses_usage(raw: Any) -> UsageData:
    if raw is None:
        return UsageData(usage_unknown=True, usage_source="responses")
    if hasattr(raw, "model_dump"):
        raw = raw.model_dump()
    input_tokens = _nullable_int(raw.get("input_tokens"))
    output_tokens = _nullable_int(raw.get("output_tokens"))
    input_details = raw.get("input_tokens_details") or {}
    output_details = raw.get("output_tokens_details") or {}
    cached = _nullable_int(input_details.get("cached_tokens"))
    miss = None
    if input_tokens is not None and cached is not None:
        miss = max(input_tokens - cached, 0)
    total = _nullable_int(raw.get("total_tokens"))
    if total is None and input_tokens is not None and output_tokens is not None:
        total = input_tokens + output_tokens
    return UsageData(
        input_tokens=input_tokens,
        cached_input_tokens=cached,
        cache_miss_input_tokens=miss,
        output_tokens=output_tokens,
        reasoning_tokens=_nullable_int(output_details.get("reasoning_tokens")),
        total_tokens=total,
        usage_source="responses",
        usage_unknown=input_tokens is None and output_tokens is None,
    )


def pricing_period(timestamp: datetime) -> str:
    utc = timestamp.astimezone(UTC)
    if utc.weekday() >= 5:
        return "offpeak"
    hour = utc.hour + utc.minute / 60
    return "peak" if (1 <= hour < 4 or 6 <= hour < 10) else "offpeak"


def add_estimated_cost(usage: UsageData, route: str, timestamp: datetime) -> UsageData:
    if usage.input_tokens is None or usage.output_tokens is None:
        return usage
    prices = PRICES[route][pricing_period(timestamp)]
    cached = usage.cached_input_tokens or 0
    miss = usage.cache_miss_input_tokens
    if miss is None:
        miss = max(usage.input_tokens - cached, 0)
    cost = (
        cached * prices["cache"] + miss * prices["miss"] + usage.output_tokens * prices["output"]
    ) / 1_000_000
    return usage.model_copy(update={"estimated_cost_usd": cost, "pricing_version": PRICING_VERSION})


def _sum_nullable(rows: list[dict[str, Any]], key: str) -> int | float | None:
    values = [row[key] for row in rows if row.get(key) is not None]
    return sum(values) if values else None


def _percentile(values: list[int], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(percentile * len(ordered)) - 1))
    return float(ordered[index])


def aggregate_usage(rows: list[dict[str, Any]]) -> UsageSummary:
    cached = _sum_nullable(rows, "cached_input_tokens")
    input_tokens = _sum_nullable(rows, "input_tokens")
    cache_rate = None
    cache_state = "no_data"
    if rows:
        if cached is None:
            cache_state = "unknown"
        elif cached == 0:
            cache_state = "reported_zero"
        else:
            cache_state = "reported"
    if cached is not None and input_tokens:
        cache_rate = float(cached) / float(input_tokens)
    latencies = [int(row["latency_ms"]) for row in rows if row.get("latency_ms") is not None]
    routes: dict[str, int] = {}
    providers: dict[str, int] = {}
    route_tokens: dict[str, int] = {}
    provider_tokens: dict[str, int] = {}
    for row in rows:
        routes[row["model_route"]] = routes.get(row["model_route"], 0) + 1
        providers[row["provider_alias"]] = providers.get(row["provider_alias"], 0) + 1
        total = row.get("total_tokens")
        if total is not None:
            route_tokens[row["model_route"]] = route_tokens.get(row["model_route"], 0) + int(total)
            provider_tokens[row["provider_alias"]] = provider_tokens.get(row["provider_alias"], 0) + int(total)
    retry_rows = [row for row in rows if int(row.get("retry_index") or 0) > 0]
    fallback_rows = [row for row in rows if row.get("fallback_from")]
    compaction_rows = [row for row in rows if row.get("call_site") == "compaction"]
    return UsageSummary(
        calls=len(rows),
        input_tokens=_sum_nullable(rows, "input_tokens"),
        cached_input_tokens=cached,
        cache_miss_input_tokens=_sum_nullable(rows, "cache_miss_input_tokens"),
        output_tokens=_sum_nullable(rows, "output_tokens"),
        reasoning_tokens=_sum_nullable(rows, "reasoning_tokens"),
        total_tokens=_sum_nullable(rows, "total_tokens"),
        actual_cost_usd=_sum_nullable(rows, "actual_cost_usd"),
        estimated_cost_usd=_sum_nullable(rows, "estimated_cost_usd"),
        cache_hit_rate=cache_rate,
        cache_state=cache_state,
        p50_latency_ms=float(median(latencies)) if latencies else None,
        p95_latency_ms=_percentile(latencies, 0.95),
        by_model_route=routes,
        by_provider=providers,
        tokens_by_model_route=route_tokens,
        tokens_by_provider=provider_tokens,
        retry_tokens=_sum_nullable(retry_rows, "total_tokens"),
        fallback_tokens=_sum_nullable(fallback_rows, "total_tokens"),
        compaction_tokens=_sum_nullable(compaction_rows, "total_tokens"),
    )
