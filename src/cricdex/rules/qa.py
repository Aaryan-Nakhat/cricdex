"""LLM Q&A over rule clauses with citation discipline.

Uses `cricdex.common.llm.generate` (HTTP proxy) so swapping the underlying
LLM provider later is one-file change.
"""

from __future__ import annotations

from cricdex.common import llm
from cricdex.config import settings
from cricdex.rules.retrieval import hybrid_search

SYSTEM_PROMPT = """You answer cricket rule questions using ONLY the supplied passages.

Citation rules:
- Every factual claim MUST be cited in square brackets like
  [icc_pc_men_t20i_2025 §21.5.2].
- Multiple sources should each get their own bracket.
- If two passages give different rules for different formats, present the
  difference as a short Markdown table.
- If the passages do NOT contain the answer, reply exactly:
  "Not in current CricDex corpus — check the publisher directly."
- Do not speculate. Do not draw on prior knowledge outside the passages.

Style: terse, factual. Cricket terminology preserved.
""".strip()

FORMAT_TO_SOURCE_IDS: dict[str, list[str]] = {
    "test": ["icc_pc_men_test_2025", "icc_wtc_2025_2027"],
    "odi": ["icc_pc_men_odi_2025"],
    "t20i": ["icc_pc_men_t20i_2025"],
    "women_test": ["icc_pc_women_test_2025"],
    "women_odi": ["icc_pc_women_odi_2025"],
    "women_t20i": ["icc_pc_women_t20i_2025"],
    "u19_men": ["icc_u19_men_world_cup_2024"],
    "u19_women": ["icc_u19_women_t20wc_2025"],
    "t20wc": ["icc_men_t20wc_2026"],
    "ipl": ["ipl_pc_2026", "ipl_impact_player_2025_27"],
    "hundred": ["hundred_pc_2025"],
    "bbl": ["bbl_pc_2024_25"],
    "wbbl": ["wbbl_pc_2025_26"],
    "shield": ["cricket_aus_shield_2025_26"],
    "oneday_cup": ["cricket_aus_oneday_cup_2025_26"],
    "mcc_laws": ["mcc_laws_2017_4th_2026"],
    "code_of_conduct": [
        "icc_code_of_conduct_players_2023",
        "icc_code_of_conduct_match_officials_2016",
        "ipl_code_of_conduct_2025",
    ],
    "anti_corruption": ["icc_anti_corruption_2024"],
}


def resolve_formats(formats: list[str] | None) -> list[str] | None:
    if not formats:
        return None
    out: list[str] = []
    for fmt in formats:
        out.extend(FORMAT_TO_SOURCE_IDS.get(fmt.lower(), []))
    return out or None


def format_passages(hits: list[tuple[float, dict]]) -> str:
    blocks: list[str] = []
    for _, p in hits:
        cite = f"[{p['source_id']} §{p['law_number']}]"
        meta = f"({p['edition']}, p.{p.get('page', '?')})"
        blocks.append(f"{cite} {meta} {p['title']}\n{p['text']}")
    return "\n\n---\n\n".join(blocks)


def answer(
    query: str,
    formats: list[str] | None = None,
    top_k: int = 8,
    model: str = llm.DEFAULT_TEXT_MODEL,
) -> dict:
    source_ids = resolve_formats(formats)
    hits = hybrid_search(query, top_k=top_k, source_ids=source_ids)
    passages_str = format_passages(hits)

    if not settings.gemini_tmp_url:
        return {
            "answer": ("(GEMINI_TMP_URL not set — returning passages only)\n\n" + passages_str),
            "passages": [p for _, p in hits],
            "citations": [(p["source_id"], p["law_number"]) for _, p in hits],
            "llm_used": None,
        }

    user_prompt = f"PASSAGES:\n{passages_str}\n\nQUESTION: {query}\n\nANSWER:"
    text = llm.generate(
        system_prompt=SYSTEM_PROMPT,
        user_prompt=user_prompt,
        model=model,
    )
    return {
        "answer": text,
        "passages": [p for _, p in hits],
        "citations": [(p["source_id"], p["law_number"]) for _, p in hits],
        "llm_used": model,
    }
