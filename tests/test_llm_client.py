"""OpenAI client tests. These tests do not call the live API."""

import pytest

from rfp_eval.db import Criterion
from rfp_eval.llm_client import (
    OpenAIEvaluationClient,
    build_evaluation_messages,
    load_project_env,
    read_setting,
)


def _criteria():
    return [
        Criterion(1, "Technical Capability", "Architecture and integrations.", 30, 10, True),
    ]


def test_messages_request_json_and_include_the_proposal():
    messages = build_evaluation_messages("Apex Systems", "Untrusted proposal text", _criteria())
    combined = "\n".join(message["content"] for message in messages)
    assert "JSON" in combined
    assert "Apex Systems" in combined
    assert "Technical Capability" in combined
    assert "Untrusted proposal text" in combined
    assert "<<<PROPOSAL>>>" in combined
    assert "PPI" in combined


def test_environment_overrides_secrets(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "from-env")
    monkeypatch.setenv("OPENAI_MODEL", "env-model")
    client = OpenAIEvaluationClient(
        secrets={"OPENAI_API_KEY": "from-secrets", "OPENAI_MODEL": "secret-model"},
        client_factory=lambda api_key: None,
    )
    assert client.api_key == "from-env"
    assert client.model == "env-model"


def test_secrets_are_used_when_environment_is_empty(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    assert read_setting("OPENAI_API_KEY", secrets={"OPENAI_API_KEY": "from-secrets"}) == "from-secrets"
    client = OpenAIEvaluationClient(
        secrets={"OPENAI_API_KEY": "from-secrets", "OPENAI_MODEL": "secret-model"},
        client_factory=lambda api_key: None,
    )
    assert client.api_key == "from-secrets"
    assert client.model == "secret-model"


def test_env_file_fills_blank_settings_and_does_not_override(monkeypatch, tmp_path):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_MODEL", "already-set")
    env_file = tmp_path / ".env"
    env_file.write_text(
        '# local only\nexport OPENAI_API_KEY="file-key"\nOPENAI_MODEL=file-model\n\n',
        encoding="utf-8",
    )
    load_project_env(env_file)
    assert read_setting("OPENAI_API_KEY", secrets={}) == "file-key"
    assert read_setting("OPENAI_MODEL", secrets={"OPENAI_MODEL": "from-secrets"}) == "already-set"


def test_missing_api_key_raises_before_any_call(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        OpenAIEvaluationClient(secrets={}, client_factory=lambda api_key: None)


def test_evaluate_uses_json_mode_without_calling_openai():
    captured = {}

    class _Completions:
        def create(self, **kwargs):
            captured.update(kwargs)

            class _Message:
                content = '{"supplier_name": "Apex Systems"}'

            class _Choice:
                message = _Message()

            class _Response:
                choices = [_Choice()]

            return _Response()

    class _Chat:
        completions = _Completions()

    class _Client:
        chat = _Chat()

    client = OpenAIEvaluationClient(
        api_key="test-key",
        model="gpt-test",
        client_factory=lambda api_key: _Client(),
    )
    raw = client.evaluate("Apex Systems", "UNIQUE-BODY-77", _criteria())
    assert raw.startswith("{")
    assert captured["model"] == "gpt-test"
    assert captured["temperature"] == 0
    assert captured["response_format"] == {"type": "json_object"}
    assert captured["messages"][1]["content"].count("UNIQUE-BODY-77") == 1


def test_installed_sdk_exposes_chat_completions():
    from openai import OpenAI

    sdk_client = OpenAI(api_key="sk-test")
    assert callable(sdk_client.chat.completions.create)
