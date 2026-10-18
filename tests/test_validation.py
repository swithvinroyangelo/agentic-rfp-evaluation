"""LLM JSON normalization tests. No API key and no network."""

import pytest

from rfp_eval.db import initialize_database, load_active_criteria
from rfp_eval.scoring import score_suppliers
from rfp_eval.validation import MISSING_EVIDENCE, MISSING_JUSTIFICATION, normalize_evaluation


def _criteria(tmp_path):
    initialize_database(tmp_path / "rfp.db")
    return load_active_criteria(tmp_path / "rfp.db")


def _criterion(criterion_id, score=8, max_score=10, justification="Supported by the proposal.", evidence="Page 1 quote."):
    return {
        "criterion_id": criterion_id,
        "score": score,
        "max_score": max_score,
        "justification": justification,
        "evidence": evidence,
    }


def _payload(criteria_rows, supplier="Apex Systems"):
    return {
        "supplier_name": supplier,
        "criteria": criteria_rows,
        "risks": ["Timeline depends on site access."],
        "overall_summary": "A complete proposal with cited evidence.",
    }


def test_valid_json_preserves_text_and_scores_for_the_ranker(tmp_path):
    criteria = _criteria(tmp_path)
    payload = _payload([_criterion(item.criterion_id, score=10) for item in criteria])
    normalized = normalize_evaluation(payload, "Apex Systems", criteria)

    assert normalized.warnings == ()
    assert normalized.overall_summary == payload["overall_summary"]
    assert normalized.risks == ("Timeline depends on site access.",)
    assert [item.score for item in normalized.criteria] == [10, 10, 10, 10, 10]
    assert normalized.criteria[0].evidence == "Page 1 quote."
    assert normalized.criteria[0].justification == "Supported by the proposal."
    assert normalized.criteria[0].max_score == 10

    scored = score_suppliers(criteria, [normalized.to_scorecard("2026-03-01", 4)])
    assert scored[0].absolute_score == 100
    assert scored[0].final_rank is None


def test_json_string_and_malformed_json(tmp_path):
    criteria = _criteria(tmp_path)
    raw = (
        '{"supplier_name":"Apex Systems","criteria":['
        + ",".join(
            '{"criterion_id":%s,"score":9,"max_score":10,"justification":"Cited.","evidence":"Quoted."}'
            % item.criterion_id
            for item in criteria
        )
        + '],"risks":[],"overall_summary":"Summary."}'
    )
    normalized = normalize_evaluation(raw, "Apex Systems", criteria)
    assert [item.score for item in normalized.criteria] == [9, 9, 9, 9, 9]

    with pytest.raises(ValueError, match="not valid JSON"):
        normalize_evaluation("{not json", "Apex Systems", criteria)
    with pytest.raises(ValueError, match="JSON object"):
        normalize_evaluation("[1, 2]", "Apex Systems", criteria)


def test_missing_duplicate_and_unknown_criteria(tmp_path):
    criteria = _criteria(tmp_path)
    rows = [_criterion(item.criterion_id, score=6) for item in criteria if item.criterion_id != 3]
    rows.append(_criterion(1, score=9, justification="Later duplicate.", evidence="Should be ignored."))
    rows.append(_criterion(99, score=4, justification="Unknown.", evidence="Unknown evidence."))
    normalized = normalize_evaluation(_payload(rows), "Apex Systems", criteria)

    by_id = {item.criterion_id: item for item in normalized.criteria}
    assert [item.criterion_id for item in normalized.criteria] == [1, 2, 3, 4, 5]
    assert by_id[1].score == 6
    assert by_id[1].justification == "Supported by the proposal."
    assert by_id[3].score == 0
    assert by_id[3].justification == MISSING_JUSTIFICATION
    assert by_id[3].evidence == MISSING_EVIDENCE
    assert "Ignored duplicate criterion id 1. Kept the first result." in normalized.warnings
    assert "Ignored unknown criterion id 99." in normalized.warnings
    assert "Missing result for Commercial Value. Score set to 0." in normalized.warnings
    assert all(item.criterion_id != 99 for item in normalized.criteria)


def test_out_of_range_scores_are_clipped_and_max_score_comes_from_configuration(tmp_path):
    criteria = _criteria(tmp_path)
    rows = []
    for item in criteria:
        score = 10
        max_score = 10
        if item.criterion_id == 1:
            score = -2
        elif item.criterion_id == 2:
            score = 15
        elif item.criterion_id == 3:
            max_score = 5
            score = 8
        rows.append(_criterion(item.criterion_id, score=score, max_score=max_score))
    normalized = normalize_evaluation(_payload(rows), "Apex Systems", criteria)
    by_id = {item.criterion_id: item for item in normalized.criteria}

    assert by_id[1].score == 0
    assert by_id[2].score == 10
    assert by_id[3].score == 8
    assert by_id[3].max_score == 10
    assert "Score for Technical Capability was -2.0 and was clipped to 0." in normalized.warnings
    assert "Score for Implementation Plan was 15.0 and was clipped to 10." in normalized.warnings
    assert "Model max_score for Commercial Value was 5.0 and was replaced with the configured maximum 10." in normalized.warnings
    assert by_id[3].evidence == "Page 1 quote."


def test_non_finite_scores_wrong_name_and_invalid_types_are_rejected(tmp_path):
    criteria = _criteria(tmp_path)
    valid_rows = [_criterion(item.criterion_id) for item in criteria]

    nan_rows = [_criterion(item.criterion_id) for item in criteria]
    nan_rows[0] = _criterion(1, score=float("nan"))
    with pytest.raises(ValueError, match="finite"):
        normalize_evaluation(_payload(nan_rows), "Apex Systems", criteria)

    inf_rows = [_criterion(item.criterion_id) for item in criteria]
    inf_rows[0] = _criterion(1, score=float("inf"))
    with pytest.raises(ValueError, match="finite"):
        normalize_evaluation(_payload(inf_rows), "Apex Systems", criteria)

    with pytest.raises(ValueError, match="does not match"):
        normalize_evaluation(_payload(valid_rows, supplier="BrightPath Tech"), "Apex Systems", criteria)

    bad_score = [_criterion(item.criterion_id) for item in criteria]
    bad_score[0]["score"] = "eight"
    with pytest.raises(ValueError, match="score"):
        normalize_evaluation(_payload(bad_score), "Apex Systems", criteria)

    bad_justification = [_criterion(item.criterion_id) for item in criteria]
    bad_justification[0]["justification"] = 12
    with pytest.raises(ValueError, match="justification"):
        normalize_evaluation(_payload(bad_justification), "Apex Systems", criteria)

    payload = _payload(valid_rows)
    payload["risks"] = "none"
    with pytest.raises(ValueError, match="risks"):
        normalize_evaluation(payload, "Apex Systems", criteria)

    payload = _payload(valid_rows)
    payload["overall_summary"] = 5
    with pytest.raises(ValueError, match="overall_summary"):
        normalize_evaluation(payload, "Apex Systems", criteria)

    payload = _payload(valid_rows)
    del payload["criteria"]
    with pytest.raises(ValueError, match="criteria"):
        normalize_evaluation(payload, "Apex Systems", criteria)
