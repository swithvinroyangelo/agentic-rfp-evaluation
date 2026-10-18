"""Run one RFP batch from PDFs through scoring and persistence."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from rfp_eval.db import initialize_database, load_active_criteria, load_evaluation_run, save_evaluation_run
from rfp_eval.llm_client import EvaluationClient
from rfp_eval.pdf_extract import PdfExtractionError, extract_pdf_text
from rfp_eval.ranking import rank_suppliers
from rfp_eval.scoring import (
    SupplierEvaluation,
    parse_submission_date,
    score_suppliers,
    validate_experience_rating,
    validate_supplier_name,
)
from rfp_eval.validation import NormalizedEvaluation, normalize_evaluation


@dataclass(frozen=True)
class SupplierSubmission:
    supplier_name: str
    pdf_path: Path | str
    submission_date: str
    experience_rating: int


@dataclass(frozen=True)
class BatchResult:
    rfp_run_id: str
    status: str
    created_at: str
    suppliers: tuple[dict, ...]
    warnings: tuple[str, ...]

    def to_dict(self) -> dict:
        return {
            "rfp_run_id": self.rfp_run_id,
            "status": self.status,
            "created_at": self.created_at,
            "warnings": list(self.warnings),
            "suppliers": list(self.suppliers),
        }


def run_evaluation_batch(
    db_path: Path | str,
    suppliers: list[SupplierSubmission],
    model: EvaluationClient,
    run_id: str | None = None,
    on_progress=None,
) -> BatchResult:
    """Evaluate a batch. A supplier failure is stored, and successful suppliers are kept.

    Failed suppliers are not given a zero score or a rank. The run status is
    "completed" only when every supplier is scored. "completed_with_failures"
    means at least one supplier was scored and at least one failed. "failed"
    means none were scored.
    """
    if not suppliers:
        raise ValueError("At least one supplier is required.")
    _validate_submissions(suppliers)
    initialize_database(db_path)
    criteria = load_active_criteria(db_path)
    batch_id = run_id or str(uuid.uuid4())
    created_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()

    scored_inputs: list[tuple[SupplierSubmission, NormalizedEvaluation]] = []
    failures: list[dict] = []
    total = len(suppliers)
    for index, submission in enumerate(suppliers, start=1):
        _notify(on_progress, f"Evaluating {submission.supplier_name}", index / (total + 1))
        try:
            proposal_text = extract_pdf_text(submission.pdf_path)
        except PdfExtractionError as error:
            failures.append(_failure_record(submission, "extraction", str(error)))
            continue
        try:
            raw_response = model.evaluate(submission.supplier_name, proposal_text, criteria)
        except Exception as error:
            failures.append(_failure_record(submission, "evaluation", str(error)))
            continue
        try:
            normalized = normalize_evaluation(raw_response, submission.supplier_name, criteria)
        except ValueError as error:
            failures.append(_failure_record(submission, "validation", str(error), raw_response))
            continue
        scored_inputs.append((submission, normalized))

    ranked: list[SupplierEvaluation] = []
    if scored_inputs:
        scorecards = [
            normalized.to_scorecard(submission.submission_date, submission.experience_rating)
            for submission, normalized in scored_inputs
        ]
        ranked = rank_suppliers(score_suppliers(criteria, scorecards))

    normalized_by_name = {
        submission.supplier_name.strip(): normalized for submission, normalized in scored_inputs
    }
    successes = [
        _success_record(normalized_by_name[item.supplier_name], item)
        for item in ranked
    ]
    supplier_rows = successes + failures
    if successes and failures:
        status = "completed_with_failures"
    elif successes:
        status = "completed"
    else:
        status = "failed"

    warnings: list[str] = []
    for row in supplier_rows:
        for warning in row["result_json"]["warnings"]:
            if warning not in warnings:
                warnings.append(warning)

    _notify(on_progress, "Saving results", 1)
    save_evaluation_run(
        db_path,
        batch_id,
        created_at,
        status,
        [
            {
                "supplier_name": row["supplier_name"],
                "submission_date": row["submission_date"],
                "experience_rating": row["experience_rating"],
                "absolute_score": row["absolute_score"],
                "ppi": row["ppi"],
                "final_rank": row["final_rank"],
                "result_json": row["result_json"],
            }
            for row in supplier_rows
        ],
    )
    stored = load_evaluation_run(db_path, batch_id)
    return BatchResult(
        rfp_run_id=stored["rfp_run_id"],
        status=stored["status"],
        created_at=stored["created_at"],
        suppliers=tuple(row["result_json"] for row in stored["suppliers"]),
        warnings=tuple(warnings),
    )


def _notify(callback, message: str, fraction: float) -> None:
    if callback is not None:
        callback(message, fraction)


def _validate_submissions(suppliers: list[SupplierSubmission]) -> None:
    names = [validate_supplier_name(item.supplier_name).strip() for item in suppliers]
    if len(names) != len(set(names)):
        raise ValueError("Supplier names must be unique within a run.")
    for item in suppliers:
        parse_submission_date(item.submission_date)
        validate_experience_rating(item.experience_rating)


def _success_record(normalized: NormalizedEvaluation, evaluation: SupplierEvaluation) -> dict:
    submitted = evaluation.submission_date.isoformat()
    criteria = []
    details = {item.criterion_id: item for item in normalized.criteria}
    for result in evaluation.criteria:
        detail = details[result.criterion_id]
        criteria.append(
            {
                "criterion_id": result.criterion_id,
                "name": result.name,
                "weight": result.weight,
                "max_score": result.max_score,
                "score": result.score,
                "benchmark": result.benchmark,
                "gap": result.gap,
                "relative_percent": result.relative_percent,
                "justification": detail.justification,
                "evidence": detail.evidence,
            }
        )
    warnings = tuple(dict.fromkeys((*normalized.warnings, *evaluation.warnings)))
    payload = {
        "supplier_name": evaluation.supplier_name,
        "submission_date": submitted,
        "experience_rating": evaluation.experience_rating,
        "status": "scored",
        "absolute_score": evaluation.absolute_score,
        "ppi": evaluation.ppi,
        "final_rank": evaluation.final_rank,
        "risks": list(normalized.risks),
        "overall_summary": normalized.overall_summary,
        "warnings": list(warnings),
        "criteria": criteria,
    }
    return {
        "supplier_name": evaluation.supplier_name,
        "submission_date": submitted,
        "experience_rating": evaluation.experience_rating,
        "absolute_score": evaluation.absolute_score,
        "ppi": evaluation.ppi,
        "final_rank": evaluation.final_rank,
        "result_json": payload,
    }


def _failure_record(
    submission: SupplierSubmission,
    stage: str,
    message: str,
    raw_response: str | None = None,
) -> dict:
    payload = {
        "supplier_name": submission.supplier_name.strip(),
        "submission_date": parse_submission_date(submission.submission_date).isoformat(),
        "experience_rating": submission.experience_rating,
        "status": "failed",
        "stage": stage,
        "error": message,
        "warnings": [],
        "absolute_score": None,
        "ppi": None,
        "final_rank": None,
    }
    if raw_response is not None:
        payload["raw_model_response"] = raw_response
    return {
        "supplier_name": payload["supplier_name"],
        "submission_date": payload["submission_date"],
        "experience_rating": submission.experience_rating,
        "absolute_score": None,
        "ppi": None,
        "final_rank": None,
        "result_json": payload,
    }
