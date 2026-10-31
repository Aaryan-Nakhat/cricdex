"""Build the player master: display names, capped, roles / bowling style, country, active /
retired, current IPL team and date of birth for every player of every exported league.

Reads the DuckDB file read-only; fetches Wikidata, Wikipedia and Cricsheet's ODI / Test archives
in polite cached batches; asks the configured LLM (if any) to check display names. Writes
data/curated/player_master.json (read by scripts/export_site.py) and
data/curated/player_master_review.json (source disagreements to settle in
data/curated/player_overrides.json). See src/cricdesk/scout/identity/master.py.

Run:
    uv run python scripts/build_player_master.py              # fetch what's missing, check names
    uv run python scripts/build_player_master.py --no-fetch   # caches only (offline)
    uv run python scripts/build_player_master.py --no-llm     # skip the LLM name check
    uv run python scripts/build_player_master.py --force      # refetch every source
"""

from __future__ import annotations

import json

import typer

from cricdesk.scout.identity import master

app = typer.Typer(add_completion=False)


@app.command()
def run(
    fetch: bool = typer.Option(True, "--fetch/--no-fetch", help="Fetch missing open data."),
    force: bool = typer.Option(False, "--force", help="Refetch every source (ignores caches)."),
    llm: bool = typer.Option(True, "--llm/--no-llm", help="Check display names with the LLM."),
    llm_limit: int = typer.Option(0, "--llm-limit", help="Max players to LLM-check (0 = all)."),
) -> None:
    summary = master.build(fetch=fetch, force=force, llm_names=llm, llm_limit=llm_limit)
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    app()
