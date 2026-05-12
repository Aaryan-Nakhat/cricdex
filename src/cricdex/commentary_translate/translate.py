"""Multilingual cricket-commentary translator.

v1 is text-only. Voice-cloned target-language audio is the deferred
year-2 milestone (XTTS-v2 / F5-TTS / OpenVoice + AI4Bharat IndicTTS).

Today's job: take English ball-by-ball commentary, hand it to the
temp Gemini proxy with a cricket-glossary system prompt, and return
the same text in the user's target language. Cricket terms (line and
length, yorker, bouncer, slog-sweep, …) are preserved where the
target language uses them as loanwords; otherwise the most-used
local term is substituted.
"""

from __future__ import annotations

from cricdex.common import llm

TARGETS = {
    "hi": "Hindi (Devanagari script)",
    "ta": "Tamil",
    "bn": "Bengali",
    "ur": "Urdu (Nastaliq script)",
    "si": "Sinhala",
    "mr": "Marathi (Devanagari script)",
    "te": "Telugu",
    "kn": "Kannada",
}

SYSTEM_PROMPT = """You are a cricket-commentary translator.

Translate the English text the user supplies into {target_label}.

Rules:
- Stay faithful to the original — no embellishments, no extra phrases.
- Cricket terms (yorker, bouncer, line and length, googly, doosra,
  slog-sweep, third man, fine leg, square leg, slip, deep midwicket,
  cow corner, helicopter shot, etc.) should be preserved as the most
  natural local form. Hindi / Marathi / Urdu commentators routinely
  borrow English cricket terms — that's fine.
- Numbers stay as numerals (Arabic numerals; do not transliterate).
- Player names stay in English script unless the target script has a
  widely accepted spelling for the player.
- Output only the translated text. No preamble. No "Translation:".
""".strip()


def translate(
    english_text: str,
    target: str = "hi",
    model: str = llm.DEFAULT_TEXT_MODEL,
    temperature: float = 0.1,
) -> str:
    if target not in TARGETS:
        raise ValueError(f"unsupported target {target!r}. options: {sorted(TARGETS)}")
    system = SYSTEM_PROMPT.format(target_label=TARGETS[target])
    return llm.generate(
        system_prompt=system,
        user_prompt=english_text,
        model=model,
        temperature=temperature,
    )
