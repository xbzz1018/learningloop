import pytest

from learningloop.agent.policy import AgentPolicy
from learningloop.llm.gateway import (
    BudgetExceeded,
    BudgetGate,
    CircuitBreakerLLM,
    CircuitOpenTimeoutError,
    ModelPolicy,
)
from learningloop.models import AgentRole, CallContext, ModelRoute, TaskMetadata


def test_flash_is_default() -> None:
    assert ModelPolicy().choose(TaskMetadata()) == ModelRoute.FLASH


def test_agent_profiles_keep_roles_distinct() -> None:
    interactive = AgentPolicy.profile_for(AgentRole.INTERACTIVE)
    autonomous = AgentPolicy.profile_for(AgentRole.AUTONOMOUS)
    assert interactive.context_message_limit == 8
    assert autonomous.context_message_limit == 0
    assert "goal-anchoring" in interactive.allowed_skills
    assert "goal-anchoring" not in autonomous.allowed_skills


def test_pro_rules() -> None:
    policy = ModelPolicy()
    assert policy.choose(TaskMetadata(deep_mode=True)) == ModelRoute.PRO
    assert policy.choose(TaskMetadata(duration_days=61)) == ModelRoute.PRO
    assert policy.choose(TaskMetadata(domain_count=3)) == ModelRoute.PRO
    assert policy.choose(TaskMetadata(affected_fraction=0.31)) == ModelRoute.PRO
    assert policy.choose(TaskMetadata(validation_failures=2)) == ModelRoute.PRO


def test_rule_boundary_remains_flash() -> None:
    metadata = TaskMetadata(duration_days=60, domain_count=2, affected_fraction=0.30)
    assert ModelPolicy().choose(metadata) == ModelRoute.FLASH


class FailingLLM:
    async def complete(self, *args, **kwargs):
        raise TimeoutError("upstream timeout")


async def test_circuit_opens_after_three_transient_failures() -> None:
    circuit = CircuitBreakerLLM(FailingLLM())
    for _ in range(3):
        with pytest.raises(TimeoutError):
            await circuit.complete(None, [])
    with pytest.raises(CircuitOpenTimeoutError):
        await circuit.complete(None, [])


def test_development_cost_limit_is_enforced(settings, db) -> None:
    db.execute(
        "INSERT INTO model_calls(call_id,run_id,session_id,turn_id,task_type,call_site,"
        "provider_alias,requested_model,model_route,started_at,status,retry_index,"
        "estimated_cost_usd) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            "call",
            "run",
            "session",
            "turn",
            "test",
            "test",
            "vibe",
            "flash",
            "flash",
            "2026-09-01T00:00:00+00:00",
            "success",
            0,
            settings.development_cost_limit_usd,
        ),
    )
    with pytest.raises(BudgetExceeded):
        BudgetGate(db, settings).check(
            CallContext(run_id="next", session_id="other", turn_id="other")
        )
