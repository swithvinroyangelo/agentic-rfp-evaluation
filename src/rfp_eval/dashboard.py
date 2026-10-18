"""Pure helpers for the procurement dashboard. No Streamlit calls and no API calls."""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from pathlib import Path

from rfp_eval.db import Criterion, validate_active_criteria
from rfp_eval.scoring import parse_submission_date, validate_experience_rating, validate_supplier_name

TIE_BREAK_RULE = (
    "Rank uses higher PPI, then earlier submission date, then higher experience rating, "
    "then supplier name from A to Z."
)


@dataclass(frozen=True)
class SupplierFormRow:
    supplier_name: str
    submission_date: str
    experience_rating: int
    filename: str


def default_database_path(project_root: Path) -> Path:
    return Path(project_root) / "data" / "rfp_eval.db"


def evaluation_block_reason(criteria: list[Criterion]) -> str | None:
    """Return why evaluation cannot start, or None when active weights total 100."""
    try:
        validate_active_criteria([criterion for criterion in criteria if criterion.is_active])
    except ValueError as error:
        return str(error)
    return None


def validate_supplier_rows(rows: list[SupplierFormRow]) -> list[str]:
    if not rows:
        return ["Upload at least one PDF."]
    errors: list[str] = []
    names: list[str] = []
    for row in rows:
        label = row.filename or "PDF"
        try:
            names.append(validate_supplier_name(row.supplier_name).strip())
        except ValueError as error:
            errors.append(f"{label}: {error}")
        try:
            parse_submission_date(row.submission_date)
        except ValueError as error:
            errors.append(f"{label}: {error}")
        try:
            validate_experience_rating(row.experience_rating)
        except ValueError as error:
            errors.append(f"{label}: {error}")
    if len(names) != len(set(names)):
        errors.append("Supplier names must be unique within a run.")
    return errors


def submission_token(rows: list[SupplierFormRow]) -> str:
    payload = tuple(
        sorted(
            (
                row.supplier_name.strip(),
                row.submission_date,
                row.experience_rating,
                row.filename,
            )
            for row in rows
        )
    )
    return hashlib.sha256(repr(payload).encode("utf-8")).hexdigest()


def duplicate_submission_message(token: str, previous_token: str | None, previous_run_id: str | None) -> str | None:
    if previous_token and token == previous_token:
        run_label = previous_run_id or "the previous run"
        return f"This batch was already submitted as run {run_label}."
    return None


def completion_message(status: str) -> tuple[str, str]:
    """Return a message level and text. Only a fully scored run is a success."""
    if status == "completed":
        return "success", "Evaluation completed. Every supplier was scored and ranked."
    if status == "completed_with_failures":
        return (
            "error",
            "Evaluation finished with supplier failures. Ranked suppliers were saved. "
            "Failed suppliers were not given a score or a rank.",
        )
    return "error", "Evaluation failed. No supplier was scored, so there is no leaderboard."


def partition_suppliers(payloads: list[dict]) -> tuple[list[dict], list[dict]]:
    """Split scored suppliers from failures. Failed suppliers are not ranked."""
    scored = [
        item for item in payloads
        if item.get("status") == "scored" and item.get("final_rank") is not None
    ]
    failed = [item for item in payloads if item not in scored]
    scored.sort(key=lambda item: item["final_rank"])
    return scored, failed


def leaderboard_rows(scored: list[dict]) -> list[dict]:
    return [
        {
            "Rank": item["final_rank"],
            "Supplier": item["supplier_name"],
            "Absolute score": _round(item["absolute_score"]),
            "PPI": _round(item["ppi"]),
            "Submission date": item["submission_date"],
            "Experience": item["experience_rating"],
        }
        for item in scored
    ]


def scorecard_rows(supplier: dict) -> list[dict]:
    return [
        {
            "Criterion": item["name"],
            "Score": _round(item["score"]),
            "Maximum": item["max_score"],
            "Weight": item["weight"],
            "Benchmark": _round(item["benchmark"]),
            "Gap": _round(item["gap"]),
            "Relative %": _round(item["relative_percent"]),
            "Evidence": item["evidence"],
            "Justification": item["justification"],
        }
        for item in supplier.get("criteria", [])
    ]


def explain_ranking(scored: list[dict]) -> list[str]:
    """Explain the stored order. This does not calculate a new rank."""
    lines = [TIE_BREAK_RULE]
    ordered = sorted(scored, key=lambda item: item["final_rank"])
    for ahead, behind in zip(ordered, ordered[1:]):
        lines.append(_pair_reason(ahead, behind))
    return lines


def _pair_reason(ahead: dict, behind: dict) -> str:
    ahead_name = ahead["supplier_name"]
    behind_name = behind["supplier_name"]
    if not math.isclose(float(ahead["ppi"]), float(behind["ppi"])):
        return (
            f"{ahead_name} ranks above {behind_name} because PPI {ahead['ppi']} "
            f"is higher than {behind['ppi']}."
        )
    if ahead["submission_date"] != behind["submission_date"]:
        return (
            f"{ahead_name} ranks above {behind_name} on submission date "
            f"{ahead['submission_date']}, which is earlier than {behind['submission_date']}."
        )
    if ahead["experience_rating"] != behind["experience_rating"]:
        return (
            f"{ahead_name} ranks above {behind_name} because experience rating "
            f"{ahead['experience_rating']} is higher than {behind['experience_rating']}."
        )
    return f"{ahead_name} ranks above {behind_name} because the supplier name comes first alphabetically."


def _round(value: object) -> object:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return value
    return round(float(value), 2)
