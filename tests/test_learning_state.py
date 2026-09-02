from __future__ import annotations

from datetime import UTC, datetime

import pytest

from learningloop.learning.scheduler import schedule_review, score_to_rating
from learningloop.learning.schemas import CoursePlan, CourseStage, MemoryCandidate
from learningloop.learning.state import LearningWorkspace, MemoryGate


def test_workspace_initializes_and_persists(settings) -> None:
    workspace = LearningWorkspace(settings.workspace_dir, "session-1")
    profile = workspace.learner().model_copy(update={"daily_minutes": 90})
    workspace.save_learner(profile)
    reopened = LearningWorkspace(settings.workspace_dir, "session-1")
    assert reopened.learner().daily_minutes == 90


def test_workspace_rejects_path_escape(settings) -> None:
    with pytest.raises(ValueError):
        LearningWorkspace(settings.workspace_dir, "../escape")


def test_course_dependency_validation() -> None:
    with pytest.raises(ValueError):
        CoursePlan(
            title="test",
            goal="goal",
            stages=[
                CourseStage(
                    id="stage-1",
                    title="Stage",
                    objective="Objective",
                    estimated_days=1,
                    prerequisite_ids=["missing"],
                )
            ],
        )


def test_memory_gate_requires_confidence_and_source(settings) -> None:
    workspace = LearningWorkspace(settings.workspace_dir, "session-2")
    gate = MemoryGate(workspace)
    rejected = gate.apply(
        MemoryCandidate(
            type="profile", content={"background": "test"}, source_message_id=1, confidence=0.5
        )
    )
    assert rejected["status"] == "rejected"
    applied = gate.apply(
        MemoryCandidate(
            type="profile", content={"background": "test"}, source_message_id=1, confidence=0.9
        )
    )
    assert applied["status"] == "applied"
    assert workspace.learner().background == "test"


def test_fsrs_schedule_and_rating() -> None:
    assert score_to_rating(0.2) == "again"
    assert score_to_rating(0.8) == "good"
    review = schedule_review("tool-calling", 0.8)
    assert review.due_at > datetime.now(UTC)
    assert review.review_count == 1
