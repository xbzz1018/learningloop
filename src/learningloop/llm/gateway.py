from __future__ import annotations

import time
import uuid
from collections import deque
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta
from typing import Any

from harness.llm.fallback import FallbackLLM
from harness.llm.openai import OpenAILLM
from harness.llm.routing import RoutingLLM

from learningloop.config import Settings
from learningloop.db import Database
from learningloop.llm.context import call_context, current_call_context, current_model_route
from learningloop.models import (
    CallContext,
    ModelCallRecord,
    ModelRoute,
    TaskMetadata,
    UsageData,
)
from learningloop.observability import Telemetry
from learningloop.usage import add_estimated_cost, normalize_chat_usage


class BudgetExceeded(RuntimeError):
    pass


class CircuitOpenTimeoutError(TimeoutError):
    pass


class DetailedOpenAILLM(OpenAILLM):
    def _build_usage(self, resp: Any, headers: dict[str, str] | None) -> dict:
        usage = super()._build_usage(resp, headers)
        usage_obj = getattr(resp, "usage", None)
        if usage_obj is None:
            return usage
        prompt_details = getattr(usage_obj, "prompt_tokens_details", None)
        completion_details = getattr(usage_obj, "completion_tokens_details", None)
        cached = getattr(prompt_details, "cached_tokens", None)
        if cached is None:
            cached = getattr(usage_obj, "prompt_cache_hit_tokens", None)
        miss = getattr(usage_obj, "prompt_cache_miss_tokens", None)
        reasoning = getattr(completion_details, "reasoning_tokens", None)
        if cached is not None:
            usage["cached_input_tokens"] = int(cached)
        if miss is not None:
            usage["prompt_cache_miss_tokens"] = int(miss)
        if reasoning is not None:
            usage["reasoning_tokens"] = int(reasoning)
        return usage


def _is_transient(exc: BaseException) -> bool:
    if isinstance(exc, TimeoutError | ConnectionError | OSError):
        return True
    return getattr(exc, "status_code", None) in {408, 425, 429, 500, 502, 503, 504}


class CircuitBreakerLLM:
    def __init__(self, inner: Any, *, threshold: int = 3) -> None:
        self.inner = inner
        self.threshold = threshold
        self.failures: deque[datetime] = deque()
        self.opened_until: datetime | None = None
        self.last_usage: dict[str, Any] | None = None

    @property
    def context_window(self) -> int:
        return int(self.inner.context_window)

    @property
    def input_token_budget(self) -> int:
        return int(self.inner.input_token_budget)

    def set_budget(self, guard: Any) -> None:
        self.inner.set_budget(guard)

    def _before(self) -> None:
        now = datetime.now(UTC)
        if self.opened_until and now < self.opened_until:
            raise CircuitOpenTimeoutError("provider circuit is open")
        if self.opened_until and now >= self.opened_until:
            self.opened_until = None

    def _success(self) -> None:
        self.failures.clear()
        self.opened_until = None
        self.last_usage = getattr(self.inner, "last_usage", None)

    def _failure(self, exc: BaseException) -> None:
        if not _is_transient(exc):
            return
        now = datetime.now(UTC)
        cutoff = now - timedelta(seconds=60)
        while self.failures and self.failures[0] < cutoff:
            self.failures.popleft()
        self.failures.append(now)
        if len(self.failures) >= self.threshold:
            self.opened_until = now + timedelta(minutes=5)

    async def complete(self, *args: Any, **kwargs: Any) -> dict:
        self._before()
        try:
            result = await self.inner.complete(*args, **kwargs)
        except BaseException as exc:
            self._failure(exc)
            raise
        self._success()
        return result

    async def stream_complete(self, *args: Any, **kwargs: Any) -> AsyncGenerator[str, None]:
        self._before()
        try:
            async for chunk in self.inner.stream_complete(*args, **kwargs):
                yield chunk
        except BaseException as exc:
            self._failure(exc)
            raise
        self._success()


class BudgetGate:
    def __init__(self, db: Database, settings: Settings) -> None:
        self.db = db
        self.settings = settings

    def check(self, context: CallContext) -> None:
        day = datetime.now(UTC).date().isoformat()
        daily = self.db.usage_rows(day=day)
        session = self.db.usage_rows(session_id=context.session_id)
        turn = [row for row in session if row["turn_id"] == context.turn_id]
        all_rows = self.db.usage_rows()
        known_cost = sum(
            float(
                row["actual_cost_usd"]
                if row.get("actual_cost_usd") is not None
                else row.get("estimated_cost_usd") or 0
            )
            for row in all_rows
        )
        if known_cost >= self.settings.development_cost_limit_usd:
            raise BudgetExceeded("development cost limit reached")
        self._check_rows(
            turn,
            self.settings.turn_call_limit,
            self.settings.turn_input_limit,
            self.settings.turn_output_limit,
            "turn",
        )
        self._check_rows(
            daily,
            self.settings.daily_call_limit,
            self.settings.daily_input_limit,
            self.settings.daily_output_limit,
            "day",
        )

    @staticmethod
    def _check_rows(
        rows: list[dict[str, Any]], call_limit: int, input_limit: int, output_limit: int, scope: str
    ) -> None:
        calls = len(rows)
        inputs = sum(row["input_tokens"] or 0 for row in rows)
        outputs = sum(row["output_tokens"] or 0 for row in rows)
        if calls >= call_limit:
            raise BudgetExceeded(f"{scope} model-call limit reached")
        if inputs >= input_limit:
            raise BudgetExceeded(f"{scope} input-token limit reached")
        if outputs >= output_limit:
            raise BudgetExceeded(f"{scope} output-token limit reached")


