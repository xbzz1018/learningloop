from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class LearnerProfile(BaseModel):
    background: str = ""
    learning_topic: str = ""
    target_outcome: str = ""
    duration_days: int | None = Field(default=None, ge=1, le=365)
    weekly_days: int = Field(default=7, ge=1, le=7)
    daily_minutes: int = Field(default=45, ge=10, le=480)
    interface_language: str = "zh-CN"
    learning_language: str = "zh-CN"
    preferences: dict[str, str] = Field(default_factory=dict)
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class LessonUnit(BaseModel):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,79}$")
    title: str = Field(min_length=1, max_length=160)
    concepts: list[str] = Field(default_factory=list, max_length=20)
    explanation: str = Field(default="", max_length=4_000)
    example: str = Field(default="", max_length=6_000)
    exercise: str = Field(default="", max_length=4_000)
    expected_output: str = Field(default="", max_length=2_000)
    acceptance_criteria: str = Field(default="", max_length=2_000)
    estimated_minutes: int = Field(default=25, ge=5, le=480)


class CourseStage(BaseModel):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")
    title: str = Field(min_length=1, max_length=120)
    objective: str = Field(min_length=1, max_length=1_000)
    estimated_days: int = Field(ge=1, le=90)
    prerequisite_ids: list[str] = Field(default_factory=list)
    key_concepts: list[str] = Field(default_factory=list, max_length=20)
    lessons: list[LessonUnit] = Field(default_factory=list, max_length=20)
    stage_acceptance_criteria: str = Field(default="", max_length=2_000)
    recommended_practice: str = Field(default="", max_length=2_000)
    content_status: Literal["complete", "fallback", "needs_enrichment"] = "needs_enrichment"
    completed: bool = False


class CoursePlan(BaseModel):
    title: str = ""
    goal: str = ""
    duration_days: int = Field(default=30, ge=1, le=365)
    final_artifact: str = ""
    stages: list[CourseStage] = Field(default_factory=list, max_length=80)
    content_source: Literal["model", "deterministic", "fallback", "legacy"] = "legacy"
    version: int = 1
    approved: bool = False
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("stages")
    @classmethod
    def validate_stage_dependencies(cls, stages: list[CourseStage]) -> list[CourseStage]:
        ids = {stage.id for stage in stages}
        if len(ids) != len(stages):
            raise ValueError("stage ids must be unique")
        for stage in stages:
            missing = set(stage.prerequisite_ids) - ids
            if missing:
                raise ValueError(f"unknown prerequisite ids: {sorted(missing)}")
            if stage.id in stage.prerequisite_ids:
                raise ValueError("a stage cannot depend on itself")
        return stages


class ConceptState(BaseModel):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,79}$")
    name: str
    stage_id: str | None = None
    mastery: float = Field(default=0.0, ge=0.0, le=1.0)
    attempts: int = Field(default=0, ge=0)
    last_score: float | None = Field(default=None, ge=0.0, le=1.0)
    evidence_message_ids: list[int] = Field(default_factory=list)
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ErrorRecord(BaseModel):
    id: str
    concept_id: str
    category: Literal[
        "concept-gap", "application-failure", "expression-unclear", "knowledge-confusion"
    ]
    answer: str
    feedback: str
    source_message_id: int
    corrected: bool = False
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ReviewState(BaseModel):
    concept_id: str
    card: dict[str, Any]
    due_at: datetime
    last_rating: str | None = None
    review_count: int = 0
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class MemoryCandidate(BaseModel):
    type: Literal["profile", "concept", "error", "preference", "decision"]
    content: dict[str, Any]
    source_message_id: int
    confidence: float = Field(ge=0.0, le=1.0)
    expires_at: datetime | None = None


class LearningResult(BaseModel):
    concept_id: str
    concept_name: str
    stage_id: str | None = None
    score: float = Field(ge=0.0, le=1.0)
    source_message_id: int = Field(gt=0)
    answer: str = ""
    feedback: str = ""
    error_category: str | None = None


class DailyTask(BaseModel):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9:_-]{0,119}$")
    title: str = Field(min_length=1, max_length=200)
    category: str = Field(default="学习", min_length=1, max_length=40)
    objective: str = Field(default="", max_length=1_000)
    lesson_id: str | None = Field(default=None, max_length=80)
    concepts: list[str] = Field(default_factory=list, max_length=20)
    explanation: str = Field(default="", max_length=4_000)
    example: str = Field(default="", max_length=6_000)
    exercise: str = Field(default="", max_length=4_000)
    expected_output: str = Field(default="", max_length=2_000)
    acceptance_criteria: str = Field(default="", max_length=2_000)
    estimated_minutes: int = Field(default=25, ge=5, le=480)
    stage_id: str | None = None
    due_date: date
    completed: bool = False
    status: Literal["pending", "in_progress", "completed", "skipped"] = "pending"
    score: float | None = Field(default=None, ge=0.0, le=1.0)
    answer: str = Field(default="", max_length=8_000)
    notes: str = Field(default="", max_length=4_000)
    error_category: str | None = Field(default=None, max_length=80)
    completed_at: datetime | None = None

    @model_validator(mode="after")
    def normalize_status(self) -> DailyTask:
        if self.completed and self.status != "completed":
            self.status = "completed"
        elif self.status == "completed":
            self.completed = True
        return self


class DailyPlan(BaseModel):
    id: str
    session_id: str
    plan_date: date
    goal: str = ""
    tasks: list[DailyTask] = Field(default_factory=list, max_length=40)
    total_minutes: int = Field(default=0, ge=0, le=1_440)
    priority_reviews: list[str] = Field(default_factory=list, max_length=40)
    practice: str = Field(default="", max_length=2_000)
    completion_criteria: str = Field(default="完成今日任务并记录结果", max_length=1_000)
    source: Literal["deterministic", "model", "fallback"] = "deterministic"
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class DailyReview(BaseModel):
    id: str
    session_id: str
    review_date: date
    completed_task_ids: list[str] = Field(default_factory=list, max_length=40)
    unfinished_task_ids: list[str] = Field(default_factory=list, max_length=40)
    new_errors: list[str] = Field(default_factory=list, max_length=40)
    mastery_changes: dict[str, float] = Field(default_factory=dict)
    tomorrow_focus: list[str] = Field(default_factory=list, max_length=20)
    summary: str = Field(default="", max_length=4_000)
    plan_adjustment_suggested: bool = False
    source: Literal["deterministic", "model"] = "deterministic"
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
