from __future__ import annotations

from datetime import UTC, datetime

from learningloop.usage import (
    PRICING_VERSION,
    add_estimated_cost,
    aggregate_usage,
    normalize_chat_usage,
    normalize_responses_usage,
)


def test_missing_usage_stays_null() -> None:
    usage = normalize_chat_usage(None)
    assert usage.input_tokens is None
    assert usage.output_tokens is None
    assert usage.total_tokens is None
    assert usage.usage_unknown is True


def test_chat_usage_derives_cache_miss_and_total() -> None:
    usage = normalize_chat_usage({"tokens_in": 100, "tokens_out": 20, "cached_input_tokens": 30})
    assert usage.cache_miss_input_tokens == 70
    assert usage.total_tokens == 120


def test_responses_usage_maps_reasoning_tokens() -> None:
    usage = normalize_responses_usage(
        {
            "input_tokens": 200,
            "output_tokens": 50,
            "input_tokens_details": {"cached_tokens": 100},
            "output_tokens_details": {"reasoning_tokens": 25},
        }
    )
    assert usage.cache_miss_input_tokens == 100
    assert usage.reasoning_tokens == 25


def test_chat_usage_preserves_reasoning_tokens() -> None:
    usage = normalize_chat_usage({"tokens_in": 100, "tokens_out": 30, "reasoning_tokens": 20})
    assert usage.reasoning_tokens == 20


def test_estimated_cost_is_versioned() -> None:
    usage = normalize_chat_usage({"tokens_in": 1_000_000, "tokens_out": 100_000})
    priced = add_estimated_cost(usage, "flash", datetime(2026, 8, 31, 12, tzinfo=UTC))
    assert priced.pricing_version == PRICING_VERSION
    assert priced.estimated_cost_usd == 0.286


def test_aggregate_preserves_null_and_breakdowns() -> None:
    rows = [
        {
            "model_route": "flash",
            "provider_alias": "vibe",
            "input_tokens": 100,
            "cached_input_tokens": 20,
            "cache_miss_input_tokens": 80,
            "output_tokens": 10,
            "reasoning_tokens": None,
            "total_tokens": 110,
            "actual_cost_usd": None,
            "estimated_cost_usd": 0.1,
            "latency_ms": 100,
            "retry_index": 0,
            "fallback_from": None,
            "call_site": "agent",
        },
        {
            "model_route": "flash",
            "provider_alias": "kcne",
            "input_tokens": 200,
            "cached_input_tokens": 0,
            "cache_miss_input_tokens": 200,
            "output_tokens": 20,
            "reasoning_tokens": 5,
            "total_tokens": 220,
            "actual_cost_usd": None,
            "estimated_cost_usd": 0.2,
            "latency_ms": 300,
            "retry_index": 1,
            "fallback_from": "vibe",
            "call_site": "agent",
        },
    ]
    summary = aggregate_usage(rows)
    assert summary.calls == 2
    assert summary.total_tokens == 330
    assert summary.actual_cost_usd is None
    assert summary.estimated_cost_usd == 0.30000000000000004
    assert summary.by_provider == {"vibe": 1, "kcne": 1}
    assert summary.tokens_by_model_route == {"flash": 330}
    assert summary.tokens_by_provider == {"vibe": 110, "kcne": 220}
    assert summary.fallback_tokens == 220