class AuditedLLM:
    def __init__(
        self,
        *,
        inner: Any,
        db: Database,
        settings: Settings,
        provider_alias: str,
        model_route: ModelRoute,
        requested_model: str,
        retry_index: int,
        fallback_from: str | None,
        telemetry: Telemetry,
    ) -> None:
        self.inner = inner
        self.db = db
        self.provider_alias = provider_alias
        self.model_route = model_route
        self.requested_model = requested_model
        self.retry_index = retry_index
        self.fallback_from = fallback_from
        self.telemetry = telemetry
        self.budget_gate = BudgetGate(db, settings)
        self.last_usage: dict[str, Any] | None = None

    @property
    def context_window(self) -> int:
        return int(self.inner.context_window)

    @property
    def input_token_budget(self) -> int:
        return int(self.inner.input_token_budget)

    def set_budget(self, guard: Any) -> None:
        self.inner.set_budget(guard)

    def _context(self, source: str | None) -> CallContext:
        context = current_call_context.get()
        if context is not None:
            return context.model_copy(update={"call_site": source or context.call_site})
        fallback_id = str(uuid.uuid4())
        return CallContext(
            run_id=fallback_id,
            session_id="system",
            turn_id=fallback_id,
            task_type="system",
            call_site=source or "system",
        )

    def _record(
        self,
        *,
        context: CallContext,
        call_id: str,
        started_at: datetime,
        started_clock: float,
        status: str,
        usage: UsageData,
        reasoning_effort: str | None,
        error_type: str | None = None,
    ) -> None:
        priced = add_estimated_cost(usage, self.model_route.value, started_at)
        self.db.add_model_call(
            ModelCallRecord(
                call_id=call_id,
                run_id=context.run_id,
                session_id=context.session_id,
                owner_id=context.owner_id,
                agent_role=context.agent_role,
                turn_id=context.turn_id,
                task_type=context.task_type,
                call_site=context.call_site,
                provider_alias=self.provider_alias,
                requested_model=self.requested_model,
                actual_model=(self.last_usage or {}).get("model"),
                model_route=self.model_route,
                reasoning_effort=reasoning_effort,
                started_at=started_at,
                latency_ms=int((time.perf_counter() - started_clock) * 1000),
                status=status,
                retry_index=self.retry_index,
                fallback_from=self.fallback_from,
                error_type=error_type,
                usage=priced,
            )
        )

    async def complete(
        self, system: str | None, messages: list[dict], *, source: str | None = None, **kwargs: Any
    ) -> dict:
        context = self._context(source)
        self.budget_gate.check(context)
        call_id = str(uuid.uuid4())
        started_at = datetime.now(UTC)
        started_clock = time.perf_counter()
        attributes = {
            "gen_ai.operation.name": "invoke_agent",
            "gen_ai.request.model": self.requested_model,
            "gen_ai.provider.name": self.provider_alias,
            "learningloop.run_id": context.run_id,
            "learningloop.session_id": context.session_id,
            "learningloop.call_site": context.call_site,
            "learningloop.agent_role": context.agent_role.value,
        }
        with self.telemetry.span("learningloop.model", attributes):
            try:
                result = await self.inner.complete(system, messages, source=source, **kwargs)
            except BaseException as exc:
                self.last_usage = getattr(self.inner, "last_usage", None)
                usage = normalize_chat_usage(self.last_usage)
                self._record(
                    context=context,
                    call_id=call_id,
                    started_at=started_at,
                    started_clock=started_clock,
                    status="failed",
                    usage=usage,
                    reasoning_effort=kwargs.get("reasoning_effort"),
                    error_type=type(exc).__name__,
                )
                raise
        self.last_usage = getattr(self.inner, "last_usage", None)
        usage = normalize_chat_usage(self.last_usage)
        self._record(
            context=context,
            call_id=call_id,
            started_at=started_at,
            started_clock=started_clock,
            status="success",
            usage=usage,
            reasoning_effort=kwargs.get("reasoning_effort"),
        )
        return result

    async def stream_complete(
        self,
        system: str | None,
        messages: list[dict],
        *,
        source: str | None = None,
        **kwargs: Any,
    ) -> AsyncGenerator[str, None]:
        context = self._context(source)
        self.budget_gate.check(context)
        call_id = str(uuid.uuid4())
        started_at = datetime.now(UTC)
        started_clock = time.perf_counter()
        emitted = False
        attributes = {
            "gen_ai.operation.name": "invoke_agent",
            "gen_ai.request.model": self.requested_model,
            "gen_ai.provider.name": self.provider_alias,
            "learningloop.run_id": context.run_id,
            "learningloop.session_id": context.session_id,
            "learningloop.call_site": context.call_site,
            "learningloop.agent_role": context.agent_role.value,
        }
        with self.telemetry.span("learningloop.model", attributes):
            try:
                async for chunk in self.inner.stream_complete(
                    system, messages, source=source, **kwargs
                ):
                    emitted = True
                    yield chunk
            except BaseException as exc:
                self.last_usage = getattr(self.inner, "last_usage", None)
                self._record(
                    context=context,
                    call_id=call_id,
                    started_at=started_at,
                    started_clock=started_clock,
                    status="stream_interrupted" if emitted else "failed",
                    usage=normalize_chat_usage(self.last_usage),
                    reasoning_effort=kwargs.get("reasoning_effort"),
                    error_type=type(exc).__name__,
                )
                raise
        self.last_usage = getattr(self.inner, "last_usage", None)
        self._record(
            context=context,
            call_id=call_id,
            started_at=started_at,
            started_clock=started_clock,
            status="success",
            usage=normalize_chat_usage(self.last_usage),
            reasoning_effort=kwargs.get("reasoning_effort"),
        )


