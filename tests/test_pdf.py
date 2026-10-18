"""PDF generation and extraction tests. No API key and no network."""

from pathlib import Path

import pytest
from fpdf import FPDF

from rfp_eval.pdf_extract import PdfExtractionError, extract_pdf_text, pdf_page_count
from rfp_eval.proposals import (
    PROPOSAL_FILENAMES,
    REQUIRED_SECTIONS,
    generate_sample_proposals,
)

ROOT = Path(__file__).resolve().parents[1]
SAMPLE_DIR = ROOT / "sample_proposals"


def test_sample_proposals_exist_and_match_the_brief():
    assert [path.name for path in generate_sample_proposals(SAMPLE_DIR)] == list(PROPOSAL_FILENAMES)
    for filename in PROPOSAL_FILENAMES:
        path = SAMPLE_DIR / filename
        assert path.is_file()
        text = extract_pdf_text(path)
        pages = pdf_page_count(path)
        assert 2 <= pages <= 4
        for heading in REQUIRED_SECTIONS:
            assert heading in text
        assert "Fictional classroom proposal" in text
        assert "No real certification is claimed." in text


def test_supplier_differences_are_present_in_extracted_text():
    texts = {name: extract_pdf_text(SAMPLE_DIR / name) for name in PROPOSAL_FILENAMES}
    apex = texts["apex_systems.pdf"]
    bright = texts["brightpath_tech.pdf"]
    nexa = texts["nexaworks.pdf"]
    orbit = texts["orbit_digital.pdf"]

    assert "Apex technical design uses a documented integration hub." in apex
    assert "Apex fixed price is 480000 fictional units." in apex
    assert "Apex delivery schedule is a moderate 16 weeks." in apex
    assert "Apex security controls are described in detail." in apex

    assert "BrightPath fixed price is 190000 fictional units." in bright
    assert "BrightPath timeline is a fast 8 weeks." in bright
    assert "BrightPath compliance detail is limited." in bright
    assert "BrightPath relevant experience is limited." in bright

    assert "NexaWorks implementation plan is the most detailed." in nexa
    assert "NexaWorks support model has a named escalation path." in nexa
    assert "NexaWorks balanced price is 320000 fictional units." in nexa

    assert "Orbit integration plan stays vague pending discovery." in orbit
    assert "Orbit medium price is 340000 fictional units." in orbit
    assert "Orbit cites three fictional references." in orbit


def test_generation_is_repeatable(tmp_path):
    first = tmp_path / "first"
    second = tmp_path / "second"
    generate_sample_proposals(first)
    generate_sample_proposals(second)
    for filename in PROPOSAL_FILENAMES:
        assert (first / filename).read_bytes() == (second / filename).read_bytes()


def test_empty_invalid_and_image_only_pdfs_are_rejected(tmp_path):
    empty = tmp_path / "empty.pdf"
    empty.write_bytes(b"")
    with pytest.raises(PdfExtractionError, match="empty"):
        extract_pdf_text(empty)

    invalid = tmp_path / "notes.pdf"
    invalid.write_bytes(b"this is not a pdf")
    with pytest.raises(PdfExtractionError, match="unreadable"):
        extract_pdf_text(invalid)

    image_only = tmp_path / "scan.pdf"
    pdf = FPDF()
    pdf.add_page()
    pdf.set_fill_color(180, 180, 180)
    pdf.rect(20, 20, 80, 40, "F")
    pdf.output(image_only)
    with pytest.raises(PdfExtractionError, match="image-only"):
        extract_pdf_text(image_only)

    missing = tmp_path / "missing.pdf"
    with pytest.raises(PdfExtractionError, match="not found"):
        extract_pdf_text(missing)
