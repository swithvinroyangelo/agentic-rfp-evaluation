"""The committed sample export is synthetic and comes from the real pipeline."""

import json
from pathlib import Path

from rfp_eval.db import load_evaluation_run
from rfp_eval.sample_export import SYNTHETIC_NOTICE, build_synthetic_export

ROOT = Path(__file__).resolve().parents[1]
SAMPLE_JSON = ROOT / "sample_output" / "synthetic_rfp_run.json"


def _comparable(payload: dict) -> list[dict]:
    rows = []
    for supplier in payload["suppliers"]:
        body = supplier["result_json"]
        rows.append(
            {
                "supplier_name": supplier["supplier_name"],
                "submission_date": supplier["submission_date"],
                "experience_rating": supplier["experience_rating"],
                "absolute_score": supplier["absolute_score"],
                "ppi": supplier["ppi"],
                "final_rank": supplier["final_rank"],
                "status": body["status"],
                "risks": body["risks"],
                "overall_summary": body["overall_summary"],
                "warnings": body["warnings"],
                "criteria": body["criteria"],
            }
        )
    return rows


def test_synthetic_export_reopens_with_scores_evidence_and_ranks(tmp_path):
    db_path = tmp_path / "synthetic.db"
    payload = build_synthetic_export(db_path, ROOT / "sample_proposals")
    reopened = load_evaluation_run(db_path, payload["rfp_run_id"])

    assert payload["notice"] == SYNTHETIC_NOTICE
    assert payload["status"] == "completed"
    assert reopened["rfp_run_id"] == payload["rfp_run_id"]
    assert reopened["created_at"] == payload["created_at"]
    assert [row["final_rank"] for row in payload["suppliers"]] == [1, 2, 3, 4]
    for supplier in payload["suppliers"]:
        body = supplier["result_json"]
        assert body["status"] == "scored"
        assert body["final_rank"] is not None
        assert body["absolute_score"] is not None
        assert body["ppi"] is not None
        assert body["risks"]
        assert body["overall_summary"]
        assert "warnings" in body
        assert len(body["criteria"]) == 5
        for criterion in body["criteria"]:
            assert {"score", "max_score", "weight", "benchmark", "gap", "relative_percent", "evidence", "justification"} <= set(criterion)
            assert "Synthetic test evidence" in criterion["evidence"]
            assert "Not a live model citation." in criterion["evidence"]


def test_committed_sample_matches_a_fresh_offline_run(tmp_path):
    fresh = build_synthetic_export(tmp_path / "fresh.db", ROOT / "sample_proposals")
    committed = json.loads(SAMPLE_JSON.read_text(encoding="utf-8"))
    assert committed["notice"].startswith("SYNTHETIC TEST DATA")
    assert committed["status"] == "completed"
    assert _comparable(committed) == _comparable(fresh)
