"""SQLite schema, seed data, and active-criteria checks."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path

REQUIRED_ACTIVE_WEIGHT = 100

_SCHEMA = (
    """
    CREATE TABLE IF NOT EXISTS evaluation_criteria (
        criterion_id INTEGER PRIMARY KEY,
        name TEXT NOT NULL UNIQUE,
        description TEXT NOT NULL,
        weight INTEGER NOT NULL CHECK (weight > 0 AND weight <= 100),
        max_score INTEGER NOT NULL CHECK (max_score > 0),
        is_active INTEGER NOT NULL CHECK (is_active IN (0, 1))
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS rfp_runs (
        rfp_run_id TEXT PRIMARY KEY,
        created_at TEXT NOT NULL,
        status TEXT NOT NULL CHECK (length(status) > 0)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS supplier_results (
        rfp_run_id TEXT NOT NULL,
        supplier_name TEXT NOT NULL,
        submission_date TEXT NOT NULL,
        experience_rating INTEGER NOT NULL CHECK (experience_rating BETWEEN 1 AND 5),
        absolute_score REAL,
        ppi REAL,
        final_rank INTEGER CHECK (final_rank IS NULL OR final_rank >= 1),
        result_json TEXT NOT NULL CHECK (json_valid(result_json)),
        PRIMARY KEY (rfp_run_id, supplier_name),
        FOREIGN KEY (rfp_run_id) REFERENCES rfp_runs (rfp_run_id)
    )
    """,
)

# Seeded only when evaluation_criteria has no rows. Weights total 100.
SEED_CRITERIA = (
    {
        "criterion_id": 1,
        "name": "Technical Capability",
        "description": "Architecture, integrations, scalability, and technical fit.",
        "weight": 30,
        "max_score": 10,
        "is_active": 1,
    },
    {
        "criterion_id": 2,
        "name": "Implementation Plan",
        "description": "Timeline, milestones, staffing, and risk plan.",
        "weight": 20,
        "max_score": 10,
        "is_active": 1,
    },
    {
        "criterion_id": 3,
        "name": "Commercial Value",
        "description": "Pricing clarity, total cost, and assumptions.",
        "weight": 20,
        "max_score": 10,
        "is_active": 1,
    },
    {
        "criterion_id": 4,
        "name": "Security & Compliance",
        "description": "Controls, certifications, privacy, and auditability.",
        "weight": 20,
        "max_score": 10,
        "is_active": 1,
    },
    {
        "criterion_id": 5,
        "name": "Support & Experience",
        "description": "Support model, similar projects, and references.",
        "weight": 10,
        "max_score": 10,
        "is_active": 1,
    },
)


@dataclass(frozen=True)
class Criterion:
    criterion_id: int
    name: str
    description: str
    weight: int
    max_score: int
    is_active: bool


def connect(db_path: Path | str) -> sqlite3.Connection:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def initialize_database(db_path: Path | str) -> None:
    """Create tables and seed criteria once. Repeated calls do not insert again."""
    connection = connect(db_path)
    try:
        connection.execute("BEGIN")
        for statement in _SCHEMA:
            connection.execute(statement)
        existing = connection.execute("SELECT COUNT(*) AS count FROM evaluation_criteria").fetchone()
        if existing["count"] == 0:
            connection.executemany(
                """
                INSERT INTO evaluation_criteria (
                    criterion_id, name, description, weight, max_score, is_active
                ) VALUES (
                    :criterion_id, :name, :description, :weight, :max_score, :is_active
                )
                """,
                SEED_CRITERIA,
            )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def load_active_criteria(db_path: Path | str) -> list[Criterion]:
    """Return active criteria ordered by id. Raises if their weights do not total 100."""
    connection = connect(db_path)
    try:
        rows = connection.execute(
            """
            SELECT criterion_id, name, description, weight, max_score, is_active
            FROM evaluation_criteria
            WHERE is_active = 1
            ORDER BY criterion_id
            """
        ).fetchall()
    finally:
        connection.close()
    criteria = [_row_to_criterion(row) for row in rows]
    validate_active_criteria(criteria)
    return criteria


def list_all_criteria(db_path: Path | str) -> list[Criterion]:
    """Return every criterion, including inactive rows, ordered by id."""
    connection = connect(db_path)
    try:
        rows = connection.execute(
            """
            SELECT criterion_id, name, description, weight, max_score, is_active
            FROM evaluation_criteria
            ORDER BY criterion_id
            """
        ).fetchall()
    finally:
        connection.close()
    return [_row_to_criterion(row) for row in rows]


def update_criteria(db_path: Path | str, updates: list[dict]) -> None:
    """Save weight, maximum score, and active flag. Does not require the total to be 100."""
    if not updates:
        raise ValueError("At least one criterion update is required.")
    connection = connect(db_path)
    try:
        connection.execute("BEGIN")
        for update in updates:
            criterion_id = update["criterion_id"]
            weight = _whole_number(update["weight"], "Weight")
            max_score = _whole_number(update["max_score"], "Maximum score")
            if weight <= 0 or weight > 100:
                raise ValueError(f"Weight must be from 1 to 100. Received {weight}.")
            if max_score <= 0:
                raise ValueError(f"Maximum score must be positive. Received {max_score}.")
            is_active = 1 if update["is_active"] else 0
            found = connection.execute(
                "SELECT 1 FROM evaluation_criteria WHERE criterion_id = ?",
                (criterion_id,),
            ).fetchone()
            if found is None:
                raise ValueError(f"Criterion {criterion_id} was not found.")
            connection.execute(
                """
                UPDATE evaluation_criteria
                SET weight = ?, max_score = ?, is_active = ?
                WHERE criterion_id = ?
                """,
                (weight, max_score, is_active, criterion_id),
            )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def delete_evaluation_runs(db_path: Path | str) -> int:
    """Delete every saved run and its supplier rows. Criteria are left in place."""
    connection = connect(db_path)
    try:
        connection.execute("BEGIN")
        connection.execute("DELETE FROM supplier_results")
        deleted = connection.execute("DELETE FROM rfp_runs").rowcount
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
    return int(deleted)


def list_evaluation_runs(db_path: Path | str) -> list[dict]:
    connection = connect(db_path)
    try:
        rows = connection.execute(
            """
            SELECT rfp_run_id, created_at, status
            FROM rfp_runs
            ORDER BY created_at DESC, rfp_run_id
            """
        ).fetchall()
    finally:
        connection.close()
    return [
        {"rfp_run_id": row["rfp_run_id"], "created_at": row["created_at"], "status": row["status"]}
        for row in rows
    ]


def validate_active_criteria(criteria: list[Criterion]) -> None:
    """Require positive max scores, weights from 1 to 100, and a total of exactly 100."""
    if not criteria:
        raise ValueError("At least one active criterion is required.")
    for criterion in criteria:
        if criterion.weight <= 0 or criterion.weight > 100:
            raise ValueError(f"Criterion {criterion.name} has an invalid weight: {criterion.weight}.")
        if criterion.max_score <= 0:
            raise ValueError(f"Criterion {criterion.name} must have a positive maximum score.")
    total = sum(criterion.weight for criterion in criteria)
    if total != REQUIRED_ACTIVE_WEIGHT:
        raise ValueError(f"Active criterion weights must total 100. Current total is {total}.")


def save_evaluation_run(
    db_path: Path | str,
    run_id: str,
    created_at: str,
    status: str,
    suppliers: list[dict],
) -> None:
    """Insert one run and its supplier rows. Rolls back the whole write on failure."""
    if not run_id.strip():
        raise ValueError("RFP_RUN_ID is required.")
    if not status.strip():
        raise ValueError("Run status is required.")
    connection = connect(db_path)
    try:
        connection.execute("BEGIN")
        connection.execute(
            "INSERT INTO rfp_runs (rfp_run_id, created_at, status) VALUES (?, ?, ?)",
            (run_id, created_at, status),
        )
        connection.executemany(
            """
            INSERT INTO supplier_results (
                rfp_run_id, supplier_name, submission_date, experience_rating,
                absolute_score, ppi, final_rank, result_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    run_id,
                    supplier["supplier_name"],
                    supplier["submission_date"],
                    supplier["experience_rating"],
                    supplier.get("absolute_score"),
                    supplier.get("ppi"),
                    supplier.get("final_rank"),
                    json.dumps(supplier["result_json"]),
                )
                for supplier in suppliers
            ],
        )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def load_evaluation_run(db_path: Path | str, run_id: str) -> dict:
    connection = connect(db_path)
    try:
        run = connection.execute(
            "SELECT rfp_run_id, created_at, status FROM rfp_runs WHERE rfp_run_id = ?",
            (run_id,),
        ).fetchone()
        if run is None:
            raise ValueError(f"RFP run {run_id} was not found.")
        rows = connection.execute(
            """
            SELECT supplier_name, submission_date, experience_rating,
                   absolute_score, ppi, final_rank, result_json
            FROM supplier_results
            WHERE rfp_run_id = ?
            ORDER BY final_rank IS NULL, final_rank, supplier_name
            """,
            (run_id,),
        ).fetchall()
    finally:
        connection.close()
    return {
        "rfp_run_id": run["rfp_run_id"],
        "created_at": run["created_at"],
        "status": run["status"],
        "suppliers": [
            {
                "supplier_name": row["supplier_name"],
                "submission_date": row["submission_date"],
                "experience_rating": row["experience_rating"],
                "absolute_score": row["absolute_score"],
                "ppi": row["ppi"],
                "final_rank": row["final_rank"],
                "result_json": json.loads(row["result_json"]),
            }
            for row in rows
        ],
    }


def _whole_number(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be a whole number.")
    if not float(value).is_integer():
        raise ValueError(f"{label} must be a whole number.")
    return int(value)


def _row_to_criterion(row: sqlite3.Row) -> Criterion:
    return Criterion(
        criterion_id=row["criterion_id"],
        name=row["name"],
        description=row["description"],
        weight=row["weight"],
        max_score=row["max_score"],
        is_active=bool(row["is_active"]),
    )
