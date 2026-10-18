"""Absolute scores, benchmarks, gaps, relative percentages, and PPI."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date

from rfp_eval.db import Criterion, validate_active_criteria


@dataclass(frozen=True)
class CriterionScore:
    criterion_id: int
    score: float


@dataclass(frozen=True)
class SupplierScorecard:
    supplier_name: str
    submission_date: date | str
    experience_rating: int
    scores: tuple[CriterionScore, ...]


@dataclass(frozen=True)
class CriterionResult:
    criterion_id: int
    name: str
    weight: int
    max_score: int
    score: float
    benchmark: float
    gap: float
    relative_percent: float


@dataclass(frozen=True)
class SupplierEvaluation:
    supplier_name: str
    submission_date: date
    experience_rating: int
    absolute_score: float
    ppi: float
    criteria: tuple[CriterionResult, ...]
    warnings: tuple[str, ...]
    final_rank: int | None = None


def score_suppliers(
    criteria: list[Criterion],
    suppliers: list[SupplierScorecard],
) -> list[SupplierEvaluation]:
    """Score every supplier. Ranks stay unset; ranking.py assigns them after sorting."""
    active = list(criteria)
    _validate_criteria(active)
    _validate_unique_names([supplier.supplier_name for supplier in suppliers])

    prepared: list[tuple[SupplierScorecard, dict[int, float], float]] = []
    for supplier in suppliers:
        scores = _scores_by_criterion(supplier, active)
        prepared.append((supplier, scores, _absolute_score(active, scores)))

    benchmarks = {
        criterion.criterion_id: max(scores[criterion.criterion_id] for _, scores, _ in prepared)
        for criterion in active
    } if prepared else {}
    warnings = tuple(
        f"Criterion {criterion.name} benchmark is 0. Relative performance is 0."
        for criterion in active
        if benchmarks.get(criterion.criterion_id, 0) == 0 and prepared
    )
    weight_total = sum(criterion.weight for criterion in active)

    evaluations: list[SupplierEvaluation] = []
    for supplier, scores, absolute_score in prepared:
        criterion_results: list[CriterionResult] = []
        for criterion in active:
            score = scores[criterion.criterion_id]
            benchmark = benchmarks[criterion.criterion_id]
            if benchmark == 0:
                relative_percent = 0.0
            else:
                relative_percent = (score / benchmark) * 100
            criterion_results.append(
                CriterionResult(
                    criterion_id=criterion.criterion_id,
                    name=criterion.name,
                    weight=criterion.weight,
                    max_score=criterion.max_score,
                    score=score,
                    benchmark=benchmark,
                    gap=score - benchmark,
                    relative_percent=relative_percent,
                )
            )
        ppi = sum(result.relative_percent * result.weight for result in criterion_results) / weight_total
        evaluations.append(
            SupplierEvaluation(
                supplier_name=validate_supplier_name(supplier.supplier_name),
                submission_date=parse_submission_date(supplier.submission_date),
                experience_rating=validate_experience_rating(supplier.experience_rating),
                absolute_score=absolute_score,
                ppi=ppi,
                criteria=tuple(criterion_results),
                warnings=warnings,
            )
        )
    return evaluations


def validate_supplier_name(name: str) -> str:
    if not isinstance(name, str) or not name.strip():
        raise ValueError("Supplier name is required.")
    return name


def parse_submission_date(value: date | str) -> date:
    if type(value) is date:
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError as error:
            raise ValueError("Submission date must be an ISO date, YYYY-MM-DD.") from error
    raise ValueError("Submission date must be an ISO date, YYYY-MM-DD.")


def validate_experience_rating(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 5:
        raise ValueError("Historical experience rating must be a whole number from 1 to 5.")
    return value


def _validate_unique_names(names: list[str]) -> None:
    cleaned = [validate_supplier_name(name) for name in names]
    if len(cleaned) != len(set(cleaned)):
        raise ValueError("Supplier names must be unique within a run.")


def _validate_criteria(criteria: list[Criterion]) -> None:
    ids = [criterion.criterion_id for criterion in criteria]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate criteria are not allowed.")
    for criterion in criteria:
        if isinstance(criterion.weight, bool) or isinstance(criterion.max_score, bool):
            raise ValueError(f"Criterion {criterion.name} has a non-numeric weight or maximum score.")
        if not isinstance(criterion.weight, (int, float)) or not isinstance(criterion.max_score, (int, float)):
            raise ValueError(f"Criterion {criterion.name} has a non-numeric weight or maximum score.")
        if not math.isfinite(criterion.weight) or not math.isfinite(criterion.max_score):
            raise ValueError(f"Criterion {criterion.name} has a non-finite weight or maximum score.")
    validate_active_criteria(criteria)


def _scores_by_criterion(supplier: SupplierScorecard, criteria: list[Criterion]) -> dict[int, float]:
    scores: dict[int, float] = {}
    for item in supplier.scores:
        if item.criterion_id in scores:
            raise ValueError(f"Duplicate score for criterion {item.criterion_id}.")
        if isinstance(item.score, bool) or not isinstance(item.score, (int, float)) or not math.isfinite(item.score):
            raise ValueError(f"Criterion {item.criterion_id} has a non-finite score.")
        scores[item.criterion_id] = float(item.score)

    expected = {criterion.criterion_id: criterion for criterion in criteria}
    missing = [criterion.name for criterion_id, criterion in expected.items() if criterion_id not in scores]
    unknown = sorted(set(scores) - set(expected))
    if missing:
        raise ValueError(f"Missing scores for: {', '.join(missing)}.")
    if unknown:
        raise ValueError(f"Unknown criterion ids: {unknown}.")
    for criterion in criteria:
        score = scores[criterion.criterion_id]
        if score < 0 or score > criterion.max_score:
            raise ValueError(
                f"Score for {criterion.name} must be from 0 to {criterion.max_score}."
            )
    return scores


def _absolute_score(criteria: list[Criterion], scores: dict[int, float]) -> float:
    return sum((scores[criterion.criterion_id] / criterion.max_score) * criterion.weight for criterion in criteria)
