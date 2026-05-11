"""Temporary Gemini client.

Points at an external `generate` / `generate_json` proxy URL configured via
`GEMINI_TMP_URL`. This is a stop-gap so we can hit Gemini without provisioning
a personal API key right now; swap to the official `google-genai` SDK with a
personal `GEMINI_API_KEY` before public launch.

Endpoints expected:
    POST {base}/generate       → {"status": "success", "response": "<text>", "model": "..."}
    POST {base}/generate_json  → {"status": "success", "result": <parsed object>, ...}

Common payload (JSON body):
    {
      "system_prompt": "...",
      "user_prompt":   "...",
      "model":         "gemini-2.5-flash",
      "temperature":    0.0
    }

If `GEMINI_TMP_API_KEY` is set, the value is sent as the `x-api-key` header.
"""

from __future__ import annotations

import httpx

from cricdex.config import settings

DEFAULT_TEXT_MODEL = "gemini-2.5-flash"
DEFAULT_JSON_MODEL = "gemini-2.5-pro"


class LLMError(RuntimeError):
    pass


def _client(timeout: float) -> httpx.Client:
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if settings.gemini_tmp_api_key:
        headers["x-api-key"] = settings.gemini_tmp_api_key
    return httpx.Client(timeout=timeout, headers=headers)


def _base() -> str:
    if not settings.gemini_tmp_url:
        raise LLMError("GEMINI_TMP_URL is not set in .env")
    return settings.gemini_tmp_url.rstrip("/")


def generate(
    system_prompt: str,
    user_prompt: str,
    model: str = DEFAULT_TEXT_MODEL,
    temperature: float = 0.0,
    timeout: float = 60.0,
) -> str:
    payload = {
        "system_prompt": system_prompt,
        "user_prompt": user_prompt,
        "model": model,
        "temperature": temperature,
    }
    with _client(timeout) as cx:
        r = cx.post(f"{_base()}/generate", json=payload)
    if r.status_code != 200:
        raise LLMError(f"generate failed: HTTP {r.status_code} {r.text[:300]}")
    body = r.json()
    if body.get("status") != "success":
        raise LLMError(f"generate non-success: {body}")
    return body["response"]


def generate_json(
    system_prompt: str,
    user_prompt: str,
    model: str = DEFAULT_JSON_MODEL,
    temperature: float = 0.0,
    timeout: float = 90.0,
) -> dict:
    payload = {
        "system_prompt": system_prompt,
        "user_prompt": user_prompt,
        "model": model,
        "temperature": temperature,
    }
    with _client(timeout) as cx:
        r = cx.post(f"{_base()}/generate_json", json=payload)
    if r.status_code != 200:
        raise LLMError(f"generate_json failed: HTTP {r.status_code} {r.text[:300]}")
    body = r.json()
    if body.get("status") != "success":
        raise LLMError(f"generate_json non-success: {body}")
    return body["result"]
