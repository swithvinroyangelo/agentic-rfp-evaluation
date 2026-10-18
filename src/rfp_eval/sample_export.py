"""Offline sample export. The model is fake and no API key is used."""

from __future__ import annotations

import json
from pathlib import Path

from rfp_eval.db import list_evaluation_runs, load_evaluation_run
from rfp_eval.orchestrator import SupplierSubmission, run_evaluation_batch

SYNTHETIC_NOTICE = (
    "SYNTHETIC TEST DATA. This export was produced offline with a fake model. "
    "It is not a live OpenAI evaluation and it contains no real supplier information."
)

_PROFILES = (
    ("Apex Systems", "apex_systems.pdf", "2026-02-10", 4, [9, 7, 5, 9, 7]),
    ("BrightPath Tech", "brightpath_tech.pdf", "2026-01-20", 2, [6, 8, 9, 3, 4]),
    ("NexaWorks", "nexaworks.pdf", "2026-02-01", 4, [8, 10, 7, 7, 9]),
    ("Orbit Digital", "orbit_digital.pdf", "2026-01-15", 5, [5, 4, 6, 6, 9]),
)


class FakeModel:
    """Returns fixed JSON. It does not read proposal text and does not call a network."""

    def __init__(self) -> None:
        self.responses = {name: _response(name, scores) for name, _, _, _, scores in _PROFILES}

    def evaluate(self, supplier_name: str, proposal_text: str, criteria) -> str:
        return self.responses[supplier_name]


def build_synthetic_export(db_path: Path | str, proposal_dir: Path | str) -> dict:
    """Run the four sample PDFs through the real pipeline and return one saved run."""
    proposals = Path(proposal_dir)
    submissions = [
        SupplierSubmission(
            supplier_name=name,
            pdf_path=proposals / filename,
            submission_date=submitted,
            experience_rating=experience,
        )
        for name, filename, submitted, experience, _scores in _PROFILES
    ]
    result = run_evaluation_batch(db_path, submissions, FakeModel())
    stored = load_evaluation_run(db_path, result.rfp_run_id)
    runs = list_evaluation_runs(db_path)
    if not any(run["rfp_run_id"] == stored["rfp_run_id"] for run in runs):
        raise RuntimeError("The synthetic run was saved but could not be listed.")
    return {"notice": SYNTHETIC_NOTICE, **stored}


def _response(name: str, scores: list[int]) -> str:
    return json.dumps(
        {
            "supplier_name": name,
            "criteria": [
                {
                    "criterion_id": criterion_id,
                    "score": score,
                    "max_score": 10,
                    "justification": (
                        f"Synthetic test justification for {name}, criterion {criterion_id}."
                    ),
                    "evidence": (
                        f"Synthetic test evidence for {name}, criterion {criterion_id}. "
                        "Not a live model citation."
                    ),
                }
                for criterion_id, score in enumerate(scores, start=1)
            ],
            "risks": [f"Synthetic test risk for {name}. Not a live model finding."],
            "overall_summary": f"Synthetic test summary for {name}. Produced by the offline fake model.",
        }
    )
