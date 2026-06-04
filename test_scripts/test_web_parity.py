"""Parity lock: the Python web_parity port must reproduce the canonical TS
(`site/src/lib/auction.ts` + Scout look-alike logic) byte-for-byte on the same
exported JSON. If this fails, the desktop surfaces have drifted from the web.

Runs the TS under Node (`--experimental-strip-types`) via
`site/scripts/parity_dump.ts` and diffs against the Python port. Skips (does
not fail) if Node or the exported JSON is unavailable.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from cricdex.web_parity import (
    IPL_TEAMS_DEFAULT,
    build_pool,
    default_retentions,
    est_value,
    load_auction_pool,
    load_retentions,
    load_scout_index,
    similar_to,
    simulate_auction,
)

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"
TOL = 1e-9


def _node_dump() -> dict:
    if shutil.which("node") is None:
        pytest.skip("node not on PATH")
    if not (SITE / "public" / "data" / "ipl" / "auction_pool.json").exists():
        pytest.skip("exported JSON missing — run scripts/export_site.py")
    r = subprocess.run(
        ["node", "--no-warnings", "--experimental-strip-types", "scripts/parity_dump.ts"],
        cwd=SITE,
        capture_output=True,
        text=True,
    )
    if r.returncode != 0:
        pytest.skip(f"node strip-types unavailable / TS failed:\n{r.stderr[-500:]}")
    return json.loads(r.stdout)


def _approx_eq(a, b, path="") -> None:
    """Recursive deep-equal with float tolerance; raises AssertionError with a
    breadcrumb on the first mismatch."""
    if isinstance(a, bool) or isinstance(b, bool):
        assert a == b, f"{path}: {a!r} != {b!r}"
    elif isinstance(a, int | float) and isinstance(b, int | float):
        assert abs(a - b) <= TOL, f"{path}: {a!r} != {b!r}"
    elif isinstance(a, dict) and isinstance(b, dict):
        assert set(a) == set(b), f"{path}: keys {set(a) ^ set(b)}"
        for k in a:
            _approx_eq(a[k], b[k], f"{path}.{k}")
    elif isinstance(a, list) and isinstance(b, list):
        assert len(a) == len(b), f"{path}: len {len(a)} != {len(b)}"
        for i, (x, y) in enumerate(zip(a, b, strict=False)):
            _approx_eq(x, y, f"{path}[{i}]")
    else:
        assert a == b, f"{path}: {a!r} != {b!r}"


def test_web_parity():
    js = _node_dump()

    pool = build_pool(load_auction_pool("ipl"))
    ret = load_retentions("ipl")
    mega_ids = {t: [r["cricsheet_id"] for r in rows] for t, rows in ret["mega"].items()}
    real_prices = {r["cricsheet_id"]: r["price"] for rows in ret["mega"].values() for r in rows}
    teams = IPL_TEAMS_DEFAULT
    retentions = default_retentions(pool, teams, "mega", mega_ids)

    # 1) retention builder parity
    _approx_eq(retentions, js["retentions"], "retentions")

    # 2) auction simulation parity (same seeds, same trials)
    res = simulate_auction(
        pool,
        teams,
        {
            "purse": 120,
            "squad_size": 25,
            "overseas_cap": 8,
            "trials": 40,
            "mode": "mega",
            "retentions": retentions,
            "real_prices": real_prices,
        },
    )
    assert res["pool_size"] == js["poolSize"]
    py_teams = [
        {
            "team": t["team"],
            "retained": t["retained"],
            "avgBought": t["avg_bought"],
            "avgSpend": t["avg_spend"],
            "avgValue": t["avg_value"],
            "avgOverseas": t["avg_overseas"],
        }
        for t in res["teams"]
    ]
    _approx_eq(py_teams, js["teams"], "teams")
    py_marquee = [
        {
            "id": m["player"]["cricsheet_id"],
            "winners": [{"team": w["team"], "pct": w["pct"]} for w in m["winners"]],
        }
        for m in res["marquee"]
    ]
    _approx_eq(py_marquee, js["marquee"], "marquee")
    py_outcomes = [
        {
            "id": o["cricsheet_id"],
            "status": o["status"],
            "team": o["team"],
            "soldPct": o["soldPct"],
            "avgPrice": o["avgPrice"],
            "winners": [{"team": w["team"], "pct": w["pct"]} for w in o["winners"]],
        }
        for o in res["outcomes"]
    ]
    _approx_eq(py_outcomes, js["outcomes"], "outcomes")
    py_draft = [
        {
            "team": s["team"],
            "bought": [p["cricsheet_id"] for p in s["bought"]],
            "spent": s["spent"],
            "overseas": s["overseas"],
        }
        for s in res["sample_draft"]
    ]
    _approx_eq(py_draft, js["sampleDraft"], "sampleDraft")

    # 3) scout look-alike + pricing parity
    scout = load_scout_index("ipl")
    sel = sorted(scout["ipl"], key=lambda p: p["cricsheet_id"])[0]
    assert sel["cricsheet_id"] == js["scoutPick"]
    for tier in ("ipl", "smat", "bbl"):
        rows = similar_to(sel, scout[tier], sel["role"], "")
        py = [
            {
                "id": r["cricsheet_id"],
                "sim": r["sim"],
                "price": est_value(r["value"], r["role"], tier),
            }
            for r in rows
        ]
        _approx_eq(py, js["scout"][tier], f"scout.{tier}")
