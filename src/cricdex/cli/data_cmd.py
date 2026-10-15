"""`cricdex data` — inventory + ingest.

`cricdex data status` shows what's locally available + sizes + last-
updated, so a returning user can tell at a glance what's fresh and
what needs recomputing.

`cricdex data ingest <slice>` triggers the relevant pipeline. The
cricsheet and ratings slices skip a collection that's already there,
unless `--force` is passed. The metrics slice also rebuilds that
collection's site JSON, so every command reads the new numbers.
"""

from __future__ import annotations

import datetime as dt
import subprocess
import sys
from pathlib import Path

import typer

from cricdex.cli._shared import EXIT_RUNTIME_ERROR, EXIT_USER_ERROR, die, render_table
from cricdex.config import DATA_DIR, ROOT, SITE_DATA

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
        ("scout NumPyro ratings", DATA_DIR / "metrics" / "scout_ratings_ipl.json"),
        ("metrics outputs", DATA_DIR / "metrics"),
        ("people register", DATA_DIR / "register" / "people.csv"),
        ("exported site JSON", SITE_DATA / "ipl"),
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


def _script(name: str, *args: str) -> subprocess.CompletedProcess:
    """Run one of the repo's scripts/ from the repo root (works from any working directory)."""
    return subprocess.run(
        [sys.executable, str(ROOT / "scripts" / name), *args],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )


def _tail(proc: subprocess.CompletedProcess) -> str:
    return (proc.stderr or proc.stdout or "").strip()[-800:]


def _has_collection(collection: str) -> bool:
    import duckdb

    from cricdex.common.sql import table_suffix

    db = DATA_DIR / "cricsheet" / "cricsheet.duckdb"
    if not db.exists():
        return False
    with duckdb.connect(str(db), read_only=True) as con:
        tables = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
    return f"balls_{table_suffix(collection)}" in tables


def run_export(collection: str) -> str:
    """Rebuild one collection's site JSON (what the web, CLI, TUI and dashboard read). Raises on failure."""
    proc = _script("export_site.py", "-c", collection)
    if proc.returncode != 0:
        raise RuntimeError(f"export_site.py failed (exit {proc.returncode}):\n{_tail(proc)}")
    return f"site JSON rebuilt for {collection}"


SLICES: tuple[str, ...] = (
    "cricsheet",
    "ratings",
    "metrics",
    "wikidata",
)


def run_ingest(slice_: str, collection: str = "ipl", force: bool = False) -> str:
    """Run an ingest slice and return a one-line status string.

    Pulled out of the typer command so the TUI + Streamlit can call
    the same code path. Returns a human-readable summary; raises
    `ValueError` for unknown slices and `RuntimeError` when a step fails,
    so the caller can stop instead of reporting success.
    """
    if slice_ == "cricsheet":
        out = DATA_DIR / "cricsheet" / "cricsheet.duckdb"
        # Skip only when *this* collection is already loaded (other collections share the same DuckDB file).
        if _has_collection(collection) and not force:
            return f"{collection} is already in {out} (pass --force to re-download)"
        if collection == "indian_domestic_male":
            args = ["indian-domestic", *(["--force"] if force else [])]
        else:
            args = ["ingest", "--collection", collection, *(["--force"] if force else [])]
        proc = _script("ingest_cricsheet.py", *args)
        if proc.returncode != 0:
            raise RuntimeError(
                f"ingest_cricsheet.py failed (exit {proc.returncode}):\n{_tail(proc)}"
            )
        return f"loaded {collection} into {out}"
    if slice_ == "ratings":
        from cricdex.scout.ratings import bayesian

        out = DATA_DIR / "metrics" / f"scout_ratings_{collection}.json"
        if out.exists() and not force:
            return f"scout ratings JSON already present at {out} (pass force=True to regenerate)"
        df = bayesian.fit(collection=collection)
        out.parent.mkdir(parents=True, exist_ok=True)
        df.write_json(str(out))
        return f"wrote {out} ({df.height} rows)"
    if slice_ == "metrics":
        proc = _script("compute_metrics.py", "all", "-c", collection)
        if proc.returncode != 0:
            raise RuntimeError(
                f"compute_metrics.py failed (exit {proc.returncode}):\n{_tail(proc)}"
            )
        return f"metrics computed for {collection}; " + run_export(collection)
    if slice_ == "wikidata":
        from cricdex.scout.ingest import wikidata

        n = wikidata.enrich_via_entity_api(force=force)
        return f"wikidata enrichment cache size: {len(n)}"
    raise ValueError(f"unknown slice `{slice_}` — choose: {' | '.join(SLICES)}")


@app.command("ingest", help="Ingest a data slice (cricsheet|ratings|metrics|wikidata).")
def ingest_cmd(
    slice_: str = typer.Argument(..., metavar="SLICE"),
    collection: str = typer.Option("ipl", "--collection", "-c"),
    force: bool = typer.Option(False, "--force/--no-force"),
) -> None:
    try:
        msg = run_ingest(slice_, collection=collection, force=force)
    except ValueError as e:
        die(str(e), code=EXIT_USER_ERROR)
    except RuntimeError as e:
        die(str(e), code=EXIT_RUNTIME_ERROR)
    typer.echo(msg)
