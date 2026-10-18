"""Deterministic tie-break sort and rank numbers."""

from __future__ import annotations

import math
from dataclasses import replace

from rfp_eval.scoring import (
    SupplierEvaluation,
    parse_submission_date,
    validate_experience_rating,
    validate_supplier_name,
)


def rank_suppliers(evaluations: list[SupplierEvaluation]) -> list[SupplierEvaluation]:
    """Sort by PPI, submission date, experience, then name, and then assign ranks."""
    names = [validate_supplier_name(item.supplier_name) for item in evaluations]
    if len(names) != len(set(names)):
        raise ValueError("Supplier names must be unique within a run.")

    checked: list[SupplierEvaluation] = []
    for item in evaluations:
        if not math.isfinite(item.ppi) or not math.isfinite(item.absolute_score):
            raise ValueError(f"{item.supplier_name} has a non-finite score.")
        checked.append(
            replace(
                item,
                supplier_name=validate_supplier_name(item.supplier_name),
                submission_date=parse_submission_date(item.submission_date),
                experience_rating=validate_experience_rating(item.experience_rating),
                final_rank=None,
            )
        )

    ordered = sorted(
        checked,
        key=lambda item: (
            -item.ppi,
            item.submission_date,
            -item.experience_rating,
            item.supplier_name,
        ),
    )
    return [replace(item, final_rank=rank) for rank, item in enumerate(ordered, start=1)]
