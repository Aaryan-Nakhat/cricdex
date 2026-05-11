"""CLI: download + parse cricket rulebook PDFs.

Usage:
    uv run python scripts/ingest_rules.py download
    uv run python scripts/ingest_rules.py parse-pdfs
"""

from __future__ import annotations

import json
from pathlib import Path

import typer
from loguru import logger

from cricdex.config import DATA_DIR
from cricdex.rules import ingest, parse

app = typer.Typer(add_completion=False)


@app.command()
def download(force: bool = typer.Option(False, "--force")) -> None:
    dest = DATA_DIR / "rules" / "raw"
    paths = ingest.download_all(dest, force=force)
    logger.info(f"downloaded {len(paths)} PDFs into {dest}")


@app.command("parse-pdfs")
def parse_pdfs(out: Path | None = typer.Option(None, "--out")) -> None:
    pdf_dir = DATA_DIR / "rules" / "raw"
    out_dir = out or (DATA_DIR / "rules" / "parsed")
    out_dir.mkdir(parents=True, exist_ok=True)
    results = parse.parse_all(pdf_dir)
    for src_id, clauses in results.items():
        fp = out_dir / f"{src_id}.jsonl"
        with open(fp, "w") as f:
            for rec in parse.to_records(clauses):
                f.write(json.dumps(rec) + "\n")
        logger.info(f"wrote {fp}")


if __name__ == "__main__":
    app()
