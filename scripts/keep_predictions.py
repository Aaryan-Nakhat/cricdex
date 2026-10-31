"""The dated Keep calls for the next retention deadline, written before it (docs/METHODOLOGY.md §10).

Every IPL squad player's chance of being kept and the default call (the same `evaluate` the page and
`cricdesk keep` run, no overrides), from the exported site data. The file is the first true test of the
Keep model: it is written before the deadline and scored once the retained lists are published. It
carries the git commit (and whether the tree had uncommitted changes) and a SHA-256 of every input, so
the calls can be shown to predate the deadline and to come from this model.

    uv run python scripts/keep_predictions.py [--out data/predictions]
"""

from __future__ import annotations

import csv
import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import typer

from cricdesk.config import SITE_DATA
from cricdesk.web_parity import build_pool, load_auction_pool
from cricdesk.web_parity.keep import evaluate, market_for, player_key, squad_of
from cricdesk.web_parity.loader import load_keep

ROOT = Path(__file__).resolve().parents[1]
INPUTS = (
    "config/keep_model.json",
    "site/public/data/ipl/keep.json",
    "site/public/data/ipl/auction_pool.json",
    "scripts/keep_predictions.py",
)


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.strip()


def _sha256(rel: str) -> str:
    return hashlib.sha256((ROOT / rel).read_bytes()).hexdigest()


def main(out: Path = typer.Option(ROOT / "data" / "predictions", "--out")) -> None:
    assert (SITE_DATA / "ipl" / "keep.json").exists(), "export the site data first"
    data = load_keep("ipl")
    pool = build_pool(load_auction_pool("ipl"))
    comp = data["competition"]
    rules = dict(comp["rules"])
    rows = []
    for team in data["teams"]:
        squad = squad_of(data, team)
        market = market_for(
            team, data["players"], pool, data.get("pool_tags") or {}, data.get("form"), rules
        )
        res = evaluate(squad, market, rules, {}, {}, data.get("form"))
        for p in res["players"]:
            rows.append(
                {
                    "team": team,
                    "key": player_key(p),
                    "name": p["name"],
                    "overseas": bool(p.get("overseas")),
                    "salary_cr": p["salary"],
                    "matches_last": p.get("matches_last"),
                    "p_keep": None if p.get("p_keep") is None else round(p["p_keep"], 4),
                    "call": "keep" if p["kept"] else "release",
                    "auto_release": p.get("auto_release"),
                }
            )
    rows.sort(key=lambda r: (r["team"], -(r["p_keep"] or 0), r["name"]))
    model = json.loads((ROOT / "config/keep_model.json").read_text(encoding="utf-8"))
    deadline = comp["retention_deadline"]
    doc = {
        "about": f"Keep calls for the {comp['name']} retention deadline ({deadline}), written before it",
        "written_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "deadline": deadline,
        "git_commit": _git("rev-parse", "HEAD"),
        "git_dirty": bool(_git("status", "--porcelain")),
        "inputs_sha256": {f: _sha256(f) for f in INPUTS},
        "model": {
            "chosen": model["evaluation"]["chosen"],
            **{k: model.get(k) for k in ("fitted", "trained_on", "rows")},
        },
        "score_with": "accuracy, log loss and release precision / recall against the published "
        "retained lists, against keeping everyone (METHODOLOGY §10)",
        "teams": {
            t: {
                "players": sum(r["team"] == t for r in rows),
                "kept": sum(r["team"] == t and r["call"] == "keep" for r in rows),
            }
            for t in data["teams"]
        },
        "players": rows,
    }
    out.mkdir(parents=True, exist_ok=True)
    stem = f"ipl_keep_{comp['season']}"
    (out / f"{stem}.json").write_text(
        json.dumps(doc, indent=1, ensure_ascii=False), encoding="utf-8"
    )
    with (out / f"{stem}.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    kept = sum(r["call"] == "keep" for r in rows)
    print(
        f"{len(rows)} players, {kept} kept, {len(rows) - kept} released -> {out / stem}.json/.csv"
    )


if __name__ == "__main__":
    typer.run(main)
