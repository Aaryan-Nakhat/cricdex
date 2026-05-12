"""DRS scenario library + scoring helpers."""

from __future__ import annotations

import json
import random

from cricdex.config import DATA_DIR

SCENARIOS_PATH = DATA_DIR / "drs" / "scenarios.jsonl"


def load_scenarios() -> list[dict]:
    if not SCENARIOS_PATH.exists():
        return []
    return [json.loads(line) for line in SCENARIOS_PATH.read_text().splitlines() if line.strip()]


def categories() -> list[str]:
    return sorted({s["category"] for s in load_scenarios()})


def pick(
    n: int = 5,
    category: str | None = None,
    difficulty: str | None = None,
    seed: int | None = None,
) -> list[dict]:
    pool = load_scenarios()
    if category:
        pool = [s for s in pool if s["category"] == category]
    if difficulty:
        pool = [s for s in pool if s["difficulty"] == difficulty]
    rng = random.Random(seed)
    rng.shuffle(pool)
    return pool[:n]


def score(answers: dict[str, str]) -> dict:
    """answers = {scenario_id: chosen_option}."""
    scenarios = {s["id"]: s for s in load_scenarios()}
    correct = 0
    rows: list[dict] = []
    for sid, chosen in answers.items():
        if sid not in scenarios:
            continue
        right = scenarios[sid]["correct"]
        ok = chosen == right
        if ok:
            correct += 1
        rows.append(
            {
                "id": sid,
                "category": scenarios[sid]["category"],
                "correct_answer": right,
                "your_answer": chosen,
                "got_right": ok,
                "explanation": scenarios[sid]["explanation"],
                "citation": scenarios[sid]["citation"],
            }
        )
    total = len(rows) or 1
    return {
        "correct": correct,
        "total": total,
        "pct": round(100 * correct / total, 1),
        "rows": rows,
    }
