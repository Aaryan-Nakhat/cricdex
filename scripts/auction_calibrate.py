"""Calibrate the auction simulator's bidding to real IPL auctions (docs/AUCTION_MATH.md Part 3b).

Each real auction is replayed with only what was known before it (the inputs of
`scripts/bidplan_backtest.py`: walk-forward values, a price model fitted on the earlier auctions, the real
retentions and purses, every sold lot with a Cricsheet id at his real base price). All ten franchises bid in
the Auction room's simulator (their personalities, budget pressure, role needs), `--trials` runs each, and
each lot's simulated clearing price is set against what he really sold for.

The parameters (auction.py `BID_LEVEL`, `BID_CURVE`, `LOT_HYPE_SD` ⇄ auction.ts):

* `level_mega`, `level_mini`: a team's bid as a multiple of the market price, per auction type;
* `curve`: the exponent on the market price around 1 cr (> 1 stretches the top);
* `sd`: the per-lot demand shock (ln sd), shared by every team in a run;
* `anchor`: the weight on a player's last IPL price where it is known (a reference price);
* `tight`: market tightness on / off (money left with the teams that have places ÷ the market value of the
  best unsold players who would fill them).

Each replay pool is the auction's sold lots plus its unsold alternatives (recent IPL players neither
retained nor bought: the P(bought) risk set); it is scored on the sold lots. Fitted on the calibration
auctions (mega: 2022; mini: 2023, 2024) by grid search: for each (curve, sd, anchor, tight) the level per
auction type with the smallest mean log error (real ÷ simulated median) on the contested lots (sold, and
priced by the market model at 2× base or more: chosen by the predictor, not the outcome), then the
combination with the lowest loss (`loss`). Selecting lots by their real price (a "contested" or "10 cr+" set) would always show
any model below them, so the top-end check uses the lots the simulation prices highest. Then tested out of time on the 2025 mega and 2026 mini auctions.

    uv run python scripts/auction_calibrate.py --work <dir> [--trials 60] [--out calib.json]
"""

from __future__ import annotations

import json
import math
import pickle
import sys
import time
from pathlib import Path

import numpy as np
import typer

sys.path.insert(0, str(Path(__file__).resolve().parent))

import bidplan_backtest as bt  # noqa: E402
import ipl_price_model as ipm  # noqa: E402

from cricdex.scout.identity import master  # noqa: E402
from cricdex.web_parity.auction import IPL_TEAMS_DEFAULT, one_trial  # noqa: E402

app = typer.Typer(add_completion=False)
CALIB = (2022, 2023, 2024)
TEST = (2025, 2026)
CURVES = (0.6, 0.75, 0.9, 1.0)
SDS = (0.6, 0.8, 1.0, 1.2)
ANCHORS = (0.0, 0.3, 0.6)
TIGHTS = (1,)  # off was worse at every level tried (it leaves stars soaking up purses)
CONTEST = 2.0  # scored lots: market price ≥ CONTEST × base price (the model expects a contest)
LEVELS = tuple(round(0.5 * 1.2**k, 4) for k in range(12))  # 0.5 … ~3.7


def _inputs(work: Path) -> dict:
    f = work / "season_inputs.pkl"
    if f.exists():
        return pickle.loads(f.read_bytes())
    ipm.AUCTIONS_DATES.update(ipm.auction_dates())
    price_rows, risk_rows, hist, ret_rows = ipm.build_rows()
    pm = master.load()
    apps = ipm.ipl_appearances()
    tags = bt._tags_fn()
    out = {}
    for s in CALIB + TEST:
        si = bt._season_inputs(s, (price_rows, ret_rows, risk_rows), hist, pm, apps, tags)
        out[s] = {k: si[k] for k in ("season", "purse", "cycle", "avail", "teams")}
        print(f"{s}: {len(si['avail'])} lots, {len(si['teams'])} teams", flush=True)
    f.write_bytes(pickle.dumps(out))
    return out


