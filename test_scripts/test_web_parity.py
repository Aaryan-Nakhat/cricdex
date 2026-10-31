"""Parity lock: the Python web_parity port must reproduce the canonical TS
(`site/src/lib/auction.ts` + Scout look-alike logic) byte-for-byte on the same
exported JSON. If this fails, the desktop surfaces have drifted from the web.

Runs the TS under Node (`--experimental-strip-types`) via
`site/scripts/parity_dump.ts` and diffs against the Python port. Skips (does
not fail) if Node or the exported JSON is unavailable.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from cricdesk import leagues
from cricdesk.config import SITE_DATA
from cricdesk.web_parity import (
    IPL_TEAMS_DEFAULT,
    build_pool,
    default_retentions,
    est_value,
    gem_threshold,
    is_gem,
    load_auction_pool,
    load_retentions,
    load_scout_index,
    market_price,
    retention_inputs,
    scout_price,
    similar_to,
    simulate_auction,
)
from cricdesk.web_parity.pricing import _MODEL_PATHS, load_price_model, market_features
from cricdesk.web_parity.scout import slot_band

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"
TOL = 1e-9


def _node_dump() -> dict:
    if shutil.which("node") is None:
        pytest.skip("node not on PATH")
    if not (SITE_DATA / "ipl" / "auction_pool.json").exists():
        pytest.skip("exported JSON missing — run scripts/export_site.py")
    # Both sides price from the same registry: hand the TS the Python payload of config/leagues.toml.
    with tempfile.TemporaryDirectory() as tmp:
        reg = Path(tmp) / "leagues.json"
        reg.write_text(json.dumps(leagues.site_payload()), encoding="utf-8")
        r = subprocess.run(
            ["node", "--no-warnings", "--experimental-strip-types", "scripts/parity_dump.ts"],
            cwd=SITE,
            capture_output=True,
            text=True,
            env={
                **os.environ,
                "CRICDESK_LEAGUES_JSON": str(reg),
                "CRICDESK_SITE_DATA": str(SITE_DATA),
                **_model_env(),
            },
        )
    if r.returncode != 0:
        pytest.skip(f"node strip-types unavailable / TS failed:\n{r.stderr[-500:]}")
    return json.loads(r.stdout)


def _model_env() -> dict[str, str]:
    """Hand the TS the same market-price model file the Python reads (config/price_model.json)."""
    for p in _MODEL_PATHS:
        if p.exists():
            return {"CRICDESK_PRICE_MODEL_JSON": str(p)}
    return {"CRICDESK_PRICE_MODEL_JSON": str(ROOT / "no-price-model.json")}


# mirrored in site/scripts/parity_dump.ts (MARKET_CASES)
MARKET_CASES = [
    ({"price_value": 13.6, "value_sd": 2.75, "role": "batter", "is_overseas": False, "intl_caps": 555, "age": 38.1, "ipl_balls": 8400, "ipl_seasons": 19, "ipl_gap": 0.55, "target_balls": 6926, "captain_ipl_last": 0, "captain_ipl_seasons": 10, "captain_intl_2y": 0, "prior_share": 0.175, "prior_years": 2, "prior_retained": True, "wiki_views": 2500000.0}, "mini", 125),
    ({"price_value": 59.7, "value_sd": 12.5, "role": "batter", "is_overseas": False, "intl_caps": 0, "age": 15.7, "ipl_balls": 449, "ipl_seasons": 2, "ipl_gap": 0.55, "target_balls": 449}, "mini", 125),
    ({"price_value": 23.2, "value_sd": 2.7, "role": "bowler", "overseas": False, "intl_caps": 210, "age": 32.9, "ipl_balls": 3100, "ipl_seasons": 12, "ipl_gap": 0.55, "target_balls": 3000, "captain_ipl_last": 1, "captain_ipl_seasons": 1, "captain_intl_2y": 1, "prior_share": 0.9, "prior_years": 9, "prior_retained": False, "wiki_views": 41234.5}, "mega", 120),
    ({"price_value": 6.0, "value_sd": 9.0, "role": "all_rounder", "is_overseas": True, "intl_caps": 40, "age": 27.2, "ipl_balls": 0, "ipl_seasons": 0, "ipl_gap": None, "target_balls": 0}, "mini", 125),
    ({"price_value": None, "role": "keeper", "is_overseas": False, "intl_caps": None, "age": None, "ipl_balls": None, "ipl_seasons": None, "ipl_gap": 3.2}, "mega", 90),
    ({"price_value": -45, "value_sd": 20, "role": "bowler", "is_overseas": True, "intl_caps": 3, "age": 41, "ipl_balls": 120, "ipl_seasons": 1, "ipl_gap": 9.5, "target_balls": 120, "prior_share": 0, "prior_years": 3, "prior_retained": True}, "mini", 125),
    ({"price_value": 18.5, "value_sd": 3.1, "role": "keeper", "is_overseas": True, "intl_caps": 160, "intl_caps_2y": 30, "age": 33.5, "ipl_balls": 2600, "ipl_seasons": 9, "ipl_gap": 0.6, "target_balls": 2500, "prior_share": 0.0001, "prior_years": 1, "wiki_views": 0}, "mega", 120),
    # resold a season after his last auction (the resale rule, 2026-10-29): a sale and a retention
    ({"price_value": 3.0, "value_sd": 6.0, "role": "batter", "is_overseas": False, "intl_caps": 0, "age": 20.4, "ipl_balls": 90, "ipl_seasons": 1, "ipl_gap": 0.6, "target_balls": 90, "prior_share": 0.1136, "prior_years": 1, "prior_retained": False}, "mini", 125),
    ({"price_value": 12.0, "value_sd": 3.0, "role": "bowler", "is_overseas": True, "intl_caps": 60, "intl_caps_2y": 20, "age": 23.0, "ipl_balls": 1500, "ipl_seasons": 4, "ipl_gap": 0.6, "target_balls": 1500, "prior_share": 0.108, "prior_years": 1, "prior_retained": True}, "mini", 125),
    # the price input's own sd (2026-10-23: the pool's value_sd is the translated blend's)
    ({"price_value": 21.0, "price_value_sd": 9.0, "value_sd": 2.0, "role": "batter", "is_overseas": False, "intl_caps": 4, "age": 24.0, "ipl_balls": 300, "ipl_seasons": 2, "ipl_gap": 0.6, "target_balls": 300}, "mini", 125),
    ({"price_value": 21.0, "price_value_sd": None, "value_sd": 2.0, "role": "batter", "is_overseas": False, "intl_caps": 4, "age": 24.0, "ipl_balls": 300, "ipl_seasons": 2, "ipl_gap": 0.6, "target_balls": 300}, "mini", 125),
]  # fmt: skip
# mirrored in site/scripts/parity_dump.ts (SCOUT_CASES): Scout prices on fixed rows — translated
# (`ipl_value`) with and without the market inputs, with the price recipe's own input, and a row
# exported before the translation (no `ipl_value`)
SCOUT_CASES = [
    {"value": 30.0, "value_sd": 8.0, "ipl_value": 9.5, "ipl_value_sd": 12.0, "role": "batter", "target_balls": 0},
    {"value": 30.0, "value_sd": 8.0, "ipl_value": 9.5, "ipl_value_sd": 12.0, "price_value": 13.0, "price_value_sd": 10.3, "role": "batter", "target_balls": 0, "is_overseas": False, "intl_caps": 0, "age": 23.0, "ipl_balls": 0, "ipl_seasons": 0, "ipl_gap": None},
    {"value": 12.0, "value_sd": 5.0, "ipl_value": 4.0, "ipl_value_sd": 9.0, "role": "bowler", "target_balls": 0, "is_overseas": True, "intl_caps": 12, "age": 27.0, "ipl_balls": 0, "ipl_seasons": 0, "ipl_gap": None},
    {"value": 12.0, "value_sd": 5.0, "role": "bowler", "target_balls": 40},
]  # fmt: skip


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
    ri = retention_inputs(ret)
    mega_ids = ri["mega_ids"]
    teams = IPL_TEAMS_DEFAULT
    retentions = default_retentions(pool, teams, "mega", mega_ids)

    # 1) retention builder parity (mega: the real lists; mini: top 18 by expected season value)
    _approx_eq(retentions, js["retentions"], "retentions")
    mini = default_retentions(pool, teams, "mini", mega_ids)
    _approx_eq(mini, js["retentionsMini"], "retentionsMini")

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
            "real_prices": ri["real_prices"],
            "retention_slabs": ri["retention_slabs"],
            "slab_holders": ri["slab_holders"],
            "fixed_retained": ri["fixed_retained"],
        },
    )
    assert res["pool_size"] == js["poolSize"]
    assert res["auctioned"] == js["auctioned"]
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
    # every Scout pool in the registry that the export has, in registry order
    tiers = [lg.tier for lg in leagues.scout_pools() if lg.tier in scout]
    assert tiers == js["scoutTiers"]
    assert len(tiers) >= 2, "the export has fewer than two Scout pools"
    for tier in tiers:
        rows = similar_to(sel, scout[tier], sel["role"], "")
        py = [
            {
                "id": r["cricsheet_id"],
                "sim": r["sim"],
                "price": scout_price(r),
            }
            for r in rows
        ]
        _approx_eq(py, js["scout"][tier], f"scout.{tier}")

    # 3b) same-type matching (seam/spin for all-rounders) + own slot + country modes
    gem_lg = leagues.gem_pool()
    gem_tier = gem_lg.tier if gem_lg else None
    by_id = {p["cricsheet_id"]: p for p in scout["ipl"]}
    picks = [by_id[c] for c in js["scoutTypedPicks"]]
    assert picks, "no bowling all-rounder to exercise same-type matching"
    for pick in picks:
        for tier in tiers:
            for mode in ("same", "overseas", "all"):
                fb = pick["country"] if tier == gem_tier else None
                rows = similar_to(
                    pick, scout[tier], "", "same", 8, country=mode, fallback_country=fb
                )
                key = f"{pick['cricsheet_id']}|{tier}|{mode}"
                want = js["scoutTyped"][key]
                got = [f"{r['cricsheet_id']}:{r['sim']}" for r in rows]
                assert [g.split(":")[0] for g in got] == [w.split(":")[0] for w in want], key
                for g, w in zip(got, want, strict=True):
                    assert abs(float(g.split(":")[1]) - float(w.split(":")[1])) <= TOL, key
                # never a different bowling type, never a different slot
                for r in rows:
                    assert r["bowling_category"] == pick["bowling_category"], key
                    assert slot_band(r["batting_position"]) == slot_band(
                        pick["batting_position"]
                    ), key

    # 4) uncapped-gem cutoff + flags (lib/scout.ts gemThreshold / isGem)
    gem_lg = leagues.gem_pool()
    gem_pool = scout.get(gem_lg.tier, []) if gem_lg else []
    med = gem_threshold(gem_pool)
    assert med == js["gemMedian"]
    assert [p["cricsheet_id"] for p in gem_pool if is_gem(p, med)] == js["gems"]

    # 4b) the calibration's top tail (hi_slope), the saturating link and the slab-rule retention
    # charge, on fixed inputs (mirrored in parity_dump.ts)
    from cricdesk.web_parity.auction import retention_spend
    from cricdesk.web_parity.pricing import calibrate, link_share

    cal_part = {"intercept": 0, "coef": {}, "shift": -0.1,
                "calibration": {"x": [-4, -3, -1.5], "y": [-4.2, -3.1, -2.2], "hi_slope": 0.4}}  # fmt: skip
    _approx_eq(
        [calibrate(cal_part, x) for x in (-6, -4, -3.5, -1.5, -1.0, 0.5)], js["calCases"], "cal"
    )
    sat = {"intercept": 0, "coef": {}, "link": {"kind": "sat", "cap_share": 0.3}}
    _approx_eq([link_share(sat, x) for x in (-40, -5, -1, 0, 2, 30)], js["linkCases"], "link")
    slab_opts = {
        "purse": 120, "squad_size": 25, "overseas_cap": 8, "trials": 1, "mode": "mega",
        "retentions": {}, "real_prices": {"a": 13, "b": 12, "c": 12, "d": 12, "e": 4},
        "retention_slabs": {"capped": [18, 14, 11, 18, 14], "uncapped": 4},
        "slab_holders": {"a": "capped", "b": "capped", "c": "capped", "d": "capped",
                         "e": "uncapped"},
        "fixed_retained": {"KKR": [{"salary": 4, "slab_holder": "uncapped"}]},
    }  # fmt: skip
    sp = [{"cricsheet_id": i} for i in "abcde"]
    py_slab = [
        retention_spend("KKR", sp, slab_opts),
        retention_spend("KKR", sp[:3], slab_opts),
        retention_spend("XYZ", sp, {**slab_opts, "retention_slabs": None}),
        retention_spend("KKR", sp, {**slab_opts, "mode": "mini"}),
        # a mini auction charged as Keep or release does (contracts, the 2025 holders by the slab
        # rule, a kept player outside the pool, a player from outside the squads at his price)
        retention_spend(
            "KKR",
            sp + [{"cricsheet_id": "z", "projected_value": 2.5}],
            {
                **slab_opts,
                "mode": "mini",
                "mini_squad": {
                    "a": {"salary": 13, "slab_holder": "capped"},
                    "b": {"salary": 12, "slab_holder": "capped"},
                    "c": {"salary": 3, "slab_holder": None},
                    "d": {"salary": 0.3, "slab_holder": None},
                    "e": {"salary": 4, "slab_holder": "uncapped"},
                },
                "mini_fixed": {"KKR": [{"salary": 1.5, "slab_holder": None}]},
                "mini_rules": {
                    "retained_cost": "slabs",
                    "retention_slabs": [18, 14, 11, 18, 14],
                    "uncapped_retention_slab": 4,
                },
            },
        ),
    ]
    _approx_eq([{"total": t, "each": e} for t, e in py_slab], js["slabSpend"], "slabSpend")
    # KKR's real 2025 charge: 18 + 14 + 11 + 18 + 4 + 4 = 69 cr, not the 57 cr of salaries
    assert py_slab[0][0] == 69
    # mini: holders max(18 + 14 + 4, 29) = 36, plus 3 + 0.3 + 1.5 (outside the pool) + 2.5 (drafted)
    assert py_slab[4][0] == 43.3

    # 5) the cautious price (value − PRICE_CAUTION_SD × value_sd) under the IPL-evidence ceiling,
    # on fixed inputs (value on the IPL scale, role, value_sd, target-league balls)
    cases = [
        (0, "batter", 0, 0),
        (13.6, "batter", 2.75, 6926),
        (59.7, "batter", 12.5, 449),
        (27.7, "keeper", 12.4, 471),
        (27.4, "keeper", 4.9, 163),
        (40.0, "all_rounder", 9.0, None),
        (-30, "bowler", 7.0, 0),
        (10, "bowler", None, 600),
    ]
    _approx_eq([est_value(*c) for c in cases], js["estCases"], "estCases")

    # 6) the market price (fitted to real auctions): features, price and P(bought) on fixed inputs,
    # and every pool row's market / on-field price and P(bought)
    load_price_model.cache_clear()
    if load_price_model() is None:
        assert js["marketCases"] is None
    else:
        pv_max = load_price_model()["price"].get("pv_max")
        py_market = [
            {
                "features": market_features(row, cycle, pv_max),
                **market_price(row, {"cycle": cycle, "purse": purse}),
            }
            for row, cycle, purse in MARKET_CASES
        ]
        _approx_eq(py_market, js["marketCases"], "marketCases")
    _approx_eq([scout_price(r) for r in SCOUT_CASES], js["scoutCases"], "scoutCases")
    _approx_eq(
        [
            [
                p["cricsheet_id"],
                p["projected_value"],
                p["onfield_value"],
                p["p_bought"],
                p["captain"],
            ]
            for p in pool
        ],
        js["poolPrices"],
        "poolPrices",
    )
