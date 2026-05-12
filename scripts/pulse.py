"""CLI: fetch Reddit posts, extract player sentiment, aggregate.

Examples:
    uv run python scripts/pulse.py fetch --period week --limit 50
    uv run python scripts/pulse.py extract data/pulse/posts_2026-05-12.jsonl
    uv run python scripts/pulse.py run    # one-shot end-to-end
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import polars as pl
import typer
from loguru import logger

from cricdex.config import DATA_DIR
from cricdex.pulse import sentiment
from cricdex.pulse.sources import reddit_public

app = typer.Typer(add_completion=False, no_args_is_help=True)


@app.callback()
def _root() -> None:
    """CricDex social pulse CLI."""


def _outdir() -> Path:
    p = DATA_DIR / "pulse"
    p.mkdir(parents=True, exist_ok=True)
    return p


@app.command()
def fetch(
    period: str = typer.Option("week", "--period"),
    limit: int = typer.Option(50, "--limit"),
    subs: str = typer.Option(
        ",".join(reddit_public.DEFAULT_SUBS), "--subs", help="comma-sep subreddits"
    ),
) -> None:
    today = dt.date.today().isoformat()
    posts = reddit_public.fetch_many(
        subs=[s.strip() for s in subs.split(",") if s.strip()],
        period=period,
        limit_per_sub=limit,
    )
    out = _outdir() / f"posts_{today}.jsonl"
    sentiment.dump_jsonl(out, posts)
    logger.info(f"wrote {out} ({len(posts)} posts)")


@app.command()
def extract(jsonl: Path) -> None:
    posts = [json.loads(line) for line in jsonl.read_text().splitlines() if line.strip()]
    all_mentions: list[dict] = []
    for i, post in enumerate(posts, 1):
        rows = sentiment.extract_mentions(post)
        if rows:
            all_mentions.extend(rows)
        if i % 10 == 0:
            logger.info(f"processed {i}/{len(posts)}")
    today = dt.date.today().isoformat()
    mentions_path = _outdir() / f"mentions_{today}.jsonl"
    sentiment.dump_jsonl(mentions_path, all_mentions)
    logger.info(f"wrote {mentions_path} ({len(all_mentions)} mentions)")

    agg = sentiment.aggregate(all_mentions)
    agg_path = _outdir() / f"player_sentiment_{today}.json"
    pl.DataFrame(agg).write_json(str(agg_path))
    logger.info(f"wrote {agg_path}")
    if agg:
        typer.echo("\n=== Top 20 most-mentioned players ===\n")
        typer.echo(pl.DataFrame(agg[:20]).to_pandas().to_string(index=False))


@app.command()
def run(
    period: str = typer.Option("week", "--period"),
    limit: int = typer.Option(50, "--limit"),
) -> None:
    today = dt.date.today().isoformat()
    posts_path = _outdir() / f"posts_{today}.jsonl"
    if not posts_path.exists():
        fetch(period=period, limit=limit, subs=",".join(reddit_public.DEFAULT_SUBS))
    extract(posts_path)


if __name__ == "__main__":
    app()
