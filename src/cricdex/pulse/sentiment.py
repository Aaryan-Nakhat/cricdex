"""LLM-based player-mention + sentiment extraction from Reddit posts.

Per post: one prompt to Gemini Flash asking for an array of
`{player, sentiment, theme}` triples grounded in the post title +
selftext. Sentiment ∈ {positive, neutral, negative}. The LLM is
instructed to skip posts that don't mention a specific player.

Aggregator collapses per-player tallies and emits a leaderboard.
"""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Iterable

from loguru import logger

from cricdex.common import llm

SENTIMENT_SYSTEM = """You are a sports-text mention extractor.

Read the supplied Reddit-style cricket post (title + selftext). For every
SPECIFIC cricketer named in the text, emit one object:
    {"player": "<verbatim name as written>", "sentiment": "positive|neutral|negative", "theme": "<1-4 words>"}

Rules:
- Only emit a row if a real cricketer is named. Skip team-only / generic posts.
- "sentiment" is the post's stance toward that player.
- "theme" is a short tag (e.g. "form", "injury", "captaincy", "selection",
  "controversy", "praise").
- Return a JSON object: {"mentions": [...]}.
- If nothing applies, return {"mentions": []}.

Do not include any prose outside the JSON.
""".strip()


def extract_mentions(post: dict) -> list[dict]:
    title = post.get("title") or ""
    body = post.get("selftext") or ""
    if not title.strip():
        return []
    user_prompt = f"TITLE: {title}\n\nSELFTEXT: {body[:1500]}\n\nReturn the mentions JSON."
    try:
        result = llm.generate_json(SENTIMENT_SYSTEM, user_prompt, temperature=0.0)
    except llm.LLMError as e:
        logger.warning(f"extract failed for post {post.get('id')}: {e}")
        return []
    rows = result.get("mentions") or []
    if not isinstance(rows, list):
        return []
    cleaned: list[dict] = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        cleaned.append(
            {
                "post_id": post.get("id"),
                "subreddit": post.get("subreddit"),
                "score": post.get("score"),
                "num_comments": post.get("num_comments"),
                "permalink": post.get("permalink"),
                "title": post.get("title"),
                "player": r.get("player"),
                "sentiment": r.get("sentiment"),
                "theme": r.get("theme"),
            }
        )
    return cleaned


def aggregate(mentions: Iterable[dict]) -> list[dict]:
    counts: dict[str, dict] = defaultdict(
        lambda: {
            "player": None,
            "n": 0,
            "positive": 0,
            "neutral": 0,
            "negative": 0,
            "weighted_score": 0,
        }
    )
    for m in mentions:
        p = m.get("player")
        if not p:
            continue
        row = counts[p]
        row["player"] = p
        row["n"] += 1
        s = (m.get("sentiment") or "").lower()
        if s in row:
            row[s] += 1
        weight = (m.get("score") or 0) + (m.get("num_comments") or 0)
        sign = {"positive": 1, "neutral": 0, "negative": -1}.get(s, 0)
        row["weighted_score"] += sign * weight
    out = list(counts.values())
    out.sort(key=lambda r: (-r["n"], -abs(r["weighted_score"])))
    return out


def dump_jsonl(path, rows: Iterable[dict]) -> None:
    with open(path, "w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
