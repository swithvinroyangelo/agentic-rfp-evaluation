"""Skeleton checks. These tests do not read an API key and do not use the network."""

import importlib

import rfp_eval
from rfp_eval import db, llm_client, orchestrator, pdf_extract, proposals, ranking, scoring, validation


def test_package_version():
    assert rfp_eval.__version__ == "0.1.0"


def test_modules_import_without_credentials(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    reloaded = importlib.reload(rfp_eval)
    assert reloaded.__version__ == "0.1.0"
    assert all(
        module is not None
        for module in (db, llm_client, orchestrator, pdf_extract, proposals, ranking, scoring, validation)
    )
