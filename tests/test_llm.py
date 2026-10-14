"""The LLM client is provider-neutral: the model comes from settings, any LiteLLM model string."""

import types

import pytest

from cricdex.common import llm


def _fake(text):
    def completion(**kw):
        _fake.kw = kw
        msg = types.SimpleNamespace(content=text)
        return types.SimpleNamespace(choices=[types.SimpleNamespace(message=msg)])

    return types.SimpleNamespace(completion=completion)


def test_unset_model_is_a_clear_error(monkeypatch):
    monkeypatch.setattr(llm.settings, "llm_model", "")
    assert not llm.configured()
    with pytest.raises(llm.LLMError, match="LLM_MODEL"):
        llm.generate_json("s", "u")


def test_json_is_parsed_and_settings_passed_through(monkeypatch):
    import sys

    monkeypatch.setattr(llm.settings, "llm_model", "provider/model")
    monkeypatch.setattr(llm.settings, "llm_api_key", "k")
    monkeypatch.setattr(llm.settings, "llm_api_base", "")
    monkeypatch.setitem(sys.modules, "litellm", _fake('```json\n{"players": [{"id": "a"}]}\n```'))
    assert llm.generate_json("s", "u") == {"players": [{"id": "a"}]}
    assert _fake.kw["model"] == "provider/model" and _fake.kw["api_key"] == "k"
    assert "api_base" not in _fake.kw
