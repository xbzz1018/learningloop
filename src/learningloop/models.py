from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(UTC)


class SessionStatus(StrEnum):
    IDLE = "idle"
    RUNNING = "running"
    AWAITING_APPROVAL = "awaiting_approval"
    COMPLETED = "completed"
    FAILED = "failed"
    RECOVERING = "recovering"
    CANCELLED = "cancelled"


class RunStage(StrEnum):
    RECEIVED = "received"
    CONTEXT_READY = "context_ready"
    MODEL_COMPLETED = "model_completed"
    EFFECT_APPLIED = "effect_applied"
    AWAITING_ACTION = "awaiting_action"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class ActionType(StrEnum):
    PLAN_APPROVAL = "plan_approval"
    PLAN_REVISION = "plan_revision"
    HIGH_RISK_WRITE = "high_risk_write"
    EMAIL_ACTIVATION = "email_activation"
    WORKFLOW_CHECKPOINT = "workflow_checkpoint"


class ActionStatus(StrEnum):
    PENDING = "pending"
    EXECUTING = "executing"
    COMPLETED = "completed"
    REJECTED = "rejected"
    CANCELLED = "cancelled"
    FAILED = "failed"


class ActionDecision(StrEnum):
    EXECUTE = "execute"
    NEXT = "next"
    SUGGEST = "suggest"
    REJECT = "reject"
    CANCEL = "cancel"


class ModelRoute(StrEnum):
    FLASH = "flash"
    PRO = "pro"


class AgentRole(StrEnum):
    """运行入口角色：实时交互与后台主动任务共享同一 Harness。"""

    INTERACTIVE = "interactive"
    AUTONOMOUS = "autonomous"


class CallContext(BaseModel):
    run_id: str
    session_id: str
    turn_id: str
    owner_id: str = "local"
    agent_role: AgentRole = AgentRole.INTERACTIVE
    task_type: str = "chat"
    call_site: str = "agent"
    source_message_id: int | None = None


class UsageData(BaseModel):
    input_tokens: int | None = None
    cached_input_tokens: int | None = None
    cache_miss_input_tokens: int | None = None
    output_tokens: int | None = None
    reasoning_tokens: int | None = None
    total_tokens: int | None = None
    actual_cost_usd: float | None = None
    estimated_cost_usd: float | None = None
    pricing_version: str | None = None
    usage_source: str | None = None
    usage_unknown: bool = False


class ModelCallRecord(BaseModel):
    call_id: str
    run_id: str
    session_id: str
    owner_id: str = "local"
    agent_role: AgentRole = AgentRole.INTERACTIVE
    turn_id: str
    task_type: str
    call_site: str
    provider_alias: str
    requested_model: str
    actual_model: str | None = None
    model_route: ModelRoute
    reasoning_effort: str | None = None
    started_at: datetime
    latency_ms: int | None = None
    status: Literal["success", "failed", "stream_interrupted"]
    retry_index: int = 0
    fallback_from: str | None = None
    error_type: str | None = None
    usage: UsageData = Field(default_factory=UsageData)


class EventRecord(BaseModel):
    id: int | None = None
    session_id: str
    run_id: str
    type: str
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)


class RunRecord(BaseModel):
    id: str
    session_id: str
    owner_id: str = "local"
    agent_role: AgentRole = AgentRole.INTERACTIVE
    parent_run_id: str | None = None
    turn_id: str
    stage: RunStage = RunStage.RECEIVED
    status: str = SessionStatus.RUNNING.value
    skill_name: str | None = None
    skill_hash: str | None = None
    route: ModelRoute | None = None
    error_type: str | None = None
    error_message: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class AgentArtifact(BaseModel):
    """跨运行入口交接的结构化产物，不承载完整聊天文本。"""

    id: str
    run_id: str
    session_id: str
    owner_id: str = "local"
    artifact_type: str
    schema_version: str = "1"
    payload: dict[str, Any] = Field(default_factory=dict)
    source: AgentRole
    created_at: datetime = Field(default_factory=utc_now)


class ApprovalRecord(BaseModel):
    id: str
    session_id: str
    run_id: str
    tool: str
    args: dict[str, Any]
    status: ApprovalStatus = ApprovalStatus.PENDING
    message: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    decided_at: datetime | None = None


class ActionRequest(BaseModel):
    id: str
    session_id: str
    run_id: str
    action_type: ActionType
    title: str
    description: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)
    available_decisions: list[ActionDecision] = Field(default_factory=list)
    status: ActionStatus = ActionStatus.PENDING
    decision_message: str | None = None
    parent_action_id: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    decided_at: datetime | None = None


class TaskMetadata(BaseModel):
    operation: str = "chat"
    deep_mode: bool = False
    duration_days: int | None = None
    domain_count: int = 1
    affected_fraction: float = 0.0
    validation_failures: int = 0


class UsageSummary(BaseModel):
    calls: int = 0
    input_tokens: int | None = None
    cached_input_tokens: int | None = None
    cache_miss_input_tokens: int | None = None
    output_tokens: int | None = None
    reasoning_tokens: int | None = None
    total_tokens: int | None = None
    actual_cost_usd: float | None = None
    estimated_cost_usd: float | None = None
    cache_hit_rate: float | None = None
    cache_state: Literal["no_data", "reported_zero", "reported", "unknown"] = "no_data"
    p50_latency_ms: float | None = None
    p95_latency_ms: float | None = None
    by_model_route: dict[str, int] = Field(default_factory=dict)
    by_provider: dict[str, int] = Field(default_factory=dict)
    tokens_by_model_route: dict[str, int] = Field(default_factory=dict)
    tokens_by_provider: dict[str, int] = Field(default_factory=dict)
    retry_tokens: int | None = None
    fallback_tokens: int | None = None
    compaction_tokens: int | None = None
