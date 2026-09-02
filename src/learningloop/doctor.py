from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

from openai import AsyncOpenAI

from learningloop.config import Settings
from learningloop.db import Database
from learningloop.llm import ModelGateway, call_context
from learningloop.llm.search import SearchService
from learningloop.models import CallContext, ModelRoute


class CapabilityDoctor:
    def __init__(self, settings: Settings, db: Database) -> None:
        self.settings = settings
        self.db = db
        self.gateway = ModelGateway(settings, db)
        self.search = SearchService(settings, db)

    def configured(self) -> dict[str, Any]:
        return {
            f"{alias}_{route}": {
                "configured": bool(provider.flash_key if route == "flash" else provider.pro_key),
                "base_url": provider.base_url,
                "model": provider.flash_model if route == "flash" else provider.pro_model,
            }
            for alias, provider in self.settings.providers.items()
            for route in ("flash", "pro")
        }

    async def run_live(self) -> dict[str, Any]:
        results: dict[str, Any] = {}
        for alias, provider in self.settings.providers.items():
            for route in (ModelRoute.FLASH, ModelRoute.PRO):
                key = provider.flash_key if route == ModelRoute.FLASH else provider.pro_key
                model = provider.flash_model if route == ModelRoute.FLASH else provider.pro_model
                result = {
                    "models_ok": False,
                    "chat_ok": False,
                    "structured_ok": False,
                    "streaming_ok": False,
                    "usage_ok": False,
                    "responses_ok": False,
                    "web_search_ok": False,
                    "actual_model": None,
                    "error": None,
                }
                if key is None:
                    result["error"] = "missing_key"
                    results[f"{alias}_{route.value}"] = result
                    continue
                client = AsyncOpenAI(
                    api_key=key.get_secret_value(),
                    base_url=provider.base_url,
                    timeout=self.settings.request_timeout_seconds,
                )
                try:
                    models = await client.models.list()
                    result["models_ok"] = any(item.id == model for item in models.data)
                    context_id = str(uuid.uuid4())
                    context = CallContext(
                        run_id=context_id,
                        session_id="doctor",
                        turn_id=context_id,
                        task_type="compatibility",
                        call_site="doctor",
                    )
                    with call_context(context, route):
                        response = await self.gateway.adapters[f"{alias}_{route.value}"].complete(
                            system="Return JSON only.",
                            messages=[{"role": "user", "content": 'Return {"ok": true}.'}],
                            response_format={"type": "json_object"},
                            reasoning_effort="low" if route == ModelRoute.FLASH else "high",
                        )
                    parsed = json.loads(response["text"])
                    result["chat_ok"] = bool(parsed.get("ok"))
                    result["structured_ok"] = result["chat_ok"]
                    usage = self.gateway.adapters[f"{alias}_{route.value}"].last_usage or {}
                    result["usage_ok"] = bool(usage.get("tokens_in") is not None)
                    result["actual_model"] = usage.get("model")
                    chunks: list[str] = []
                    with call_context(context, route):
                        async for chunk in self.gateway.adapters[
                            f"{alias}_{route.value}"
                        ].stream_complete(
                            system="Answer briefly.",
                            messages=[{"role": "user", "content": "Reply OK."}],
                            reasoning_effort="low" if route == ModelRoute.FLASH else "high",
                        ):
                            chunks.append(chunk)
                    result["streaming_ok"] = bool("".join(chunks).strip())
                    if route == ModelRoute.FLASH:
                        try:
                            search_response = await self.search._responses_search(
                                alias,
                                "Search for the official Python website.",
                                3,
                                0,
                            )
                            result["responses_ok"] = True
                            result["web_search_ok"] = bool(search_response["sources"])
                        except Exception as search_exc:  # noqa: BLE001
                            result["error"] = f"web_search:{type(search_exc).__name__}"
                except Exception as exc:  # noqa: BLE001
                    result["error"] = type(exc).__name__
                results[f"{alias}_{route.value}"] = result
                self._save(alias, route.value, result)
        return results

    def _save(self, alias: str, route: str, result: dict[str, Any]) -> None:
        self.db.execute(
            "INSERT OR REPLACE INTO provider_capabilities("
            "provider_alias,model_route,models_ok,chat_ok,tools_ok,structured_ok,"
            "streaming_ok,usage_ok,responses_ok,web_search_ok,actual_model,error,checked_at"
            ") VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                alias,
                route,
                int(result["models_ok"]),
                int(result["chat_ok"]),
                int(result["chat_ok"] and result["structured_ok"]),
                int(result["structured_ok"]),
                int(result["streaming_ok"]),
                int(result["usage_ok"]),
                int(result["responses_ok"]),
                int(result["web_search_ok"]),
                result["actual_model"],
                result["error"],
                datetime.now(UTC).isoformat(),
            ),
        )
