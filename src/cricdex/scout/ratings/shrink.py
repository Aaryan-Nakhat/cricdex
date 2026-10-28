"""How much a value can be trusted: the shrinkage of a player's value toward his role's population mean,
given the evidence it rests on (docs/METHODOLOGY.md §4c; ROADMAP I18).

Every value the auction tools read is a posterior mean: within its league the Bayesian rating shrinks a
thin record toward its batting slot's (or bowling group's) mean, and the league translation
(scout/translation.py) moves it onto the IPL scale with its own uncertainty. But the contribution per
match, P(plays) and Bid plan then used that mean as if it were the player's IPL level, and the evidence
behind it was never asked whether it predicts the IPL as well as its standard deviation says. A thin
SMAT record, or an overseas league record of a 42-year-old, translated onto the IPL scale is a weaker
predictor of what he does in an IPL match than the same number earned in the IPL.

This module calibrates that, fitted on what players then did in the IPL (`scripts/value_shrink_fit.py`,
frozen protocol), in the measurement-error form of empirical Bayes:

    value used = mu + k × (value − mu),  k = k0 × tau² / (tau² + s × sd² + w_o × (1 − IPL share) + w_r × years)

`mu` is the role's population mean on the IPL scale, `tau²` the spread of true levels, `sd` the value's
own posterior sd (the blend's, translation included), `IPL share` the IPL's weight in the blend and
`years` the years since his last season in any league. `s`, `w_o`, `w_r` are fitted: how much the
reported uncertainty, the non-IPL share and the staleness of the evidence really cost. A long, recent IPL
record keeps its value; a thin, old or league-only record is pulled toward the mean by as much as the
data say. `k0` is the part of the shrink every value takes, however long its record (a season-ahead
rating regresses even when its evidence is thick: true levels move between seasons). The candidates
switch the terms on and off (one flat factor; s alone; all three; k0 with s; k0 with all three).
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

MODEL_PATH = Path(__file__).resolve().parents[4] / "config" / "value_shrink.json"
ROLES = ("batter", "bowler")


@dataclass
class RoleShrink:
    mu: float
    tau2: float
    s: float = 0.0
    w_o: float = 0.0
    w_r: float = 0.0
    k_flat: float | None = None  # the one-factor candidate: k fixed, not by evidence
    # the season-ahead factor every value takes on top of its evidence term (candidates K4 / K5, since
    # 2026-10-27): k = k0 × tau² / (tau² + …). 1 = the evidence term alone (K2 / K3)
    k0: float = 1.0

    def k(self, sd: float, ipl_share: float, years: float) -> float:
        if self.k_flat is not None:
            return self.k_flat
        den = (
            self.tau2 + self.s * sd * sd + self.w_o * (1.0 - ipl_share) + self.w_r * max(years, 0.0)
        )
        return self.k0 * self.tau2 / den if den > 0 else self.k0

    def apply(self, v: float, sd: float, ipl_share: float, years: float) -> float:
        return self.mu + self.k(sd, ipl_share, years) * (v - self.mu)

    def to_json(self) -> dict:
        return {k: (None if v is None else round(float(v), 6)) for k, v in self.__dict__.items()}

    @staticmethod
    def from_json(d: dict) -> RoleShrink:
        return RoleShrink(float(d["mu"]), float(d["tau2"]), float(d.get("s") or 0.0),
                          float(d.get("w_o") or 0.0), float(d.get("w_r") or 0.0),
                          None if d.get("k_flat") is None else float(d["k_flat"]),
                          float(d.get("k0") if d.get("k0") is not None else 1.0))  # fmt: skip


def load_model(
    path: Path | str | None = None, which: str = "model"
) -> dict[str, RoleShrink] | None:
    """role → RoleShrink (`which` = "model", fitted on every season, or "model_le2024" for the protocol
    runs). None without the file, or when the chosen candidate is no calibration."""
    p = Path(path) if path else MODEL_PATH
    if not p.exists():
        return None
    m = json.loads(p.read_text(encoding="utf-8")).get(which)
    if not m:
        return None
    return {r: RoleShrink.from_json(v) for r, v in m.items()}


def years_since(obs, date: str) -> dict[str, float]:
    """cid → years from the end of his last season with a value in any pool league (before `date`) to
    `date`'s year (0 = a value this year): drift.season_obs rows."""
    import polars as pl

    from cricdex.scout.ratings import drift

    o = drift.obs_asof(obs, date)
    y = int(date[:4])
    return {
        cid: float(y - last)
        for cid, last in o.group_by("cid").agg(pl.col("year").max()).iter_rows()
    }


def adjust(
    values: dict[str, dict[str, tuple[float, float]]],
    shares: dict[tuple[str, str], dict[str, float]],
    years: dict[str, float],
    model: dict[str, RoleShrink] | None,
) -> tuple[dict[str, dict[str, tuple[float, float]]], dict[tuple[str, str], float]]:
    """(cid → {role: (value used, sd)}, (cid, role) → k): `values` shrunk toward each role's mean by the
    fitted model. The sd is shrunk with it (it is the sd of the shrunk estimate's input)."""
    if not model:
        return values, {}
    out: dict[str, dict[str, tuple[float, float]]] = {}
    ks: dict[tuple[str, str], float] = {}
    for cid, rs in values.items():
        for role, (v, sd) in rs.items():
            m = model.get(role)
            if m is None:
                out.setdefault(cid, {})[role] = (v, sd)
                continue
            share = (shares.get((cid, role)) or {}).get("ipl", 0.0)
            yrs = years.get(cid, 0.0)
            k = m.k(sd, share, yrs)
            out.setdefault(cid, {})[role] = (m.mu + k * (v - m.mu), abs(k) * sd)
            ks[(cid, role)] = k
    return out, ks


def nan_to(x: float | None, d: float) -> float:
    return d if x is None or (isinstance(x, float) and math.isnan(x)) else float(x)
