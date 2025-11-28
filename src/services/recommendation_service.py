from __future__ import annotations

from dataclasses import dataclass
from typing import List, Dict, Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.user_service.models import Professor, Review


@dataclass
class PreferenceWeights:
    clarity_weight: float = 1.0
    workload_weight: float = 1.0
    grading_weight: float = 1.0


CLARITY_POSITIVE = [
    "clear",
    "organized",
    "easy to understand",
    "understandable",
    "well explained",
]

CLARITY_NEGATIVE = [
    "confusing",
    "unclear",
    "disorganized",
    "hard to understand",
]

WORKLOAD_POSITIVE = [
    "light workload",
    "light work",
    "not much work",
    "easy",
    "chill",
]

WORKLOAD_NEGATIVE = [
    "heavy workload",
    "a lot of work",
    "too much work",
    "tons of work",
    "busywork",
]

GRADING_POSITIVE = [
    "fair grader",
    "fair grading",
    "reasonable",
    "transparent",
    "lenient",
    "easy grader",
]

GRADING_NEGATIVE = [
    "unfair",
    "harsh",
    "strict",
    "hard marker",
    "tough grader",
]


def _count_keywords(text: str, keywords: List[str]) -> int:
    lowered = text.lower()
    count = 0
    for kw in keywords:
        if kw in lowered:
            count += 1
    return count


def _compute_review_metrics(reviews: List[Review]) -> Dict[str, float]:
    if not reviews:
        return {
            "avg_rating": 0.0,
            "clarity_score": 0.0,
            "workload_score": 0.0,
            "grading_score": 0.0,
        }

    total_rating = 0.0
    clarity_balance = 0.0
    workload_balance = 0.0
    grading_balance = 0.0

    for review in reviews:
        text = review.text or ""
        total_rating += float(review.rating or 0.0)

        clarity_balance += _count_keywords(text, CLARITY_POSITIVE)
        clarity_balance -= _count_keywords(text, CLARITY_NEGATIVE)

        workload_balance += _count_keywords(text, WORKLOAD_POSITIVE)
        workload_balance -= _count_keywords(text, WORKLOAD_NEGATIVE)

        grading_balance += _count_keywords(text, GRADING_POSITIVE)
        grading_balance -= _count_keywords(text, GRADING_NEGATIVE)

    n = float(len(reviews))
    avg_rating = total_rating / n if n > 0 else 0.0

    def normalize(component: float) -> float:
        # Rough normalization into 0 to 1 range, centered at 0.5
        if component == 0.0:
            return 0.5
        if component > 3.0:
            component = 3.0
        if component < -3.0:
            component = -3.0
        return 0.5 + (component / 6.0)

    clarity_score = normalize(clarity_balance / n)
    workload_score = normalize(workload_balance / n)
    grading_score = normalize(grading_balance / n)

    return {
        "avg_rating": avg_rating,
        "clarity_score": clarity_score,
        "workload_score": workload_score,
        "grading_score": grading_score,
    }


def _combine_scores(metrics: Dict[str, float], weights: PreferenceWeights) -> float:
    clarity_component = metrics["clarity_score"]
    workload_component = metrics["workload_score"]
    grading_component = metrics["grading_score"]

    w_clarity = max(0.0, weights.clarity_weight)
    w_workload = max(0.0, weights.workload_weight)
    w_grading = max(0.0, weights.grading_weight)

    total_weight = w_clarity + w_workload + w_grading
    if total_weight <= 0.0:
        return (clarity_component + workload_component + grading_component) / 3.0

    score = (
        clarity_component * w_clarity
        + workload_component * w_workload
        + grading_component * w_grading
    ) / total_weight

    return score


def recommend_professors_for_user(
    db: Session,
    user_id: int,
    weights: PreferenceWeights,
    limit: int = 5,
) -> List[Dict[str, Any]]:
    """
    Compute professor recommendations for a given user.

    The ranking is deterministic for a fixed set of weights and database state.
    """
    professors = db.execute(select(Professor)).scalars().all()

    recommendations: List[Dict[str, Any]] = []

    for prof in professors:
        reviews = db.execute(
            select(Review).where(Review.prof_id == prof.id)
        ).scalars().all()

        metrics = _compute_review_metrics(reviews)
        score = _combine_scores(metrics, weights)

        breakdown = {
            "avg_rating": metrics["avg_rating"],
            "clarity_score": metrics["clarity_score"],
            "workload_score": metrics["workload_score"],
            "grading_score": metrics["grading_score"],
            "clarity_weight": weights.clarity_weight,
            "workload_weight": weights.workload_weight,
            "grading_weight": weights.grading_weight,
        }

        recommendations.append(
            {
                "professor_id": prof.id,
                "name": prof.name,
                "department": getattr(prof, "department", None),
                "score": score,
                "breakdown": breakdown,
            }
        )

    # deterministic ordering: score desc, then id asc
    recommendations.sort(
        key=lambda item: (-item["score"], item["professor_id"])
    )

    return recommendations[: max(1, limit)]
