"""Validate and normalize one LLM supplier evaluation before scoring."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, ValidationError, field_validator

from rfp_eval.db import Criterion, validate_active_criteria
from rfp_eval.scoring import CriterionScore, SupplierScorecard

MISSING_JUSTIFICATION = "No model result was returned for this criterion."
MISSING_EVIDENCE = "No evidence was provided."


@dataclass(frozen=True)
class NormalizedCriterion:
    criterion_id: int
    name: str
    score: float
    max_score: int
    justification: str
    evidence: str


@dataclass(frozen=True)
class NormalizedEvaluation:
    """One supplier result after schema checks. Scores are ready for scoring.py."""

    supplier_name: str
    criteria: tuple[NormalizedCriterion, ...]
    risks: tuple[str, ...]
    overall_summary: str
    warnings: tuple[str, ...]

    def to_scorecard(self, submission_date: str, experience_rating: int) -> SupplierScorecard:
        return SupplierScorecard(
            supplier_name=self.supplier_name,
            submission_date=submission_date,
            experience_rating=experience_rating,
            scores=tuple(CriterionScore(item.criterion_id, item.score) for item in self.criteria),
        )


class _CriterionPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    criterion_id: int
    score: float
    max_score: float
    justification: str
    evidence: str

    @field_validator("criterion_id", mode="before")
    @classmethod
    def criterion_id_is_int(cls, value: object) -> int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("criterion_id must be an integer.")
        return value

    @field_validator("score", "max_score", mode="before")
    @classmethod
    def finite_number(cls, value: object, info) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{info.field_name} must be a finite number.")
        if not math.isfinite(value):
            raise ValueError(f"{info.field_name} must be a finite number.")
        return float(value)

    @field_validator("justification", "evidence", mode="before")
    @classmethod
    def text_field(cls, value: object, info) -> str:
        if not isinstance(value, str):
            raise ValueError(f"{info.field_name} must be a string.")
        return value


class _EvaluationPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    supplier_name: str
    criteria: list[_CriterionPayload]
    risks: list[str]
    overall_summary: str

    @field_validator("supplier_name", "overall_summary", mode="before")
    @classmethod
    def text_field(cls, value: object, info) -> str:
        if not isinstance(value, str):
            raise ValueError(f"{info.field_name} must be a string.")
        return value

    @field_validator("risks", mode="before")
    @classmethod
    def risks_are_strings(cls, value: object) -> list[str]:
        if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
            raise ValueError("risks must be a list of strings.")
        return value

    @field_validator("criteria", mode="before")
    @classmethod
    def criteria_are_objects(cls, value: object) -> object:
        if not isinstance(value, list):
            raise ValueError("criteria must be a list.")
        return value


def normalize_evaluation(
    payload: str | dict,
    expected_supplier_name: str,
    criteria: list[Criterion],
) -> NormalizedEvaluation:
    """Parse one model response and return one result per active criterion."""
    active = list(criteria)
    _require_unique_criteria(active)
    validate_active_criteria(active)
    expected_name = _required_name(expected_supplier_name)
    parsed = _parse_payload(payload)

    warnings: list[str] = []
    if not parsed.overall_summary.strip():
        warnings.append("Overall summary is empty.")
    if parsed.supplier_name.strip() != expected_name:
        raise ValueError(
            f"Supplier name {parsed.supplier_name!r} does not match the expected supplier {expected_name!r}."
        )

    by_id = {criterion.criterion_id: criterion for criterion in active}
    chosen: dict[int, _CriterionPayload] = {}
    for item in parsed.criteria:
        configured = by_id.get(item.criterion_id)
        if configured is None:
            warnings.append(f"Ignored unknown criterion id {item.criterion_id}.")
            continue
        if item.criterion_id in chosen:
            warnings.append(f"Ignored duplicate criterion id {item.criterion_id}. Kept the first result.")
            continue
        chosen[item.criterion_id] = item

    normalized: list[NormalizedCriterion] = []
    for criterion in active:
        item = chosen.get(criterion.criterion_id)
        if item is None:
            warnings.append(f"Missing result for {criterion.name}. Score set to 0.")
            normalized.append(
                NormalizedCriterion(
                    criterion_id=criterion.criterion_id,
                    name=criterion.name,
                    score=0.0,
                    max_score=criterion.max_score,
                    justification=MISSING_JUSTIFICATION,
                    evidence=MISSING_EVIDENCE,
                )
            )
            continue
        if item.max_score != criterion.max_score:
            warnings.append(
                f"Model max_score for {criterion.name} was {item.max_score} and was replaced "
                f"with the configured maximum {criterion.max_score}."
            )
        score = item.score
        if score < 0:
            warnings.append(f"Score for {criterion.name} was {score} and was clipped to 0.")
            score = 0.0
        elif score > criterion.max_score:
            warnings.append(
                f"Score for {criterion.name} was {score} and was clipped to {criterion.max_score}."
            )
            score = float(criterion.max_score)
        if not item.justification.strip():
            warnings.append(f"Justification for {criterion.name} is empty.")
        if not item.evidence.strip():
            warnings.append(f"Evidence for {criterion.name} is empty.")
        normalized.append(
            NormalizedCriterion(
                criterion_id=criterion.criterion_id,
                name=criterion.name,
                score=score,
                max_score=criterion.max_score,
                justification=item.justification,
                evidence=item.evidence,
            )
        )

    return NormalizedEvaluation(
        supplier_name=expected_name,
        criteria=tuple(normalized),
        risks=tuple(parsed.risks),
        overall_summary=parsed.overall_summary,
        warnings=tuple(warnings),
    )


def _parse_payload(payload: str | dict) -> _EvaluationPayload:
    if isinstance(payload, str):
        try:
            loaded = json.loads(payload)
        except json.JSONDecodeError as error:
            raise ValueError("Evaluation response is not valid JSON.") from error
    elif isinstance(payload, dict):
        loaded = payload
    else:
        raise ValueError("Evaluation response must be a JSON object.")
    if not isinstance(loaded, dict):
        raise ValueError("Evaluation response must be a JSON object.")
    try:
        return _EvaluationPayload.model_validate(loaded)
    except ValidationError as error:
        raise ValueError(str(error)) from error


def _require_unique_criteria(criteria: list[Criterion]) -> None:
    ids = [criterion.criterion_id for criterion in criteria]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate criteria are not allowed.")


def _required_name(name: str) -> str:
    if not isinstance(name, str) or not name.strip():
        raise ValueError("Supplier name is required.")
    return name.strip()
