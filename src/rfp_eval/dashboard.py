"""Pure helpers for the procurement dashboard. No Streamlit calls and no API calls."""

from __future__ import annotations

import csv
import hashlib
import io
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


def intake_status(
    has_key: bool,
    criteria_ready: bool,
    upload_count: int,
    detail_errors: list[str],
) -> list[tuple[str, bool]]:
    """Live checklist for the upload page. True means that step is complete."""
    details_ready = upload_count > 0 and not detail_errors
    return [
        ("API key entered", bool(has_key)),
        ("Criteria total 100%", bool(criteria_ready)),
        ("PDFs uploaded", upload_count > 0),
        ("Supplier details complete", details_ready),
    ]


SAMPLE_PROPOSAL_DETAILS = {
    "apex_systems.pdf": ("Apex Systems", "2026-02-10", 4),
    "brightpath_tech.pdf": ("BrightPath Tech", "2026-01-20", 2),
    "nexaworks.pdf": ("NexaWorks", "2026-02-01", 4),
    "orbit_digital.pdf": ("Orbit Digital", "2026-01-15", 5),
}
SAMPLE_SUPPLIER_NAMES = {
    filename: name for filename, (name, _submitted, _experience) in SAMPLE_PROPOSAL_DETAILS.items()
}


def detail_with_sample_fallback(filename: str, stored: dict | None) -> dict:
    """Use a saved supplier record. Known sample files fill the record when none was saved."""
    if stored is not None:
        return stored
    sample = SAMPLE_PROPOSAL_DETAILS.get(Path(filename).name)
    if sample is None:
        return {}
    name, submitted, experience = sample
    return {
        "supplier_name": name,
        "submission_date": submitted,
        "experience_rating": experience,
    }


def remembered_supplier_row(filename: str, stored: dict | None) -> SupplierFormRow:
    """Build one supplier row from details saved outside the upload widgets."""
    item = stored or {}
    submitted = item.get("submission_date", "")
    if hasattr(submitted, "isoformat"):
        submitted = submitted.isoformat()
    experience = item.get("experience_rating", 3)
    return SupplierFormRow(
        supplier_name=str(item.get("supplier_name", "") or ""),
        submission_date=str(submitted or ""),
        experience_rating=int(experience),
        filename=Path(filename).name,
    )


def suggest_supplier_name(filename: str) -> str:
    """Turn a proposal filename into a readable supplier name."""
    base = Path(filename).name
    if base in SAMPLE_SUPPLIER_NAMES:
        return SAMPLE_SUPPLIER_NAMES[base]
    words = Path(base).stem.replace("-", " ").replace("_", " ").split()
    return " ".join(word[:1].upper() + word[1:] for word in words if word)


def leaderboard_csv(rows: list[dict]) -> str:
    """CSV text for the ranked suppliers. Failed suppliers are not included."""
    if not rows:
        return ""
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue()


def waiting_for_results_message(has_key: bool) -> str:
    """Empty-results text. A confirmed key should not be asked for again."""
    if has_key:
        return "No results yet. Click Evaluate suppliers to score the proposals on this page."
    return "No results yet. Confirm an API key in the sidebar, then click Evaluate suppliers."


def resolve_api_key(typed: str, saved: str) -> str:
    """Prefer a key typed for this session. A saved setting is used only when the box is blank."""
    entered = (typed or "").strip()
    if entered:
        return entered
    return (saved or "").strip()


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