def replay(si: dict, calib: dict, trials: int) -> list[list[float]]:
    """Each lot's clearing price in each run (base price when unsold), all ten teams bidding."""
    pers = {c["team"]: c["personality"] for c in IPL_TEAMS_DEFAULT}
    bases = []
    for t, v in sorted(si["teams"].items()):
        bases.append({
            "team": t, "personality": pers.get(t, "Balanced"),
            "retained": [{"cricsheet_id": p["id"], "role": p["role"], "is_overseas": p["os"]} for p in v["kept"]],
            "retain_spend": v["cost"], "retain_overseas": sum(1 for p in v["kept"] if p["os"]),
        })  # fmt: skip
    lots = [{k: x for k, x in r.items() if not k.startswith("_")} for r in si["avail"]]
    idx = {r["cricsheet_id"]: i for i, r in enumerate(lots)}
    out = [[float(r["base_price"])] * trials for r in lots]
    opts = {
        "purse": si["purse"],
        "squad_size": 25,
        "overseas_cap": 8,
        "mode": si["cycle"],
        "calib": calib,
    }
    for t in range(trials):

        def sale(p, _i, _b, price, _t=t):
            out[idx[p["cricsheet_id"]]][_t] = price

        one_trial(bases, lots, opts, 1000 + t * 7919, sale)
    return out


def _rank(x: np.ndarray) -> np.ndarray:
    r = np.empty(len(x))
    r[np.argsort(x, kind="stable")] = np.arange(len(x))
    return r


def spearman(a, b) -> float:
    a, b = _rank(np.asarray(a, float)), _rank(np.asarray(b, float))
    return float(np.corrcoef(a, b)[0, 1])


def metrics(si: dict, sims: list[list[float]]) -> dict:
    """Scored on the lots that really sold (the unsold are only alternatives in the replay)."""
    keep = [i for i, r in enumerate(si["avail"]) if r["_price"]]
    sims = [sims[i] for i in keep]
    real = np.array([si["avail"][i]["_price"] for i in keep])
    med = np.array([float(np.median(s)) for s in sims])
    base = np.array([float(si["avail"][i]["base_price"]) for i in keep])
    pit = np.array([(np.sum(np.array(s) < r) + 0.5 * np.sum(np.array(s) == r)) / len(s)
                    for s, r in zip(sims, real, strict=True)])  # fmt: skip
    top = np.argsort(-real)[:10]
    top_sim = np.argsort(-med, kind="stable")[:10]
    # the scored set, chosen by the predictor (not the outcome): sold lots the market model expects to be
    # contested. Lots it prices at base are mostly uncapped players it knows little about; the ones real
    # teams fought over (scouted) pull any sold-only score up, whatever the bidding.
    mk = np.array([float(si["avail"][i]["projected_value"]) for i in keep])
    c = mk >= CONTEST * base
    return {
        "n_contested": int(c.sum()),
        "log_bias_c": float(np.mean(np.log(real[c]) - np.log(med[c]))),
        "median_ratio_c": float(np.median(real[c] / med[c])),
        "mae_ln_c": float(np.mean(np.abs(np.log(real[c]) - np.log(med[c])))),
        "rank_corr_c": spearman(real[c], med[c]),
        "inside_10_90_c": float(np.mean((pit[c] >= 0.1) & (pit[c] <= 0.9))),
        "n": int(len(real)),
        "median_ratio": float(np.median(real / med)),  # real ÷ simulated median (1 = right level)
        # the same over the contested lots (sold above base price): most others sit at base either way
        "median_ratio_contested": float(np.median((real / med)[real > base * 1.05])),
        "log_bias": float(
            np.mean(np.log(real) - np.log(med))
        ),  # > 0: real prices above the simulation
        "mae_ln": float(np.mean(np.abs(np.log(real) - np.log(med)))),
        "rank_corr": spearman(real, med),
        "top10_ratio": float(
            np.exp(np.mean(np.log(med[top] / real[top])))
        ),  # simulated ÷ real, top by real
        # the same for the 10 lots the simulation prices highest: selecting by real price always shows any
        # model below them (regression to the mean), so this is the fair "top lots right" check
        "top10_sim_ratio": float(np.exp(np.mean(np.log(med[top_sim] / real[top_sim])))),
        "inside_10_90": float(np.mean((pit >= 0.1) & (pit <= 0.9))),
        "below_median": float(
            np.mean(pit > 0.5)
        ),  # share of lots whose real price beat the sim median
        "pit": [round(float(x), 3) for x in pit],
    }


