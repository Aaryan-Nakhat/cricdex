"""Parity lock: the Python head-to-head engine (`scout/ratings/head_to_head.py`)
must match the web engine (`site/src/lib/headtohead.ts`) on the same ratings —
same probabilities, sds, components and verdict wording.

Runs `site/scripts/h2h_parity_dump.ts` under Node on a fixture of synthetic rows
(every file format and edge case: current `value_sd`, older dismissal-aware,
legacy runs-only, missing / zero sd, all-rounders) plus real exported IPL
ratings when present. Skips if Node is unavailable.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
from test_web_parity import _approx_eq  # test_scripts/ is on sys.path (rootdir import mode)

from cricdesk.scout.ratings import head_to_head as h2h

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"


def _row(cid, role, skill, sd, second=None, second_sd=None, value=None, value_sd=None, balls=500):
    r = {"cricsheet_id": cid, "unique_name": f"Player {cid}", "role": role, "skill": skill}
    r["skill_sd"] = sd
    if second is not None:
        r["survival_skill" if role == "batter" else "strike_skill"] = second
        r["survival_skill_sd" if role == "batter" else "strike_skill_sd"] = second_sd
    if value is not None:
        r["value"] = value
    if value_sd is not None:
        r["value_sd"] = value_sd
    r["balls"] = balls
    return r


SYNTHETIC = [
    # current files: value + value_sd, batting and bowling (all-rounders)
    _row("n1", "batter", 0.10, 0.04, 0.20, 0.05, 1.8, 0.31, balls=2400),
    _row("n1", "bowler", 0.02, 0.05, 0.05, 0.06, 0.4, 0.42, balls=900),
    _row("n2", "batter", 0.05, 0.05, 0.10, 0.06, 1.1, 0.35, balls=1800),
    _row("n2", "bowler", 0.08, 0.04, 0.12, 0.05, 1.2, 0.33, balls=1500),
    _row("n3", "batter", 0.11, 0.04, 0.19, 0.05, 1.78, 0.30, balls=2600),
    # missing / zero sd -> unknown -> no comparison
    _row("n4", "batter", 0.10, 0.04, 0.20, None, 1.5, None),
    _row("n5", "batter", 0.10, 0.04, 0.20, 0.05, 1.5, 0.0),
    # older dismissal-aware files (no value_sd): raw sum, variances add
    _row("o1", "batter", 0.20, 0.05, 0.10, 0.06, 0.30),
    _row("o2", "batter", 0.05, 0.05, 0.25, 0.06, 0.30),
    _row("o3", "bowler", 0.20, 0.05, -0.05, None, 0.15),
    _row("o4", "bowler", 0.05, 0.05, 0.35, 0.06, 0.40),
    # legacy runs-only files
    _row("l1", "batter", 0.20, 0.10),
    _row("l1", "bowler", 0.10, 0.10),
    _row("l2", "batter", 0.00, 0.10),
    _row("l2", "bowler", 0.00, 0.10),
    _row("l3", "batter", 0.00, None),
]
PAIRS = [
    ("n1", "n2"),
    ("n2", "n1"),
    ("n1", "n3"),
    ("n1", "n4"),
    ("n1", "n5"),
    ("o1", "o2"),
    ("o3", "o4"),
    ("l1", "l2"),
    ("l1", "l3"),
    ("n1", "l1"),  # different file formats -> not comparable
    ("o1", "n2"),
    ("n1", "missing"),
]


def _real_rows() -> tuple[list[dict], list[tuple[str, str]]]:
    f = SITE / "public" / "data" / "ipl" / "ratings.json"
    if not f.exists():
        return [], []
    rows = json.loads(f.read_text(encoding="utf-8"))
    ids = sorted({r["cricsheet_id"] for r in rows if r.get("unique_name")})[:60]
    keep = set(ids)
    return [r for r in rows if r["cricsheet_id"] in keep], list(zip(ids, ids[1:], strict=False))


def _py_side(rows, pairs, tmp_path, monkeypatch) -> list[dict]:
    (tmp_path / "scout_ratings_parity.json").write_text(json.dumps(rows))
    monkeypatch.setattr(h2h, "METRIC_DIR", tmp_path)
    name = {r["cricsheet_id"]: r["unique_name"] for r in rows}
    out = []
    for a, b in pairs:
        res = h2h.head_to_head(name.get(a, a), name.get(b, b), collection="parity")
        side = {}
        for role in ("batter", "bowler", "all_rounder"):
            c = res["comparisons"][role]
            side[role] = c and {
                "meanA": c["mean_a"],
                "sdA": c["sd_a"],
                "meanB": c["mean_b"],
                "sdB": c["sd_b"],
                "diff": c["diff"],
                "pooledSd": c["pooled_sd"],
                "pAbetter": c["p_a_better"],
                "pBbetter": c["p_b_better"],
                "component": c["component"],
                "ballsA": c["balls_a"],
                "ballsB": c["balls_b"],
                "verdict": c["verdict"],
            }
        out.append(side)
    return out


def test_h2h_parity(tmp_path, monkeypatch):
    if shutil.which("node") is None:
        pytest.skip("node not on PATH")
    real_rows, real_pairs = _real_rows()
    rows, pairs = SYNTHETIC + real_rows, PAIRS + real_pairs
    fixture = tmp_path / "fixture.json"
    fixture.write_text(json.dumps({"rows": rows, "pairs": pairs}))
    r = subprocess.run(
        [
            "node",
            "--no-warnings",
            "--experimental-strip-types",
            "scripts/h2h_parity_dump.ts",
            str(fixture),
        ],
        cwd=SITE,
        capture_output=True,
        text=True,
    )
    if r.returncode != 0:
        pytest.skip(f"node strip-types unavailable / TS failed:\n{r.stderr[-500:]}")
    js = json.loads(r.stdout)
    py = _py_side(rows, pairs, tmp_path, monkeypatch)
    _approx_eq(py, js, "h2h")
    # the fixture really exercises every branch
    n1n2 = py[0]
    assert n1n2["all_rounder"] is not None and n1n2["batter"]["component"] == "scoring + survival"
    assert py[3]["batter"] is None and py[4]["batter"] is None  # unknown sd -> skipped
    assert py[6]["bowler"] is None  # older file with a missing strike sd
    assert py[7]["batter"]["component"] == "scoring only (legacy ratings)"
    assert py[9]["batter"] is None  # legacy vs current file
