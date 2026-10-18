"""Scoring and ranking tests. No API key and no network."""

from dataclasses import replace
from datetime import date

import pytest

from rfp_eval.db import initialize_database, load_active_criteria
from rfp_eval.ranking import rank_suppliers
from rfp_eval.scoring import CriterionScore, SupplierScorecard, score_suppliers


def _criteria(tmp_path):
    db_path = tmp_path / "rfp.db"
    initialize_database(db_path)
    return load_active_criteria(db_path)


def _card(name, scores, submitted="2026-03-01", experience=3):
    return SupplierScorecard(
        supplier_name=name,
        submission_date=submitted,
        experience_rating=experience,
        scores=tuple(CriterionScore(criterion_id, score) for criterion_id, score in enumerate(scores, start=1)),
    )


def test_perfect_score_is_100_and_rank_is_assigned_after_scoring(tmp_path):
    criteria = _criteria(tmp_path)
    scored = score_suppliers(criteria, [_card("Apex Systems", [10, 10, 10, 10, 10])])
    assert scored[0].final_rank is None
    assert scored[0].absolute_score == 100
    assert scored[0].ppi == 100
    assert all(result.gap == 0 and result.relative_percent == 100 for result in scored[0].criteria)

    ranked = rank_suppliers(scored)
    assert ranked[0].final_rank == 1
    assert ranked[0].absolute_score == 100


def test_partial_weighted_score(tmp_path):
    criteria = _criteria(tmp_path)
    scored = score_suppliers(criteria, [_card("NexaWorks", [10, 5, 0, 8, 10])])
    # (10/10)*30 + (5/10)*20 + (0/10)*20 + (8/10)*20 + (10/10)*10
    assert scored[0].absolute_score == 66


def test_benchmarks_gaps_and_relative_percentages(tmp_path):
    criteria = _criteria(tmp_path)
    scored = score_suppliers(
        criteria,
        [
            _card("Apex Systems", [10, 8, 6, 10, 7]),
            _card("BrightPath Tech", [6, 10, 10, 4, 5]),
        ],
    )
    apex = {result.criterion_id: result for result in scored[0].criteria}
    bright = {result.criterion_id: result for result in scored[1].criteria}

    assert [apex[item].benchmark for item in range(1, 6)] == [10, 10, 10, 10, 7]
    assert [apex[item].gap for item in range(1, 6)] == [0, -2, -4, 0, 0]
    assert [bright[item].gap for item in range(1, 6)] == [-4, 0, 0, -6, -2]
    assert apex[2].relative_percent == pytest.approx(80)
    assert bright[5].relative_percent == pytest.approx((5 / 7) * 100)
    assert scored[0].absolute_score == pytest.approx(85)
    assert scored[1].absolute_score == pytest.approx(71)
    assert scored[0].ppi == pytest.approx(88)
    assert scored[1].ppi == pytest.approx((60 * 30 + 100 * 20 + 100 * 20 + 40 * 20 + (5 / 7 * 100) * 10) / 100)


def test_zero_benchmark_records_warning_and_uses_zero_relative_percent(tmp_path):
    criteria = _criteria(tmp_path)
    scored = score_suppliers(
        criteria,
        [
            _card("Apex Systems", [10, 10, 10, 10, 0]),
            _card("BrightPath Tech", [5, 5, 5, 5, 0]),
        ],
    )
    support = scored[0].criteria[4]
    assert support.benchmark == 0
    assert support.relative_percent == 0
    assert support.gap == 0
    assert scored[1].criteria[4].relative_percent == 0
    assert scored[0].warnings == ("Criterion Support & Experience benchmark is 0. Relative performance is 0.",)
    assert scored[0].ppi == pytest.approx(90)
    assert scored[1].ppi == pytest.approx(45)


