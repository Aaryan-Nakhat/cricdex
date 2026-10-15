"""Probabilistic skill head-to-head between two players.

The Bayesian scout fit (`bayesian.py`) gives every player a posterior
over each latent skill axis — a mean and a standard deviation. Each
complete value is treated as `Normal(mean, sd)`, so a head-to-head is
closed-form: the difference of two independent normals is normal, and

    P(A > B) = Φ( (mean_A − mean_B) / sqrt(sd_A² + sd_B²) )

No re-fit, no stored samples — we read the already-saved
`scout_ratings_<collection>.json` and evaluate the CDF.

Complete value per role (`_complete_axis`):
- current files: the fit's `value` / `value_sd` — scoring + survival
  (batter) or economy + strike (bowler), each axis in population-sd
  units (see `bayesian._value_draws`);
- older dismissal-aware files without `value_sd`: raw sum of the two
  axes, variances added;
- legacy runs-only files: the scoring / economy axis alone.
A missing (or non-positive) sd means the uncertainty is unknown, so that
comparison is skipped rather than guessed.

Three comparisons are produced when the data supports them: batter,
bowler, and all_rounder (complete batting + complete bowling, variances
add) when BOTH players have both ratings.

`site/src/lib/headtohead.ts` is the same engine for the web; the two are
locked by `test_scripts/test_h2h_parity.py`.
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


_SECOND_AXIS = {
    "batter": ("survival_skill", "survival_skill_sd", "scoring + survival", "scoring only"),
    "bowler": ("strike_skill", "strike_skill_sd", "economy + strike", "economy only"),
}


def _sd(x) -> float | None:
    """A usable posterior sd, or None when it is missing / non-positive."""
    if isinstance(x, bool) or not isinstance(x, int | float):
        return None
    return float(x) if math.isfinite(x) and x > 0 else None


def _complete_axis(row: dict, role: str) -> tuple[float, float, str] | None:
    """(mean, sd, component) of the complete batting / bowling value, or
    None when the row lacks a skill or its uncertainty is unknown."""
    second, second_sd_col, full, legacy = _SECOND_AXIS[role]
    skill = row.get("skill")
    if skill is None:
        return None
    if row.get(second) is None:  # legacy runs-only ratings
        sd = _sd(row.get("skill_sd"))
        return None if sd is None else (skill, sd, f"{legacy} (legacy ratings)")
    if row.get("value") is not None and row.get("value_sd") is not None:
        sd = _sd(row["value_sd"])
        return None if sd is None else (row["value"], sd, full)
    # Older dismissal-aware files: raw sum, variances add.
    sd1, sd2 = _sd(row.get("skill_sd")), _sd(row.get(second_sd_col))
    if sd1 is None or sd2 is None:
        return None
    return skill + row[second], math.sqrt(sd1**2 + sd2**2), full


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
    # floor(x + 0.5), not round(): Python rounds halves to even, JS up.
    pct = math.floor(100 * max(p_a, 1.0 - p_a) + 0.5)
    leader = name_a if p_a >= 0.5 else name_b
    if pct < 60:
        return f"too close to call ({pct}% lean to {leader})"
    if pct < 75:
        return f"{leader} likely better ({pct}%)"
    if pct < 90:
        return f"{leader} clearly better ({pct}%)"
    return f"{leader} dominant ({pct}%)"


def compare_rows(
    name_a: str,
    name_b: str,
    rows_a: dict[str, dict | None],
    rows_b: dict[str, dict | None],
    role: str,
) -> dict | None:
    """One role's comparison from each player's {"batter": row, "bowler": row}.
    `role` is "batter", "bowler" or "all_rounder". None when either side has
    no comparable rating."""
    roles = ("batter", "bowler") if role == "all_rounder" else (role,)
    axes_a, axes_b = [], []
    for r in roles:
        ra, rb = rows_a.get(r), rows_b.get(r)
        if ra is None or rb is None:
            return None
        ca, cb = _complete_axis(ra, r), _complete_axis(rb, r)
        # Different components = different scales (a legacy row vs a full one).
        if ca is None or cb is None or ca[2] != cb[2]:
            return None
        axes_a.append(ca)
        axes_b.append(cb)
    mean_a, mean_b = sum(c[0] for c in axes_a), sum(c[0] for c in axes_b)
    sd_a = math.sqrt(sum(c[1] ** 2 for c in axes_a))
    sd_b = math.sqrt(sum(c[1] ** 2 for c in axes_b))
    cmp = _compare_normal(mean_a, sd_a, mean_b, sd_b)
    cmp["component"] = " | ".join(c[2] for c in axes_a)
    ra0, rb0 = rows_a[roles[0]], rows_b[roles[0]]
    if role != "all_rounder":
        cmp["score_a"], cmp["score_b"] = ra0["skill"], rb0["skill"]
        second = _SECOND_AXIS[role][0]
        if ra0.get(second) is not None:
            # Display sub-axes (survival for batters, strike for bowlers).
            cmp["survival_a"], cmp["survival_b"] = ra0[second], rb0[second]
    cmp["balls_a"] = sum(rows_a[r].get("balls") or 0 for r in roles)
    cmp["balls_b"] = sum(rows_b[r].get("balls") or 0 for r in roles)
    cmp["verdict"] = _verdict(name_a, name_b, cmp["p_a_better"])
    return cmp


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
    rows_a = {r: idx.get((name_a, r)) for r in ("batter", "bowler")}
    rows_b = {r: idx.get((name_b, r)) for r in ("batter", "bowler")}
    comparisons = {
        role: compare_rows(name_a, name_b, rows_a, rows_b, role)
        for role in ("batter", "bowler", "all_rounder")
    }
    return {
        "name_a": name_a,
        "name_b": name_b,
        "collection": collection,
        "dismissal_aware": any(r.get("survival_skill") is not None for r in rows),
        "comparisons": comparisons,
    }
