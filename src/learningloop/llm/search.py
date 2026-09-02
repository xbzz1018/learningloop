from __future__ import annotations

import asyncio
import time
import uuid
from datetime import UTC, datetime
from typing import Any

from ddgs import DDGS
from openai import AsyncOpenAI

from learningloop.config import Settings
from learningloop.db import Database
from learningloop.llm.context import current_call_context
from learningloop.models import ModelCallRecord, ModelRoute, UsageData
from learningloop.usage import add_estimated_cost, normalize_responses_usage


def _collect_urls(value: Any, found: list[dict[str, str]]) -> None:
    if isinstance(value, dict):
        url = value.get("url")
        if isinstance(url, str) and url.startswith(("http://", "https://")):
            item = {"url": url, "title": str(value.get("title") or url)}
            if item not in found:
                found.append(item)
        for child in value.values():
            _collect_urls(child, found)
    elif isinstance(value, list):
        for child in value:
            _collect_urls(child, found)


class SearchService:
    def __init__(self, settings: Settings, db: Database) -> None:
        self.settings = settings
        self.db = db

    async def search(self, query: str, max_results: int = 5) -> dict[str, Any]:
        errors: list[str] = []
        for retry_index, alias in enumerate(self._provider_order()):
            provider = self.settings.providers[alias]
            if provider.flash_key is None:
                continue
            try:
                return await self._responses_search(alias, query, max_results, retry_index)
            except Exception as exc:  # noqa: BLE001 - capability fallback
                errors.append(f"{alias}:{type(exc).__name__}")
        return await asyncio.to_thread(self._duckduckgo_search, query, max_results, errors)

    def _provider_order(self) -> tuple[str, ...]:
        configured = [
            alias for alias, provider in self.settings.providers.items()
            if provider.flash_key is not None
        ]
        if not configured:
            return ()
        rows = self.db.fetch_all(
            "SELECT provider_alias,web_search_ok FROM provider_capabilities "
            "WHERE model_route='flash'"
        )
        available = {row["provider_alias"] for row in rows if row["web_search_ok"]}
        checked = [alias for alias in configured if alias in available]
        unverified = [alias for alias in configured if alias not in available]
        # 官方优先；只有开启中转备用时才把中转站加入搜索链路。
        if "official" in configured:
            ordered = ["official"] + [alias for alias in checked + unverified if alias != "official"]
        else:
            ordered = checked + unverified
        if not self.settings.enable_relay_fallback and "official" in configured:
            return ("official",)
        return tuple(ordered)

    async def _responses_search(
        self, alias: str, query: str, max_results: int, retry_index: int
    ) -> dict[str, Any]:
        provider = self.settings.providers[alias]
        context = current_call_context.get()
        call_id = str(uuid.uuid4())
        started_at = datetime.now(UTC)
        started_clock = time.perf_counter()
        client = AsyncOpenAI(
            api_key=provider.flash_key.get_secret_value(),
            base_url=provider.base_url,
            timeout=self.settings.request_timeout_seconds,
        )
        try:
            response = await client.responses.create(
                model=provider.flash_model,
                input=(
                    "Search the web for reliable sources that answer this learning question. "
                    "Return a concise synthesis with citations. Query: " + query
                ),
                tools=[{"type": "web_search"}],
                max_output_tokens=2_000,
            )
            raw = response.model_dump()
            usage = add_estimated_cost(
                normalize_responses_usage(raw.get("usage")), "flash", started_at
            )
            sources: list[dict[str, str]] = []
            _collect_urls(raw.get("output"), sources)
            self._record(
                alias=alias,
                call_id=call_id,
                context=context,
                started_at=started_at,
                latency_ms=int((time.perf_counter() - started_clock) * 1000),
                retry_index=retry_index,
                status="success",
                usage=usage,
                actual_model=raw.get("model"),
            )
            return {
                "provider": f"{alias}_responses",
                "verified_online": True,
                "answer": response.output_text,
                "sources": sources[:max_results],
                "searched_at": started_at.isoformat(),
            }
        except Exception as exc:
            self._record(
                alias=alias,
                call_id=call_id,
                context=context,
                started_at=started_at,
                latency_ms=int((time.perf_counter() - started_clock) * 1000),
                retry_index=retry_index,
                status="failed",
                usage=UsageData(usage_unknown=True, usage_source="responses"),
                error_type=type(exc).__name__,
            )
            raise

    def _record(
        self,
        *,
        alias: str,
        call_id: str,
        context: Any,
        started_at: datetime,
        latency_ms: int,
        retry_index: int,
        status: str,
        usage: UsageData,
        actual_model: str | None = None,
        error_type: str | None = None,
    ) -> None:
        provider = self.settings.providers[alias]
        fallback_id = str(uuid.uuid4())
        self.db.add_model_call(
            ModelCallRecord(
                call_id=call_id,
                run_id=context.run_id if context else fallback_id,
                session_id=context.session_id if context else "system",
                turn_id=context.turn_id if context else fallback_id,
                task_type=context.task_type if context else "search",
                call_site="web_search",
                provider_alias=alias,
                requested_model=provider.flash_model,
                actual_model=actual_model,
                model_route=ModelRoute.FLASH,
                reasoning_effort="low",
                started_at=started_at,
                latency_ms=latency_ms,
                status=status,
                retry_index=retry_index,
                fallback_from="vibe" if alias == "kcne" else None,
                error_type=error_type,
                usage=usage,
            )
        )

    @staticmethod
    def _duckduckgo_search(
        query: str, max_results: int, upstream_errors: list[str]
    ) -> dict[str, Any]:
        results = list(DDGS().text(query, max_results=max_results))
        return {
            "provider": "duckduckgo",
            "verified_online": True,
            "answer": "",
            "sources": [
                {
                    "title": str(item.get("title") or item.get("href") or "Source"),
                    "url": str(item.get("href") or ""),
                    "snippet": str(item.get("body") or ""),
                }
                for item in results
                if item.get("href")
            ],
            "searched_at": datetime.now(UTC).isoformat(),
            "upstream_errors": upstream_errors,
        }
