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


def _complete_axis(
    row: dict,
    primary_col: str,
    primary_sd_col: str,
    second_col: str,
    second_sd_col: str,
) -> tuple[float, float] | None:
    """Combine two latent axes (e.g. scoring + survival) into a single
    posterior (mean, sd) by raw sum — both axes are on a log scale and
    empirically comparable in magnitude, so a plain sum keeps honest
    uncertainty (variances add). Returns None if the second axis is
    absent (legacy ratings without dismissal modelling)."""
    if row.get(second_col) is None:
        return None
    mean = row[primary_col] + row[second_col]
    sd_primary = row.get(primary_sd_col) or 1.0
    sd_second = row.get(second_sd_col) or 1.0
    sd = math.sqrt(sd_primary**2 + sd_second**2)
    return mean, sd


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

    dismissal_aware = any(r.get("survival_skill") is not None for r in rows)

    # --- batter (scoring + survival) ---
    bat_a, bat_b = idx.get((name_a, "batter")), idx.get((name_b, "batter"))
    comparisons["batter"] = _build_batter(name_a, name_b, bat_a, bat_b)

    # --- bowler (economy + strike) ---
    bowl_a, bowl_b = idx.get((name_a, "bowler")), idx.get((name_b, "bowler"))
    comparisons["bowler"] = _build_bowler(name_a, name_b, bowl_a, bowl_b)

    # --- all-rounder = complete batting value + complete bowling value ---
    if bat_a is not None and bat_b is not None and bowl_a is not None and bowl_b is not None:
        ca_a = _complete_axis(
            bat_a, "skill", "skill_sd", "survival_skill", "survival_skill_sd"
        ) or (bat_a["skill"], bat_a.get("skill_sd") or 1.0)
        ca_b = _complete_axis(
            bat_b, "skill", "skill_sd", "survival_skill", "survival_skill_sd"
        ) or (bat_b["skill"], bat_b.get("skill_sd") or 1.0)
        cb_a = _complete_axis(bowl_a, "skill", "skill_sd", "strike_skill", "strike_skill_sd") or (
            bowl_a["skill"],
            bowl_a.get("skill_sd") or 1.0,
        )
        cb_b = _complete_axis(bowl_b, "skill", "skill_sd", "strike_skill", "strike_skill_sd") or (
            bowl_b["skill"],
            bowl_b.get("skill_sd") or 1.0,
        )
        mean_a, mean_b = ca_a[0] + cb_a[0], ca_b[0] + cb_b[0]
        sd_a = math.sqrt(ca_a[1] ** 2 + cb_a[1] ** 2)
        sd_b = math.sqrt(ca_b[1] ** 2 + cb_b[1] ** 2)
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
        "dismissal_aware": dismissal_aware,
        "comparisons": comparisons,
    }


def _build_batter(name_a, name_b, ra, rb) -> dict | None:
    """Complete batting comparison: scoring rate + survival (raw sum).
    Falls back to scoring-only on legacy ratings."""
    if ra is None or rb is None:
        return None
    ca = _complete_axis(ra, "skill", "skill_sd", "survival_skill", "survival_skill_sd")
    cb = _complete_axis(rb, "skill", "skill_sd", "survival_skill", "survival_skill_sd")
    if ca is not None and cb is not None:
        cmp = _compare_normal(ca[0], ca[1], cb[0], cb[1])
        cmp["component"] = "scoring + survival"
        # Surface raw sub-axes for display.
        cmp["score_a"], cmp["score_b"] = ra["skill"], rb["skill"]
        cmp["survival_a"], cmp["survival_b"] = ra["survival_skill"], rb["survival_skill"]
    else:
        cmp = _compare_normal(
            ra["skill"], ra.get("skill_sd") or 1.0, rb["skill"], rb.get("skill_sd") or 1.0
        )
        cmp["component"] = "scoring only (legacy ratings)"
    cmp["balls_a"], cmp["balls_b"] = ra.get("balls"), rb.get("balls")
    cmp["verdict"] = _verdict(name_a, name_b, cmp["p_a_better"])
    return cmp


def _build_bowler(name_a, name_b, ra, rb) -> dict | None:
    """Complete bowling comparison: economy + strike (raw sum).
    Falls back to economy-only on legacy ratings."""
    if ra is None or rb is None:
        return None
    ca = _complete_axis(ra, "skill", "skill_sd", "strike_skill", "strike_skill_sd")
    cb = _complete_axis(rb, "skill", "skill_sd", "strike_skill", "strike_skill_sd")
    if ca is not None and cb is not None:
        cmp = _compare_normal(ca[0], ca[1], cb[0], cb[1])
        cmp["component"] = "economy + strike"
        cmp["score_a"], cmp["score_b"] = ra["skill"], rb["skill"]
        cmp["survival_a"], cmp["survival_b"] = ra["strike_skill"], rb["strike_skill"]
    else:
        cmp = _compare_normal(
            ra["skill"], ra.get("skill_sd") or 1.0, rb["skill"], rb.get("skill_sd") or 1.0
        )
        cmp["component"] = "economy only (legacy ratings)"
    cmp["balls_a"], cmp["balls_b"] = ra.get("balls"), rb.get("balls")
    cmp["verdict"] = _verdict(name_a, name_b, cmp["p_a_better"])
    return cmp
