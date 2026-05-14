"""`cricdex data` — inventory + ingest.

`cricdex data status` shows what's locally available + sizes + last-
updated, so a returning user can tell at a glance what's fresh and
what needs recomputing.

`cricdex data ingest <slice>` triggers the relevant pipeline. Every
ingest skips if its output already exists, unless `--force` is passed.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import typer

from cricdex.cli._shared import EXIT_USER_ERROR, die, render_table
from cricdex.config import DATA_DIR

app = typer.Typer(add_completion=False, no_args_is_help=True)


def _file_info(path: Path) -> dict:
    if not path.exists():
        return {"present": False, "size_mb": 0.0, "mtime": "—"}
    if path.is_dir():
        total = sum(p.stat().st_size for p in path.rglob("*") if p.is_file())
    else:
        total = path.stat().st_size
    mtime = dt.datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds")
    return {"present": True, "size_mb": round(total / 1024 / 1024, 1), "mtime": mtime}


@app.command("status", help="Show what's locally available.")
def status_cmd() -> None:
    rows = []
    targets = [
        ("cricsheet duckdb", DATA_DIR / "cricsheet" / "cricsheet.duckdb"),
        ("rules qdrant index", DATA_DIR / "rules" / "qdrant"),
        ("rules parsed JSONL", DATA_DIR / "rules" / "parsed"),
        ("rules curated JSONL", DATA_DIR / "rules" / "curated"),
        ("rules raw PDFs", DATA_DIR / "rules" / "raw"),
        ("scout NumPyro ratings", DATA_DIR / "metrics" / "scout_ratings_ipl.json"),
        ("metrics outputs", DATA_DIR / "metrics"),
        ("auction GRPO policy", DATA_DIR / "auction" / "policy.zip"),
        ("people register", DATA_DIR / "register" / "people.csv"),
    ]
    for label, path in targets:
        info = _file_info(path)
        rows.append(
            {
                "artifact": label,
                "path": str(path),
                "present": "✓" if info["present"] else "✗",
                "size_mb": info["size_mb"],
                "mtime": info["mtime"],
            }
        )
    render_table(rows, title="cricdex data status")


def _skip_if_exists(path: Path, label: str, force: bool) -> bool:
    if path.exists() and not force:
        typer.echo(f"{label} already present at {path}  (pass --force to regenerate)")
        return True
    return False


@app.command("ingest", help="Ingest a data slice (cricsheet|rules|ratings|metrics|graph).")
def ingest_cmd(
    slice_: str = typer.Argument(..., metavar="SLICE"),
    collection: str = typer.Option("ipl", "--collection", "-c"),
    force: bool = typer.Option(False, "--force/--no-force"),
) -> None:
    if slice_ == "cricsheet":
        from cricdex.scout.ingest import cricsheet

        out = DATA_DIR / "cricsheet" / "cricsheet.duckdb"
        if _skip_if_exists(out, "cricsheet duckdb", force):
            return
        cricsheet.ingest(collection=collection)
        typer.echo(f"wrote {out}")
    elif slice_ == "rules":
        from cricdex.rules import embed, parse
        from cricdex.rules import ingest as r_ingest

        r_ingest.download_all()
        parse.parse_all()
        embed.embed_all()
        typer.echo("rules: download + parse + embed done")
    elif slice_ == "ratings":
        from cricdex.scout.ratings import bayesian

        out = DATA_DIR / "metrics" / f"scout_ratings_{collection}.json"
        if _skip_if_exists(out, "scout ratings JSON", force):
            return
        df = bayesian.fit(collection=collection)
        out.parent.mkdir(parents=True, exist_ok=True)
        df.write_json(str(out))
        typer.echo(f"wrote {out} ({df.height} rows)")
    elif slice_ == "metrics":
        import subprocess
        import sys

        cmd = [sys.executable, "scripts/compute_metrics.py", "all", "-c", collection]
        subprocess.run(cmd, check=False)
    elif slice_ == "graph":
        from cricdex.scout.graph import writer

        summary = writer.populate(collection=collection)
        typer.echo(f"graph populated: {summary}")
    elif slice_ == "wikidata":
        from cricdex.scout.ingest import wikidata

        n = wikidata.enrich_via_entity_api(force=force)
        typer.echo(f"wikidata enrichment cache size: {len(n)}")
    else:
        die(
            f"unknown slice `{slice_}` — " "choose: cricsheet|rules|ratings|metrics|graph|wikidata",
            code=EXIT_USER_ERROR,
        )
