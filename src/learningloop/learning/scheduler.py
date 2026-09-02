from __future__ import annotations

from datetime import UTC, datetime

from fsrs import Card, Rating, Scheduler

from learningloop.learning.schemas import ReviewState

RATINGS = {
    "again": Rating.Again,
    "hard": Rating.Hard,
    "good": Rating.Good,
    "easy": Rating.Easy,
}


def score_to_rating(score: float) -> str:
    if score < 0.4:
        return "again"
    if score < 0.7:
        return "hard"
    if score < 0.9:
        return "good"
    return "easy"


def schedule_review(
    concept_id: str, score: float, existing: ReviewState | None = None
) -> ReviewState:
    scheduler = Scheduler()
    card = Card.from_dict(existing.card) if existing else Card()
    rating_name = score_to_rating(score)
    updated_card, _review_log = scheduler.review_card(
        card, RATINGS[rating_name], review_datetime=datetime.now(UTC)
    )
    return ReviewState(
        concept_id=concept_id,
        card=updated_card.to_dict(),
        due_at=updated_card.due,
        last_rating=rating_name,
        review_count=(existing.review_count if existing else 0) + 1,
        updated_at=datetime.now(UTC),
    )
