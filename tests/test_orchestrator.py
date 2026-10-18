"""Batch orchestrator tests. The model is fake and no API key is required."""

import json

import pytest
from fpdf import FPDF

from rfp_eval.db import load_evaluation_run
from rfp_eval.orchestrator import SupplierSubmission, run_evaluation_batch
from rfp_eval.validation import MISSING_EVIDENCE


class FakeModel:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def evaluate(self, supplier_name, proposal_text, criteria):
        self.calls.append(supplier_name)
        response = self.responses[supplier_name]
        if isinstance(response, Exception):
            raise response
        return response


def _pdf(path, text="Fictional proposal text for scoring."):
    path.parent.mkdir(parents=True, exist_ok=True)
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", size=12)
    pdf.multi_cell(0, 8, text)
    pdf.output(path)
    return path


def _response(name, scores):
    return json.dumps(
        {
            "supplier_name": name,
            "criteria": [
                {
                    "criterion_id": criterion_id,
                    "score": score,
                    "max_score": 10,
                    "justification": f"{name} justification {criterion_id}",
                    "evidence": f"{name} evidence {criterion_id}",
                }
                for criterion_id, score in enumerate(scores, start=1)
            ],
            "risks": [f"{name} risk"],
            "overall_summary": f"{name} summary",
        }
    )


def _submission(tmp_path, name, filename="proposal.pdf", submitted="2026-03-01", experience=3):
    return SupplierSubmission(name, _pdf(tmp_path / filename, name), submitted, experience)


def test_successful_batch_persists_one_run_and_ranks_by_ppi(tmp_path):
    db_path = tmp_path / "rfp.db"
    apex = _submission(tmp_path, "Apex Systems", "apex.pdf", "2026-06-01", 1)
    bright = _submission(tmp_path, "BrightPath Tech", "bright.pdf", "2026-01-01", 5)
    model = FakeModel(
        {
            "Apex Systems": _response("Apex Systems", [10, 10, 10, 10, 10]),
            "BrightPath Tech": _response("BrightPath Tech", [5, 5, 5, 5, 5]),
        }
    )

    result = run_evaluation_batch(db_path, [bright, apex], model)
    stored = load_evaluation_run(db_path, result.rfp_run_id)

    assert result.status == "completed"
    assert model.calls == ["BrightPath Tech", "Apex Systems"]
    assert [row["supplier_name"] for row in stored["suppliers"]] == ["Apex Systems", "BrightPath Tech"]
    assert stored["rfp_run_id"] == result.rfp_run_id
    assert stored["suppliers"][0]["supplier_name"] == "Apex Systems"
    assert stored["suppliers"][0]["final_rank"] == 1
    assert stored["suppliers"][0]["absolute_score"] == 100
    assert stored["suppliers"][1]["final_rank"] == 2
    assert stored["suppliers"][0]["result_json"]["criteria"][0]["evidence"] == "Apex Systems evidence 1"
    assert stored["suppliers"][0]["result_json"]["risks"] == ["Apex Systems risk"]
    assert json.dumps(result.to_dict())


def test_reversed_input_keeps_the_same_ranks(tmp_path):
    def ranked_names(folder):
        model = FakeModel(
            {
                "Apex Systems": _response("Apex Systems", [10, 10, 10, 10, 10]),
                "BrightPath Tech": _response("BrightPath Tech", [5, 5, 5, 5, 5]),
            }
        )
        apex = _submission(folder, "Apex Systems", "apex.pdf", "2026-06-01", 1)
        bright = _submission(folder, "BrightPath Tech", "bright.pdf", "2026-01-01", 5)
        result = run_evaluation_batch(folder / "rfp.db", [apex, bright], model)
        return [item["supplier_name"] for item in result.suppliers], [item["final_rank"] for item in result.suppliers]

    forward = ranked_names(tmp_path / "forward")
    backward_dir = tmp_path / "backward"
    model = FakeModel(
        {
            "Apex Systems": _response("Apex Systems", [10, 10, 10, 10, 10]),
            "BrightPath Tech": _response("BrightPath Tech", [5, 5, 5, 5, 5]),
        }
    )
    apex = _submission(backward_dir, "Apex Systems", "apex.pdf", "2026-06-01", 1)
    bright = _submission(backward_dir, "BrightPath Tech", "bright.pdf", "2026-01-01", 5)
    backward = run_evaluation_batch(backward_dir / "rfp.db", [bright, apex], model)
    assert forward == (
        [item["supplier_name"] for item in backward.suppliers],
        [item["final_rank"] for item in backward.suppliers],
    )


