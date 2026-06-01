"""Probabilistic skill head-to-head between two players.

The Bayesian scout fit (`bayesian.py`) gives every player a posterior
over their latent skill — a mean (`skill`) and a standard deviation
(`skill_sd`). ADVI's posterior is mean-field normal, so each skill is
well-approximated by `Normal(skill, skill_sd)`.

That makes a head-to-head closed-form: the difference of two
independent normals is itself normal, so

    skill_A − skill_B  ~  Normal(mean_A − mean_B,
                                  sqrt(sd_A² + sd_B²))

and the probability A is genuinely the better player is just the
normal CDF of that difference at zero:

    P(A > B) = Φ( (mean_A − mean_B) / sqrt(sd_A² + sd_B²) )

No re-fit, no stored samples — we read the already-saved
`scout_ratings_<collection>.json` and evaluate the CDF.

Three comparisons are produced when the data supports them:
- **batter** — both players' batting skill (higher = scores faster
  for the opponent faced).
- **bowler** — both players' bowling skill (higher = suppresses runs
  harder).
- **all_rounder** — the sum `batter_skill + bowler_skill` (both axes
  point "higher = better", so the sum is a coherent total-impact
  proxy); variance adds. Only emitted when BOTH players have both a
  batter and a bowler rating.

Caveat surfaced to the user: the underlying skill is opponent-adjusted
**scoring / run-suppression rate**, not complete value — it does not
yet model dismissals (a fast slogger who gets out often still scores
"high"). Dismissal-aware ratings are a vNext model change.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

from cricdex.config import DATA_DIR

METRIC_DIR = DATA_DIR / "metrics"


def _phi(z: float) -> float:
    """Standard-normal CDF via erf — avoids a scipy dependency."""
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def _load_ratings(collection: str) -> list[dict]:
    path = METRIC_DIR / f"scout_ratings_{collection}.json"
    if not path.exists():
        return []
    try:
        return json.loads(Path(path).read_text())
    except Exception:
        return []


def _index(rows: list[dict]) -> dict[tuple[str, str], dict]:
    """Index by (unique_name, role) → row. Falls back to cricsheet_id
    when unique_name is absent so older rating files still resolve."""
    out: dict[tuple[str, str], dict] = {}
    for r in rows:
        key_name = r.get("unique_name") or r.get("cricsheet_id")
        if key_name:
            out[(key_name, r["role"])] = r
    return out


def _compare_normal(
    mean_a: float,
    sd_a: float,
    mean_b: float,
    sd_b: float,
) -> dict:
    """Closed-form P(A > B) for two independent normal posteriors."""
    diff = mean_a - mean_b
    pooled = math.sqrt(sd_a**2 + sd_b**2) or 1e-9
    p_a = _phi(diff / pooled)
    return {
        "mean_a": mean_a,
        "sd_a": sd_a,
        "mean_b": mean_b,
        "sd_b": sd_b,
        "diff": diff,
        "pooled_sd": pooled,
        "p_a_better": p_a,
        "p_b_better": 1.0 - p_a,
    }


def _verdict(name_a: str, name_b: str, p_a: float) -> str:
    """Human-readable verdict that respects statistical honesty —
    near-50/50 reads as 'too close to call', not a fake winner."""
    pct = round(100 * max(p_a, 1.0 - p_a))
    leader = name_a if p_a >= 0.5 else name_b
    if pct < 60:
        return f"too close to call ({pct}% lean to {leader})"
    if pct < 75:
        return f"{leader} likely better ({pct}%)"
    if pct < 90:
        return f"{leader} clearly better ({pct}%)"
    return f"{leader} dominant ({pct}%)"


def head_to_head(name_a: str, name_b: str, collection: str = "ipl") -> dict:
    """Compare two players' Bayesian skills role-by-role.

    `name_a` / `name_b` should be canonical `unique_name`s (resolve via
    the fuzzy resolver before calling). Returns a dict:

        {
          "name_a": ..., "name_b": ..., "collection": ...,
          "comparisons": {
              "batter": {...} | None,
              "bowler": {...} | None,
              "all_rounder": {...} | None,
          },
          "error": <str>   # only if ratings file missing
        }

    Each per-role dict carries means / sds / diff / pooled_sd /
    p_a_better / p_b_better / verdict / balls_a / balls_b.
    """
    rows = _load_ratings(collection)
    if not rows:
        return {
            "name_a": name_a,
            "name_b": name_b,
            "collection": collection,
            "comparisons": {},
            "error": (
                f"no scout_ratings_{collection}.json — run "
                f"`cricdex data ingest ratings -c {collection}`"
            ),
        }
    idx = _index(rows)
    comparisons: dict[str, dict | None] = {}

    for role in ("batter", "bowler"):
        ra = idx.get((name_a, role))
        rb = idx.get((name_b, role))
        if ra is None or rb is None:
            comparisons[role] = None
            continue
        cmp = _compare_normal(
            ra["skill"],
            ra.get("skill_sd") or 1.0,
            rb["skill"],
            rb.get("skill_sd") or 1.0,
        )
        cmp["balls_a"] = ra.get("balls")
        cmp["balls_b"] = rb.get("balls")
        cmp["verdict"] = _verdict(name_a, name_b, cmp["p_a_better"])
        comparisons[role] = cmp

    # All-rounder = batting skill + bowling skill (both higher = better),
    # variances add. Only when BOTH players have BOTH ratings.
    bat_a, bat_b = idx.get((name_a, "batter")), idx.get((name_b, "batter"))
    bowl_a, bowl_b = idx.get((name_a, "bowler")), idx.get((name_b, "bowler"))
    if all(x is not None for x in (bat_a, bat_b, bowl_a, bowl_b)):
        mean_a = bat_a["skill"] + bowl_a["skill"]
        mean_b = bat_b["skill"] + bowl_b["skill"]
        sd_a = math.sqrt((bat_a.get("skill_sd") or 1.0) ** 2 + (bowl_a.get("skill_sd") or 1.0) ** 2)
        sd_b = math.sqrt((bat_b.get("skill_sd") or 1.0) ** 2 + (bowl_b.get("skill_sd") or 1.0) ** 2)
        cmp = _compare_normal(mean_a, sd_a, mean_b, sd_b)
        cmp["balls_a"] = (bat_a.get("balls") or 0) + (bowl_a.get("balls") or 0)
        cmp["balls_b"] = (bat_b.get("balls") or 0) + (bowl_b.get("balls") or 0)
        cmp["verdict"] = _verdict(name_a, name_b, cmp["p_a_better"])
        comparisons["all_rounder"] = cmp
    else:
        comparisons["all_rounder"] = None

    return {
        "name_a": name_a,
        "name_b": name_b,
        "collection": collection,
        "comparisons": comparisons,
    }
