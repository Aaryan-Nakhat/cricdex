"""Check the Auction room's simulator against real IPL auctions (docs/AUCTION_MATH.md Part 3).

The bidding itself is fitted by `scripts/auction_demand_fit.py` (a demand model estimated on who bought each
lot and at what price; nothing is tuned here). This script replays each real auction with the simulator
and that model, using only what the protocol allows: the inputs of `scripts/auction_demand_fit.py inputs`
(walk-forward contributions and P(plays), the real retentions and purses, every sold lot at his real base
price plus the unsold alternatives), each lot's market price from the other 2018-2024 auctions for the
2019-2024 replays and from the auctions before for the 2025 / 2026 test, the demand model fitted on
2019-2024 (`params_le2024`). All ten franchises bid, `--trials` runs each, and each sold lot's simulated
clearing price is set against what he really sold for:

* level and error on the contested lots (sold, and priced by the market model at 2× base or more: chosen
  by the predictor, not the outcome), the share of real prices inside the simulated 10-90% range (overall
  and by real price band), the 10 lots the simulation prices highest against their real price;
* who bought him: the share of lots whose real buyer is the simulation's most frequent buyer;
* each team's purse left and squad size, simulated against real;
* the dearest simulated lots against the real top of the auction (the reality check).

    uv run python scripts/auction_calibrate.py --work <dir> [--trials 200] [--out report.json]
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np
import typer

sys.path.insert(0, str(Path(__file__).resolve().parent))

import auction_demand_fit as adf  # noqa: E402

from cricdex.web_parity.auction import one_trial  # noqa: E402

app = typer.Typer(add_completion=False)
CONTEST = 2.0  # scored lots: market price ≥ CONTEST × base price (the model expects a contest)
BANDS = ((0, 1.0), (1.0, 3.0), (3.0, 8.0), (8.0, 99.0))


def demand_of(params: dict) -> dict:
    return {k: v for k, v in params.items() if not isinstance(v, dict)}


def replay(si: dict, demand: dict, trials: int, sim=one_trial, extra: dict | None = None) -> dict:
    """Each lot's clearing price and buyer in each run (base price, no buyer, when unsold), and each
    team's spend and squad size per run."""
    bases = []
    for t, v in sorted(si["teams"].items()):
        bases.append({
            "team": t,
            "retained": [{"cricsheet_id": p["id"], "role": p["role"], "is_overseas": p["os"], "v": p["v"]}
                         for p in v["kept"]],
            "retain_spend": v["cost"], "retain_overseas": sum(1 for p in v["kept"] if p["os"]),
        })  # fmt: skip
    lots = [{k: x for k, x in r.items() if not k.startswith("_")} for r in si["avail"]]
    idx = {r["cricsheet_id"]: i for i, r in enumerate(lots)}
    price = [[float(r["base_price"])] * trials for r in lots]
    buyer: list[list[str | None]] = [[None] * trials for _ in lots]
    min_base = min(float(lot.get("base_price_cr") or 99) for lot in si["lots"])
    opts = {
        "purse": si["purse"], "squad_size": 25, "squad_min": 18, "overseas_cap": 8,
        "mode": si["cycle"], "demand": demand, "min_base": min(min_base, 0.3),
        **(extra or {}),
    }  # fmt: skip
    spend = {b["team"]: [] for b in bases}
    size = {b["team"]: [] for b in bases}
    for t in range(trials):

        def sale(p, i, _b, pr, _t=t):
            price[idx[p["cricsheet_id"]]][_t] = pr
            buyer[idx[p["cricsheet_id"]]][_t] = bases[i]["team"]

        states = sim(bases, lots, opts, 1000 + t * 7919, sale)
        for b, st in zip(bases, states, strict=True):
            spend[b["team"]].append(b["retain_spend"] + st["spent"])
            size[b["team"]].append(len(st["retained"]) + len(st["bought"]))
    return {"price": price, "buyer": buyer, "spend": spend, "size": size}