def test_validation_warning_is_stored_and_supplier_is_still_scored(tmp_path):
    db_path = tmp_path / "rfp.db"
    apex = _submission(tmp_path, "Apex Systems", "apex.pdf")
    payload = json.loads(_response("Apex Systems", [10, 10, 10, 10, 10]))
    payload["criteria"] = [item for item in payload["criteria"] if item["criterion_id"] != 5]
    model = FakeModel({"Apex Systems": json.dumps(payload)})

    result = run_evaluation_batch(db_path, [apex], model)
    supplier = result.suppliers[0]
    assert result.status == "completed"
    assert supplier["status"] == "scored"
    assert "Missing result for Support & Experience. Score set to 0." in supplier["warnings"]
    assert supplier["criteria"][4]["evidence"] == MISSING_EVIDENCE
    assert supplier["criteria"][4]["score"] == 0


def test_extraction_failure_keeps_the_successful_supplier(tmp_path):
    db_path = tmp_path / "rfp.db"
    apex = _submission(tmp_path, "Apex Systems", "apex.pdf")
    empty = tmp_path / "empty.pdf"
    empty.write_bytes(b"")
    bright = SupplierSubmission("BrightPath Tech", empty, "2026-01-01", 4)
    model = FakeModel({"Apex Systems": _response("Apex Systems", [10, 10, 10, 10, 10])})

    result = run_evaluation_batch(db_path, [apex, bright], model)
    stored = load_evaluation_run(db_path, result.rfp_run_id)
    failed = next(row for row in stored["suppliers"] if row["supplier_name"] == "BrightPath Tech")

    assert result.status == "completed_with_failures"
    assert model.calls == ["Apex Systems"]
    assert stored["suppliers"][0]["final_rank"] == 1
    assert failed["absolute_score"] is None
    assert failed["ppi"] is None
    assert failed["final_rank"] is None
    assert failed["result_json"]["status"] == "failed"
    assert failed["result_json"]["stage"] == "extraction"


def test_api_failure_and_invalid_response_are_not_scored_as_zero(tmp_path):
    db_path = tmp_path / "api.db"
    apex = _submission(tmp_path, "Apex Systems", "apex.pdf")
    bright = _submission(tmp_path, "BrightPath Tech", "bright.pdf")
    api_model = FakeModel(
        {
            "Apex Systems": _response("Apex Systems", [8, 8, 8, 8, 8]),
            "BrightPath Tech": RuntimeError("service unavailable"),
        }
    )
    api_result = run_evaluation_batch(db_path, [apex, bright], api_model)
    api_failed = next(item for item in api_result.suppliers if item["supplier_name"] == "BrightPath Tech")
    assert api_result.status == "completed_with_failures"
    assert api_failed["stage"] == "evaluation"
    assert api_failed["absolute_score"] is None

    invalid_db = tmp_path / "invalid.db"
    invalid_model = FakeModel(
        {
            "Apex Systems": _response("Apex Systems", [8, 8, 8, 8, 8]),
            "BrightPath Tech": "this is not json",
        }
    )
    invalid_result = run_evaluation_batch(invalid_db, [apex, bright], invalid_model)
    invalid_failed = next(item for item in invalid_result.suppliers if item["supplier_name"] == "BrightPath Tech")
    assert invalid_result.status == "completed_with_failures"
    assert invalid_model.calls == ["Apex Systems", "BrightPath Tech"]
    assert invalid_failed["stage"] == "validation"
    assert invalid_failed["absolute_score"] is None
    assert invalid_failed["final_rank"] is None
    assert "raw_model_response" in invalid_failed


def test_progress_callback_reports_each_supplier_and_the_save(tmp_path):
    apex = _submission(tmp_path, "Apex Systems", "apex.pdf")
    model = FakeModel({"Apex Systems": _response("Apex Systems", [10, 10, 10, 10, 10])})
    events = []

    run_evaluation_batch(
        tmp_path / "rfp.db",
        [apex],
        model,
        on_progress=lambda message, fraction: events.append((message, fraction)),
    )

    assert events[0][0] == "Evaluating Apex Systems"
    assert events[-1] == ("Saving results", 1)


def test_two_batches_receive_different_run_ids(tmp_path):
    apex = _submission(tmp_path, "Apex Systems", "apex.pdf")
    model = FakeModel({"Apex Systems": _response("Apex Systems", [10, 10, 10, 10, 10])})
    db_path = tmp_path / "rfp.db"
    first = run_evaluation_batch(db_path, [apex], model)
    second = run_evaluation_batch(db_path, [apex], model)
    assert first.rfp_run_id != second.rfp_run_id
    assert load_evaluation_run(db_path, first.rfp_run_id)["suppliers"][0]["final_rank"] == 1