def test_tie_breaks_and_repeated_order(tmp_path):
    criteria = _criteria(tmp_path)
    same = [8, 8, 8, 8, 8]
    ppi_leader = score_suppliers(
        criteria,
        [
            _card("BrightPath Tech", [5, 5, 5, 5, 5], submitted="2026-01-01", experience=5),
            _card("Apex Systems", [10, 10, 10, 10, 10], submitted="2026-06-01", experience=1),
        ],
    )
    assert [item.supplier_name for item in rank_suppliers(ppi_leader)] == ["Apex Systems", "BrightPath Tech"]

    earlier = score_suppliers(
        criteria,
        [
            _card("Apex Systems", same, submitted="2026-05-01", experience=3),
            _card("BrightPath Tech", same, submitted="2026-01-15", experience=3),
        ],
    )
    assert [item.supplier_name for item in rank_suppliers(earlier)] == ["BrightPath Tech", "Apex Systems"]

    experienced = score_suppliers(
        criteria,
        [
            _card("BrightPath Tech", same, submitted="2026-04-01", experience=2),
            _card("Apex Systems", same, submitted="2026-04-01", experience=5),
        ],
    )
    assert [item.supplier_name for item in rank_suppliers(experienced)] == ["Apex Systems", "BrightPath Tech"]

    named = score_suppliers(
        criteria,
        [
            _card("Orbit Digital", same, submitted=date(2026, 4, 1), experience=3),
            _card("Apex Systems", same, submitted=date(2026, 4, 1), experience=3),
            _card("NexaWorks", same, submitted=date(2026, 4, 1), experience=3),
        ],
    )
    ranked = rank_suppliers(list(reversed(named)))
    assert [item.supplier_name for item in ranked] == ["Apex Systems", "NexaWorks", "Orbit Digital"]
    assert [item.final_rank for item in ranked] == [1, 2, 3]
    assert [item.final_rank for item in rank_suppliers(named)] == [1, 2, 3]


def test_invalid_scores_and_criteria_are_rejected(tmp_path):
    criteria = _criteria(tmp_path)
    with pytest.raises(ValueError, match="Missing scores"):
        score_suppliers(criteria, [_card("Apex Systems", [10, 10, 10, 10])])
    with pytest.raises(ValueError, match="Duplicate score"):
        score_suppliers(
            criteria,
            [
                SupplierScorecard(
                    "Apex Systems",
                    "2026-03-01",
                    3,
                    tuple(CriterionScore(1, 10) for _ in range(2))
                    + tuple(CriterionScore(criterion_id, 10) for criterion_id in range(2, 6)),
                )
            ],
        )
    with pytest.raises(ValueError, match="Duplicate criteria"):
        score_suppliers(criteria + criteria[:1], [_card("Apex Systems", [10, 10, 10, 10, 10])])
    with pytest.raises(ValueError, match="must total 100"):
        overweight = [replace(criteria[0], weight=criteria[0].weight + 1), *criteria[1:]]
        score_suppliers(overweight, [_card("Apex Systems", [10, 10, 10, 10, 10])])
    with pytest.raises(ValueError, match="non-finite"):
        score_suppliers(criteria, [_card("Apex Systems", [10, 10, 10, 10, float("nan")])])
    with pytest.raises(ValueError, match="non-finite"):
        score_suppliers(
            [replace(criteria[0], max_score=float("nan")), *criteria[1:]],
            [_card("Apex Systems", [10, 10, 10, 10, 10])],
        )
    with pytest.raises(ValueError, match="positive maximum score"):
        score_suppliers(
            [replace(criteria[0], max_score=0), *criteria[1:]],
            [_card("Apex Systems", [10, 10, 10, 10, 10])],
        )
    with pytest.raises(ValueError, match="must be from 0"):
        score_suppliers(criteria, [_card("Apex Systems", [10, 10, 11, 10, 10])])
    with pytest.raises(ValueError, match="Submission date"):
        score_suppliers(criteria, [_card("Apex Systems", [10, 10, 10, 10, 10], submitted="15/01/2026")])
    with pytest.raises(ValueError, match="experience rating"):
        score_suppliers(criteria, [_card("Apex Systems", [10, 10, 10, 10, 10], experience=0)])
    with pytest.raises(ValueError, match="unique"):
        score_suppliers(
            criteria,
            [
                _card("Apex Systems", [10, 10, 10, 10, 10]),
                _card("Apex Systems", [8, 8, 8, 8, 8]),
            ],
        )
