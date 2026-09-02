from __future__ import annotations

import json
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from learningloop.db import Database
from learningloop.models import EventRecord


class RuntimeHooks:
    """Persist the runtime event vocabulary to SQLite and a redacted JSONL trace."""

    def __init__(self, db: Database, trace_dir: Path) -> None:
        self.db = db
        self.trace_dir = trace_dir
        self.trace_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def emit(
        self,
        session_id: str,
        run_id: str,
        event_type: str,
        payload: dict[str, Any] | None = None,
    ) -> int:
        safe_payload = self._redact(payload or {})
        created_at = datetime.now(UTC)
        event_id = self.db.add_event(
            EventRecord(
                session_id=session_id,
                run_id=run_id,
                type=event_type,
                payload=safe_payload,
                created_at=created_at,
            )
        )
        record = {
            "event_id": event_id,
            "session_id": session_id,
            "run_id": run_id,
            "type": event_type,
            "payload": self._redact_trace(payload or {}),
            "created_at": created_at.isoformat(),
        }
        path = self.trace_dir / f"{run_id}.jsonl"
        with self._lock, path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        return event_id

    @classmethod
    def _redact(cls, value: Any) -> Any:
        if isinstance(value, dict):
            result = {}
            for key, item in value.items():
                lowered = str(key).lower()
                if any(secret in lowered for secret in ("api_key", "password", "authorization")):
                    result[key] = "[redacted]"
                elif lowered in {"content", "prompt", "messages"}:
                    result[key] = "[content omitted]"
                else:
                    result[key] = cls._redact(item)
            return result
        if isinstance(value, list):
            return [cls._redact(item) for item in value]
        return value

    @classmethod
    def _redact_trace(cls, value: Any) -> Any:
        if isinstance(value, dict):
            result = {}
            for key, item in value.items():
                lowered = str(key).lower()
                if any(secret in lowered for secret in ("api_key", "password", "authorization")):
                    result[key] = "[redacted]"
                elif lowered in {"answer", "query", "text", "task", "request", "observation"}:
                    result[key] = "[content omitted]"
                else:
                    result[key] = cls._redact_trace(item)
            return result
        if isinstance(value, list):
            return [cls._redact_trace(item) for item in value]
        return value
