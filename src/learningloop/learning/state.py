from __future__ import annotations

import json
import os
import tempfile
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel

from learningloop.learning.schemas import (
    ConceptState,
    CoursePlan,
    ErrorRecord,
    LearnerProfile,
    MemoryCandidate,
    ReviewState,
)

T = TypeVar("T", bound=BaseModel)


class LearningWorkspace:
    FILES = {
        "learner": "learner.json",
        "course": "course.json",
        "concepts": "concepts.json",
        "errors": "errors.json",
        "reviews": "reviews.json",
    }

    def __init__(self, root: Path, session_id: str) -> None:
        if not session_id or any(
            char not in "abcdefghijklmnopqrstuvwxyz0123456789-" for char in session_id
        ):
            raise ValueError("session_id must be a lowercase slug")
        self.base_root = root.resolve()
        self.root = (self.base_root / session_id).resolve()
        if self.base_root not in self.root.parents:
            raise ValueError("workspace path escapes configured root")
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._initialize()

    def _initialize(self) -> None:
        defaults: dict[str, Any] = {
            "learner": LearnerProfile().model_dump(mode="json"),
            "course": CoursePlan().model_dump(mode="json"),
            "concepts": {},
            "errors": [],
            "reviews": {},
        }
        for key, value in defaults.items():
            path = self._path(key)
            if not path.exists():
                self._atomic_write(path, value)

    def _path(self, key: str) -> Path:
        if key not in self.FILES:
            raise KeyError(f"unknown workspace key: {key}")
        path = (self.root / self.FILES[key]).resolve()
        if path.parent != self.root:
            raise ValueError("workspace path escape detected")
        return path

    def _read(self, key: str) -> Any:
        with self._lock:
            with self._path(key).open("r", encoding="utf-8") as handle:
                return json.load(handle)

    def _write(self, key: str, value: Any) -> None:
        with self._lock:
            self._atomic_write(self._path(key), value)

    @staticmethod
    def _atomic_write(path: Path, value: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                json.dump(value, handle, ensure_ascii=False, indent=2, default=str)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, path)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)

    def learner(self) -> LearnerProfile:
        return LearnerProfile.model_validate(self._read("learner"))

    def save_learner(self, profile: LearnerProfile) -> None:
        self._write("learner", profile.model_dump(mode="json"))

    def course(self) -> CoursePlan:
        return CoursePlan.model_validate(self._read("course"))

    def save_course(self, course: CoursePlan) -> None:
        self._write("course", course.model_dump(mode="json"))

    def mark_stage_completed(self, stage_id: str) -> CoursePlan:
        course = self.course()
        updated = [
            stage.model_copy(update={"completed": True}) if stage.id == stage_id else stage
            for stage in course.stages
        ]
        if not any(stage.id == stage_id for stage in course.stages):
            raise KeyError(f"unknown stage: {stage_id}")
        result = course.model_copy(update={"stages": updated, "updated_at": datetime.now(UTC)})
        self.save_course(result)
        return result

    def concepts(self) -> dict[str, ConceptState]:
        return {
            key: ConceptState.model_validate(value) for key, value in self._read("concepts").items()
        }

    def save_concepts(self, concepts: dict[str, ConceptState]) -> None:
        self._write(
            "concepts", {key: value.model_dump(mode="json") for key, value in concepts.items()}
        )

    def errors(self) -> list[ErrorRecord]:
        return [ErrorRecord.model_validate(value) for value in self._read("errors")]

    def save_errors(self, errors: list[ErrorRecord]) -> None:
        self._write("errors", [value.model_dump(mode="json") for value in errors])

    def reviews(self) -> dict[str, ReviewState]:
        return {
            key: ReviewState.model_validate(value) for key, value in self._read("reviews").items()
        }

    def save_reviews(self, reviews: dict[str, ReviewState]) -> None:
        self._write(
            "reviews", {key: value.model_dump(mode="json") for key, value in reviews.items()}
        )

    def snapshot(self) -> dict[str, Any]:
        return {
            "learner": self.learner().model_dump(mode="json"),
            "course": self.course().model_dump(mode="json"),
            "concepts": {
                key: value.model_dump(mode="json") for key, value in self.concepts().items()
            },
            "recent_errors": [value.model_dump(mode="json") for value in self.errors()[-10:]],
            "due_reviews": [
                value.model_dump(mode="json")
                for value in self.reviews().values()
                if value.due_at <= datetime.now(UTC)
            ],
        }


class MemoryGate:
    def __init__(self, workspace: LearningWorkspace) -> None:
        self.workspace = workspace

    def apply(self, candidate: MemoryCandidate) -> dict[str, Any]:
        if candidate.confidence < 0.60:
            return {"status": "rejected", "reason": "confidence below write threshold"}
        if candidate.expires_at and candidate.expires_at <= datetime.now(UTC):
            return {"status": "rejected", "reason": "candidate already expired"}
        if candidate.type == "profile":
            current = self.workspace.learner()
            profile = LearnerProfile.model_validate(
                {**current.model_dump(mode="python"), **candidate.content}
            )
            profile.updated_at = datetime.now(UTC)
            self.workspace.save_learner(profile)
            return {"status": "applied", "target": "learner"}
        if candidate.type == "preference":
            profile = self.workspace.learner()
            preferences = {**profile.preferences, **candidate.content}
            self.workspace.save_learner(
                profile.model_copy(
                    update={"preferences": preferences, "updated_at": datetime.now(UTC)}
                )
            )
            return {"status": "applied", "target": "preferences"}
        return {"status": "rejected", "reason": "candidate type requires a domain tool"}