class ModelPolicy:
    PRO_OPERATIONS = {"deep_plan", "major_recovery", "complex_review"}

    def choose(self, metadata: TaskMetadata) -> ModelRoute:
        if metadata.deep_mode:
            return ModelRoute.PRO
        if metadata.operation in self.PRO_OPERATIONS:
            return ModelRoute.PRO
        if (metadata.duration_days or 0) > 60 or metadata.domain_count >= 3:
            return ModelRoute.PRO
        if metadata.affected_fraction > 0.30 or metadata.validation_failures >= 2:
            return ModelRoute.PRO
        return ModelRoute.FLASH


class ModelGateway:
    def __init__(self, settings: Settings, db: Database) -> None:
        self.settings = settings
        self.db = db
        self.policy = ModelPolicy()
        self.telemetry = Telemetry(settings)
        self.adapters: dict[str, AuditedLLM] = {}
        self.llm = self._build_router()

    def _build_adapter(
        self, provider_alias: str, route: ModelRoute, retry_index: int
    ) -> AuditedLLM:
        provider = self.settings.providers[provider_alias]
        key = provider.flash_key if route == ModelRoute.FLASH else provider.pro_key
        model = provider.flash_model if route == ModelRoute.FLASH else provider.pro_model
        if key is None:
            raise ValueError(f"Missing key for {provider_alias}_{route.value}")
        effort = "low" if route == ModelRoute.FLASH else "high"
        inner = DetailedOpenAILLM(
            model=model,
            api_key=key.get_secret_value(),
            base_url=provider.base_url,
            request_timeout_seconds=self.settings.request_timeout_seconds,
            max_completion_tokens=8_192 if route == ModelRoute.PRO else 4_096,
            reasoning_effort=effort,
            context_window=128_000,
        )
        audited = AuditedLLM(
            inner=inner,
            db=self.db,
            settings=self.settings,
            provider_alias=provider_alias,
            model_route=route,
            requested_model=model,
            retry_index=retry_index,
            fallback_from=None,
            telemetry=self.telemetry,
        )
        self.adapters[f"{provider_alias}_{route.value}"] = audited
        return audited

    def _candidate_aliases(self, route: ModelRoute) -> list[str]:
        """按生产策略生成候选：官方优先，中转站只在显式开启或官方缺失时参与。"""
        configured = []
        for alias in ("official", "vibe", "kcne"):
            provider = self.settings.providers[alias]
            key = provider.flash_key if route == ModelRoute.FLASH else provider.pro_key
            if key is not None:
                configured.append(alias)
        if "official" in configured and not self.settings.enable_relay_fallback:
            return ["official"]
        return configured

    def _build_router(self) -> RoutingLLM:
        routes = {}
        for route in (ModelRoute.FLASH, ModelRoute.PRO):
            aliases = self._candidate_aliases(route)
            if not aliases:
                raise ValueError(f"Missing configured model key for {route.value}")
            wrapped = []
            for index, alias in enumerate(aliases):
                adapter = self._build_adapter(alias, route, index)
                adapter.fallback_from = aliases[index - 1] if index else None
                wrapped.append(CircuitBreakerLLM(adapter))
            routes[route.value] = wrapped[0] if len(wrapped) == 1 else FallbackLLM(wrapped)
        return RoutingLLM(
            routes=routes,
            selector=lambda _system, _messages: current_model_route.get().value,
            default_route=ModelRoute.FLASH.value,
        )

    def route_for(self, metadata: TaskMetadata) -> ModelRoute:
        return self.policy.choose(metadata)


__all__ = ["BudgetExceeded", "ModelGateway", "ModelPolicy", "call_context"]
