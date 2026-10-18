"""SQLite schema and seed tests. No API key and no network."""

import sqlite3

import pytest

from rfp_eval.db import (
    SEED_CRITERIA,
    Criterion,
    connect,
    initialize_database,
    load_active_criteria,
    validate_active_criteria,
)

EXPECTED_COLUMNS = {
    "evaluation_criteria": {
        "criterion_id",
        "name",
        "description",
        "weight",
        "max_score",
        "is_active",
    },
    "rfp_runs": {"rfp_run_id", "created_at", "status"},
    "supplier_results": {
        "rfp_run_id",
        "supplier_name",
        "submission_date",
        "experience_rating",
        "absolute_score",
        "ppi",
        "final_rank",
        "result_json",
    },
}


def test_schema_creates_required_tables(tmp_path):
    db_path = tmp_path / "rfp.db"
    initialize_database(db_path)

    connection = connect(db_path)
    try:
        foreign_keys = connection.execute("PRAGMA foreign_keys").fetchone()[0]
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        assert {"evaluation_criteria", "rfp_runs", "supplier_results"} <= tables
        for table, expected in EXPECTED_COLUMNS.items():
            columns = {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}
            assert expected <= columns
    finally:
        connection.close()
    assert foreign_keys == 1


def test_seed_inserts_five_active_criteria_totaling_100(tmp_path):
    db_path = tmp_path / "rfp.db"
    initialize_database(db_path)

    criteria = load_active_criteria(db_path)
    assert [(item.criterion_id, item.name, item.weight, item.max_score) for item in criteria] == [
        (row["criterion_id"], row["name"], row["weight"], row["max_score"]) for row in SEED_CRITERIA
    ]
    assert all(item.is_active and item.description for item in criteria)
    assert sum(item.weight for item in criteria) == 100


def test_repeated_initialization_does_not_duplicate_seed(tmp_path):
    db_path = tmp_path / "rfp.db"
    initialize_database(db_path)
    initialize_database(db_path)

    connection = sqlite3.connect(db_path)
    try:
        count = connection.execute("SELECT COUNT(*) FROM evaluation_criteria").fetchone()[0]
        ids = [row[0] for row in connection.execute("SELECT criterion_id FROM evaluation_criteria ORDER BY criterion_id")]
    finally:
        connection.close()
    assert count == 5
    assert ids == [1, 2, 3, 4, 5]


def test_inactive_criterion_is_excluded_and_active_total_stays_100(tmp_path):
    db_path = tmp_path / "nested" / "rfp.db"
    initialize_database(db_path)

    connection = sqlite3.connect(db_path)
    try:
        connection.execute(
            """
            INSERT INTO evaluation_criteria (
                criterion_id, name, description, weight, max_score, is_active
            ) VALUES (6, 'Optional Extra', 'Not used in this run.', 15, 10, 0)
            """
        )
        connection.commit()
    finally:
        connection.close()

    criteria = load_active_criteria(db_path)
    assert [item.name for item in criteria] == [row["name"] for row in SEED_CRITERIA]
    assert sum(item.weight for item in criteria) == 100


def test_validate_rejects_weights_that_do_not_total_100():
    criteria = [
        Criterion(1, "Technical Capability", "Design.", 40, 10, True),
        Criterion(2, "Implementation Plan", "Plan.", 20, 10, True),
        Criterion(3, "Commercial Value", "Price.", 20, 10, True),
        Criterion(4, "Security & Compliance", "Security.", 20, 10, True),
        Criterion(5, "Support & Experience", "Support.", 10, 10, True),
    ]
    with pytest.raises(ValueError, match="must total 100"):
        validate_active_criteria(criteria)


def test_validate_rejects_non_positive_max_score_and_weight():
    with pytest.raises(ValueError, match="positive maximum score"):
        validate_active_criteria([Criterion(1, "Technical Capability", "Design.", 100, 0, True)])
    with pytest.raises(ValueError, match="invalid weight"):
        validate_active_criteria([Criterion(1, "Technical Capability", "Design.", 0, 10, True)])