def metrics(si: dict, rep: dict) -> dict:
    """Scored on the lots that really sold (the unsold are only alternatives in the replay)."""
    sims = rep["price"]
    keep = [i for i, r in enumerate(si["avail"]) if r["_price"]]
    real = np.array([si["avail"][i]["_price"] for i in keep])
    S = np.array([sims[i] for i in keep])
    med = np.median(S, axis=1)
    base = np.array([float(si["avail"][i]["base_price"]) for i in keep])
    pit = (np.sum(S < real[:, None], axis=1) + 0.5 * np.sum(S == real[:, None], axis=1)) / S.shape[
        1
    ]
    lo, hi = np.quantile(S, 0.1, axis=1), np.quantile(S, 0.9, axis=1)
    inside = (real >= lo - 1e-9) & (real <= hi + 1e-9)
    mk = np.array([float(si["avail"][i]["projected_value"]) for i in keep])
    c = mk >= CONTEST * base
    top_sim = np.argsort(-med, kind="stable")[:10]
    # who bought him: the simulation's most frequent buyer against the real one (sold lots)
    hit = []
    for i in keep:
        bs = [b for b in rep["buyer"][i] if b]
        if bs:
            hit.append(max(set(bs), key=bs.count) == si["avail"][i]["_sold_to"])
    by_band = {}
    for a, b in BANDS:
        m = (real >= a) & (real < b)
        if m.any():
            by_band[f"{a:g}-{b:g}"] = {"n": int(m.sum()), "inside_10_90": float(np.mean(inside[m])),
                                       "median_real_over_sim": float(np.median(real[m] / med[m]))}  # fmt: skip
    teams = {}
    for t, v in rep["spend"].items():
        real_spend = float(si["teams"][t]["cost"]) + sum(
            float(x["price_cr"]) for x in si["lots"] if x["team"] == t
        )
        real_size = len(si["teams"][t]["kept"]) + sum(1 for x in si["lots"] if x["team"] == t)
        teams[t] = {"left_sim": float(si["purse"] - np.mean(v)), "left_real": float(si["purse"] - real_spend),
                    "size_sim": float(np.mean(rep["size"][t])), "size_real": real_size}  # fmt: skip
    return {
        "n": int(len(real)),
        "n_contested": int(c.sum()),
        "log_bias_c": float(np.mean(np.log(real[c]) - np.log(med[c]))),
        "median_ratio_c": float(np.median(real[c] / med[c])),
        "mae_ln_c": float(np.mean(np.abs(np.log(real[c]) - np.log(med[c])))),
        "inside_10_90_c": float(np.mean(inside[c])),
        "inside_10_90": float(np.mean(inside)),
        "mae_ln": float(np.mean(np.abs(np.log(real) - np.log(med)))),
        "median_ratio": float(np.median(real / med)),
        "top10_sim_ratio": float(np.exp(np.mean(np.log(med[top_sim] / real[top_sim])))),
        "buyer_hit": float(np.mean(hit)) if hit else None,
        "by_band": by_band,
        "teams": teams,
        "pit": [round(float(x), 3) for x in pit],
        "names": [si["avail"][i]["name"] for i in keep],
        "real": [float(x) for x in real],
        "sim_median": [float(x) for x in med],
        "sim_p10": [float(x) for x in lo],
        "sim_p90": [float(x) for x in hi],
    }


@app.command()
def main(
    work: Path = typer.Option(..., "--work"),
    trials: int = typer.Option(200, "--trials"),
    out: Path | None = typer.Option(None, "--out"),
) -> None:
    t0 = time.time()
    cfg = json.loads(adf.OUT.read_text(encoding="utf-8"))
    demand = demand_of(cfg["params_le2024"])
    report: dict = {"demand": demand, "seasons": {}}
    for s in adf.SEASONS:
        adf.MK_SOURCE["mode"] = "mk24" if s in adf.SELECT else "walk"
        si = adf.load_season(work, s)
        m = metrics(si, replay(si, demand, trials))
        report["seasons"][s] = m
        print(s, {k: (round(v, 3) if isinstance(v, float) else v) for k, v in m.items()
                  if k not in ("pit", "names", "real", "sim_median", "sim_p10", "sim_p90", "teams")},
              f"({time.time() - t0:.0f}s)", flush=True)  # fmt: skip
    adf.MK_SOURCE["mode"] = "walk"
    if out:
        out.write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(f"done in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    app()
