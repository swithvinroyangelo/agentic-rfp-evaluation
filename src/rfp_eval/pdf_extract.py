"""Extract text from supplier proposal PDFs."""

from __future__ import annotations

from pathlib import Path

from pypdf import PdfReader


class PdfExtractionError(ValueError):
    """The file cannot be used as a proposal with extractable text."""


def extract_pdf_text(path: Path | str) -> str:
    """Return the text of a PDF. Empty and image-only files raise PdfExtractionError."""
    reader = _open_reader(path)
    try:
        chunks = [(page.extract_text() or "") for page in reader.pages]
    except PdfExtractionError:
        raise
    except Exception as error:
        raise PdfExtractionError(f"PDF is unreadable: {Path(path).name}") from error
    text = "\n".join(chunks).strip()
    if not text:
        raise PdfExtractionError(
            f"PDF has no extractable text. It may be image-only: {Path(path).name}"
        )
    return text


def pdf_page_count(path: Path | str) -> int:
    reader = _open_reader(path)
    count = len(reader.pages)
    if count == 0:
        raise PdfExtractionError(f"PDF has no pages: {Path(path).name}")
    return count


def _open_reader(path: Path | str) -> PdfReader:
    file_path = Path(path)
    if not file_path.is_file():
        raise PdfExtractionError(f"PDF not found: {file_path}")
    if file_path.stat().st_size == 0:
        raise PdfExtractionError(f"PDF is empty: {file_path.name}")
    try:
        reader = PdfReader(str(file_path))
    except Exception as error:
        raise PdfExtractionError(f"PDF is unreadable: {file_path.name}") from error
    if reader.is_encrypted:
        raise PdfExtractionError(f"PDF is encrypted and cannot be read: {file_path.name}")
    if len(reader.pages) == 0:
        raise PdfExtractionError(f"PDF has no pages: {file_path.name}")
    return reader
