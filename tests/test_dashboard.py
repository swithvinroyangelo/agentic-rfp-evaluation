"""Dashboard helper tests. No API key, no network, and no Streamlit runtime."""

import importlib
import os
import subprocess
import sys
from pathlib import Path

import pytest

from rfp_eval.dashboard import (
    SupplierFormRow,
    completion_message,
    intake_status,
    resolve_api_key,
    duplicate_submission_message,
    evaluation_block_reason,
    explain_ranking,
    leaderboard_rows,
    partition_suppliers,
    scorecard_rows,
    submission_token,
    validate_supplier_rows,
)
from rfp_eval.db import Criterion, initialize_database, list_all_criteria, load_active_criteria, update_criteria


def _row(name="Apex Systems", submitted="2026-03-01", experience=4, filename="apex.pdf"):
    return SupplierFormRow(name, submitted, experience, filename)


def test_supplier_rows_require_unique_names_dates_and_experience():
    assert validate_supplier_rows([]) == ["Upload at least one PDF."]
    errors = validate_supplier_rows(
        [
            _row(""),
            _row("Apex Systems", "03/01/2026", 4, "second.pdf"),
            _row("Apex Systems", "2026-03-01", 9, "third.pdf"),
        ]
    )
    assert any("Supplier name is required." in error for error in errors)
    assert any("YYYY-MM-DD" in error for error in errors)
    assert any("1 to 5" in error for error in errors)
    assert "Supplier names must be unique within a run." in errors
    assert validate_supplier_rows([_row(), _row("BrightPath Tech", filename="bright.pdf")]) == []


def test_submission_token_is_stable_and_ignores_row_order():
    first = [_row(), _row("BrightPath Tech", filename="bright.pdf")]
    second = list(reversed(first))
    assert submission_token(first) == submission_token(second)
    assert submission_token(first) != submission_token([_row(experience=5)])


def test_intake_checklist_updates_as_the_user_fills_the_page():
    empty = dict(intake_status(False, True, 0, ["Upload at least one PDF."]))
    assert empty["API key entered"] is False
    assert empty["PDFs uploaded"] is False
    assert empty["Supplier details complete"] is False
    ready = dict(intake_status(True, True, 2, []))
    assert all(ready.values())
    named = dict(intake_status(True, True, 1, ["proposal.pdf: Supplier name is required."]))
    assert named["PDFs uploaded"] is True
    assert named["Supplier details complete"] is False


def test_typed_api_key_is_used_before_a_saved_setting():
    assert resolve_api_key(" typed ", "saved") == "typed"
    assert resolve_api_key("  ", "saved") == "saved"
    assert resolve_api_key("", "") == ""


def test_duplicate_submission_and_completion_messages():
    assert duplicate_submission_message("abc", "abc", "run-1") == "This batch was already submitted as run run-1."
    assert duplicate_submission_message("abc", None, None) is None
    assert completion_message("completed")[0] == "success"
    assert completion_message("completed_with_failures")[0] == "error"
    assert completion_message("failed")[0] == "error"


def test_leaderboard_excludes_failures_and_scorecard_keeps_evidence():
    scored = {
        "status": "scored",
        "supplier_name": "Apex Systems",
        "absolute_score": 100,
        "ppi": 80,
        "submission_date": "2026-02-01",
        "experience_rating": 2,
        "final_rank": 1,
        "overall_summary": "Strong proposal.",
        "risks": ["Schedule risk"],
        "criteria": [
            {
                "name": "Technical Capability",
                "score": 8,
                "max_score": 10,
                "weight": 30,
                "benchmark": 10,
                "gap": -2,
                "relative_percent": 80,
                "evidence": "Documented hub",
                "justification": "Meets most requirements",
            }
        ],
    }
    failed = {"status": "failed", "supplier_name": "Orbit Digital", "final_rank": None, "stage": "extraction"}
    ranked, failures = partition_suppliers([failed, scored])
    assert [item["supplier_name"] for item in ranked] == ["Apex Systems"]
    assert failures == [failed]
    assert leaderboard_rows(ranked)[0]["Rank"] == 1
    assert "Orbit Digital" not in {row["Supplier"] for row in leaderboard_rows(ranked)}
    card = scorecard_rows(scored)[0]
    assert card["Evidence"] == "Documented hub"
    assert card["Relative %"] == 80


def test_tie_break_explanation_uses_stored_order():
    scored = [
        {"supplier_name": "BrightPath Tech", "ppi": 50, "submission_date": "2026-01-01", "experience_rating": 5, "final_rank": 2},
        {"supplier_name": "Apex Systems", "ppi": 50, "submission_date": "2026-01-01", "experience_rating": 5, "final_rank": 1},
    ]
    lines = explain_ranking(scored)
    assert "higher PPI" in lines[0]
    assert "alphabetically" in lines[1]
    earlier = [
        {"supplier_name": "NexaWorks", "ppi": 70, "submission_date": "2026-04-01", "experience_rating": 3, "final_rank": 2},
        {"supplier_name": "Orbit Digital", "ppi": 90, "submission_date": "2026-05-01", "experience_rating": 1, "final_rank": 1},
    ]
    assert "PPI 90" in explain_ranking(earlier)[1]


def test_criteria_can_be_saved_inactive_but_evaluation_stays_blocked(tmp_path):
    db_path = tmp_path / "rfp.db"
    initialize_database(db_path)
    criteria = list_all_criteria(db_path)
    assert len(criteria) == 5
    assert evaluation_block_reason(criteria) is None
    updates = [
        {
            "criterion_id": item.criterion_id,
            "weight": item.weight,
            "max_score": item.max_score,
            "is_active": item.criterion_id != 5,
        }
        for item in criteria
    ]
    update_criteria(db_path, updates)
    saved = list_all_criteria(db_path)
    assert evaluation_block_reason(saved) == "Active criterion weights must total 100. Current total is 90."
    with pytest.raises(ValueError, match="Current total is 90"):
        load_active_criteria(db_path)


def test_invalid_weight_is_rejected(tmp_path):
    db_path = tmp_path / "rfp.db"
    initialize_database(db_path)
    with pytest.raises(ValueError, match="whole number"):
        update_criteria(db_path, [{"criterion_id": 1, "weight": 30.5, "max_score": 10, "is_active": True}])


def test_app_imports_when_launched_like_streamlit():
    root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env.pop("OPENAI_API_KEY", None)
    env.pop("PYTHONPATH", None)
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            "import runpy, sys; sys.path.insert(0, '.'); runpy.run_path('app.py', run_name='streamlit_check')",
        ],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr


def test_app_imports_without_an_api_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert "OPENAI_API_KEY" not in os.environ
    app = importlib.import_module("app")
    importlib.reload(app)
    assert callable(app.main)


def test_missing_criteria_message_is_explicit():
    reason = evaluation_block_reason([])
    assert reason == "At least one active criterion is required."
    inactive = Criterion(1, "Unused", "Not used", 100, 10, False)
    assert evaluation_block_reason([inactive]) == "At least one active criterion is required."
