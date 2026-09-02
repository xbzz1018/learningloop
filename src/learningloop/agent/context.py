from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from learningloop.config import Settings
from learningloop.db import Database
from learningloop.learning.state import LearningWorkspace


@dataclass(frozen=True)
class ContextBundle:
    snapshot: dict[str, Any]
    recent_messages: list[dict[str, Any]]
    summary: str
    sources: list[dict[str, str]]

    def render(self, user_text: str) -> str:
        payload = {
            "request": user_text,
            "learning_state": self.snapshot,
            "recent_messages": self.recent_messages,
            "older_summary": self.summary or None,
            "context_sources": self.sources,
        }
        return json.dumps(payload, ensure_ascii=False, default=str)


class ContextBuilder:
    """Build a bounded, source-labelled context without creating a second fact store."""

    def __init__(self, settings: Settings, db: Database) -> None:
        self.settings = settings
        self.db = db

    def build(self, session_id: str) -> ContextBundle:
        workspace = LearningWorkspace(self.settings.workspace_dir, session_id)
        snapshot = workspace.snapshot()
        concepts = list(snapshot.get("concepts", {}).items())
        concepts.sort(key=lambda item: str(item[1].get("updated_at") or ""), reverse=True)
        snapshot["concepts"] = dict(concepts[: self.settings.context_concept_limit])
        recent = self.db.recent_messages(session_id, self.settings.max_recent_messages)
        session = self.db.get_session(session_id) or {}
        summary = str(session.get("summary") or "")
        summary = summary[: self.settings.context_summary_char_limit]
        sources = [
            {"type": "workspace", "id": session_id, "schema_version": "1"},
            {"type": "messages", "id": session_id, "schema_version": "1"},
        ]
        if summary:
            sources.append({"type": "summary", "id": session_id, "schema_version": "1"})
        return ContextBundle(snapshot, recent, summary, sources)
