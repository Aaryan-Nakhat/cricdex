"""LLM client — any provider, through LiteLLM.

Which model to call is configuration, not code: set ``LLM_MODEL`` in ``.env`` (or ``cricdex config set
llm_model ...``) to any LiteLLM model string, e.g. ``openai/gpt-4o-mini``, ``anthropic/claude-sonnet-4-5``,
``llm/llm-model``, ``ollama/llama3.1``. The provider's key is read by LiteLLM from its usual env var
(``OPENAI_API_KEY``, ``ANTHROPIC_API_KEY``, ``LLM_API_KEY``, …); ``LLM_API_KEY`` / ``LLM_API_BASE`` override
the key and endpoint when set (a self-hosted or OpenAI-compatible server).

Used only by the optional player-taxonomy enrichment (``scripts/enrich_taxonomy.py``).
"""

from __future__ import annotations

import json
import re

from cricdex.config import settings


class LLMError(RuntimeError):
    pass


def configured() -> bool:
    return bool(settings.llm_model)


def _kwargs(temperature: float) -> dict:
    if not settings.llm_model:
        raise LLMError("LLM_MODEL is not set — add it to .env (any LiteLLM model string)")
    kw: dict = {"model": settings.llm_model, "temperature": temperature}
    if settings.llm_api_key:
        kw["api_key"] = settings.llm_api_key
    if settings.llm_api_base:
        kw["api_base"] = settings.llm_api_base
    return kw


def _complete(messages: list[dict], temperature: float, json_mode: bool) -> str:
    import litellm  # heavy import; only paid when the LLM is actually used

    kw = _kwargs(temperature)
    if json_mode:
        kw["response_format"] = {"type": "json_object"}
    try:
        resp = litellm.completion(messages=messages, drop_params=True, **kw)
    except Exception as e:  # noqa: BLE001 — surface any provider error as one type
        raise LLMError(f"LLM call failed: {e}") from e
    return resp.choices[0].message.content or ""


def generate(system: str, user: str, *, temperature: float = 0.2) -> str:
    """Plain-text completion."""
    return _complete(
        [{"role": "system", "content": system}, {"role": "user", "content": user}],
        temperature,
        json_mode=False,
    )


def generate_json(system: str, user: str, *, temperature: float = 0.0) -> dict | list:
    """Completion parsed as JSON. Tolerates a ```json fence or text around the object."""
    text = _complete(
        [{"role": "system", "content": system}, {"role": "user", "content": user}],
        temperature,
        json_mode=True,
    )
    text = re.sub(r"^\s*```(?:json)?\s*|\s*```\s*$", "", text.strip())
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"[\[{].*[\]}]", text, re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                pass
    raise LLMError(f"LLM did not return JSON: {text[:300]}")