def loss(ms: list[dict]) -> float:
    """On the contested lots: level (log bias²), lot-by-lot error (MAE ln) and calibration of the spread
    (the share of real prices inside the simulated 10th–90th percentiles against 0.8, ×2); on every sold
    lot, the 10 the simulation prices highest (ln of their simulated ÷ real, squared, half weight)."""
    return sum(
        m["log_bias_c"] ** 2
        + m["mae_ln_c"]
        + 0.5 * math.log(m["top10_sim_ratio"]) ** 2
        + 2 * (m["inside_10_90_c"] - 0.8) ** 2
        for m in ms
    )


@app.command()
def main(
    work: Path = typer.Option(..., "--work"),
    trials: int = typer.Option(60, "--trials"),
    out: Path | None = typer.Option(None, "--out"),
) -> None:
    work.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    data = _inputs(work)
    print(f"inputs in {time.time() - t0:.0f}s", flush=True)
    neutral = {
        "level_mega": 1.0,
        "level_mini": 1.0,
        "curve": 1.0,
        "sd": 0.0,
        "anchor": 0.0,
        "tight": 0,
    }
    report: dict = {"neutral": {s: {k: v for k, v in metrics(data[s], replay(data[s], neutral, trials)).items() if k != "pit"}
                                for s in CALIB + TEST}}  # fmt: skip
    print("uncalibrated:", json.dumps(report["neutral"], indent=1), flush=True)
    best = None
    grid = []
    for curve in CURVES:
        for sd in SDS:
            for anchor in ANCHORS:
                for tight in TIGHTS:
                    fit = {}
                    for cyc in ("mega", "mini"):
                        seasons = [x for x in CALIB if data[x]["cycle"] == cyc]
                        bl = None
                        for lv in LEVELS:
                            cal = {**neutral, "curve": curve, "sd": sd, "anchor": anchor, "tight": tight,
                                   f"level_{cyc}": lv}  # fmt: skip
                            ms = [metrics(data[x], replay(data[x], cal, trials)) for x in seasons]
                            e = sum(m["log_bias_c"] * m["n_contested"] for m in ms) ** 2
                            if bl is None or e < bl[0]:
                                bl = (e, lv, ms)
                        fit[cyc] = bl
                    cal = {"level_mega": fit["mega"][1], "level_mini": fit["mini"][1], "curve": curve,
                           "sd": sd, "anchor": anchor, "tight": tight}  # fmt: skip
                    ms = fit["mega"][2] + fit["mini"][2]
                    lo = loss(ms)
                    grid.append({"calib": cal, "loss": lo,
                                 "metrics": [{k: v for k, v in m.items() if k != "pit"} for m in ms]})  # fmt: skip
                    print(f"curve {curve} sd {sd} anchor {anchor} tight {tight}: mega {cal['level_mega']} "
                          f"mini {cal['level_mini']} loss {lo:.3f} ({time.time() - t0:.0f}s)", flush=True)  # fmt: skip
                    if best is None or lo < best[0]:
                        best = (lo, cal)
                    (work / "grid.json").write_text(json.dumps(grid, indent=1), encoding="utf-8")
    cal = best[1]
    report["chosen"] = cal
    report["grid"] = grid
    report["calibration_auctions"] = {
        s: metrics(data[s], replay(data[s], cal, trials * 2)) for s in CALIB
    }
    report["test_auctions"] = {s: metrics(data[s], replay(data[s], cal, trials * 2)) for s in TEST}
    for k in ("calibration_auctions", "test_auctions"):
        for s, m in report[k].items():
            print(
                k,
                s,
                {
                    kk: (round(v, 3) if isinstance(v, float) else v)
                    for kk, v in m.items()
                    if kk != "pit"
                },
            )
    print("chosen:", cal)
    if out:
        out.write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(f"done in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    app()
