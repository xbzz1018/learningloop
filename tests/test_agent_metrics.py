from learningloop.metrics import context_metrics, usage_metrics


def test_context_metric_is_explicitly_estimated(settings, db) -> None:
    session = db.create_session("metric-session")
    for index in range(12):
        db.add_message(session["id"], "user" if index % 2 == 0 else "assistant", "学习内容 " * 20)
    metrics = context_metrics(settings, db, session["id"])
    assert metrics["full_context_tokens"] > 0
    assert metrics["bounded_context_tokens"] > 0
    assert 0 <= metrics["context_reduction"] <= 1


def test_usage_metric_does_not_invent_cost_or_baseline() -> None:
    report = usage_metrics(
        [
            {"agent_role": "interactive", "model_route": "flash", "estimated_cost_usd": None},
            {"agent_role": "autonomous", "model_route": "flash", "estimated_cost_usd": None},
        ]
    )
    assert report["flash_call_share"] == 1.0
    assert report["estimated_cost_usd"] is None
    assert report["cost_comparison_vs_pro_only"] is None
