"""The rebuild pipeline: every step from the Cricsheet download to the site's JSON, in order, in one
place. `scripts/rebuild_all.sh`, `make refresh-all` and the refresh workflow all run this list;
docs/PIPELINE.md explains it.

    python -m cricdesk.pipeline --list                 # the steps, their inputs and outputs
    python -m cricdesk.pipeline                        # resume (or start) the default steps
    python -m cricdesk.pipeline --fresh                # clear the markers and start over
    python -m cricdesk.pipeline --from ratings         # keep the ingested data, refit from ratings on
    python -m cricdesk.pipeline --only export          # one step (comma-separate several)
    python -m cricdesk.pipeline --refit                # also the model fits (frozen protocol)

Resumable: each finished step leaves a marker file in the state folder ($CRICDESK_REBUILD_STATE,
default data/.rebuild_state); a re-run skips marked steps. Command output goes to the log
($CRICDESK_REBUILD_LOG, default data/rebuild.log; `-` prints it). `$LEAGUES` (space-separated keys)
limits the per-league steps; the export still cooks every exported league, because the IPL export
reads every league's ratings (auction pool, Scout).

Refit steps re-run a model fit (choose on the validation seasons, test once, ship to config/). They
follow a frozen validation protocol (docs/METHODOLOGY.md), so they never run by default: only with
`--refit`, or when named in `--only`.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LEAGUE = "{league}"  # stands for the league key in a per-league step's command


@dataclass(frozen=True)
class Step:
    name: str
    about: str
    commands: tuple[tuple[str, ...], ...]  # each runs as `python <args>` from the repo root
    inputs: tuple[str, ...]
    outputs: tuple[str, ...]
    per_league: bool = False
    refit: bool = False
    # caches deleted before the step (stale once an upstream model moved)
    clear: tuple[str, ...] = ()
    marker: str | None = None  # marker file name (default: the step name)

    def marker_for(self, league: str | None = None) -> str:
        base = self.marker or self.name
        return f"{base}_{league}" if league else base


KEEP_WORK = "data/metrics/.keep_backtest"
PT_CACHE = "data/metrics/.playing_time"

STEPS: tuple[Step, ...] = (
    Step(
        "ingest",
        "Download the league from Cricsheet and load its tables",
        (("scripts/ingest_cricsheet.py", "ingest", "--collection", LEAGUE, "--force"),),
        ("Cricsheet zip(s) named in config/leagues.toml",),
        ("data/cricsheet/cricsheet.duckdb: matches_/balls_/wickets_/... tables of the league",),
        per_league=True,
    ),
    Step(
        "people",
        "Cricsheet People Register",
        (("scripts/ingest_people.py", "--force"),),
        ("Cricsheet people.csv / names.csv",),
        ("DuckDB tables people, people_names",),
    ),
    Step(
        "master",
        "Player master: display names, roles, country, squads, dates of birth",
        (("scripts/build_player_master.py",),),
        (
            "DuckDB (read-only)",
            "Wikidata, Wikipedia, Cricsheet archives (cached in data/curated)",
            "the LLM name check when LLM_MODEL is set",
        ),
        ("data/curated/player_master.json", "data/curated/player_master_review.json"),
    ),
    Step(
        "ratings",
        "Dismissal-aware Bayesian ratings",
        (("scripts/scout_rate.py", "--collection", LEAGUE, "--advi-steps", "12000"),),
        ("DuckDB balls of the league",),
        ("data/metrics/scout_ratings_<league>.json", "data/metrics/scout_context_<league>.json"),
        per_league=True,
    ),
    Step(
        "metrics",
        "NGI, the context metrics and the fielding boards (Wicket Quality reads the ratings)",
        (("scripts/compute_metrics.py", "all", "--collection", LEAGUE),),
        ("DuckDB balls", "data/metrics/scout_ratings_<league>.json", "player master"),
        ("data/metrics/<metric>_<league>.json",),
        per_league=True,
    ),
    Step(
        "translation",
        "League translation onto the IPL (METHODOLOGY §6d)",
        (
            ("scripts/league_translation_fit.py", "pairs"),
            ("scripts/league_translation_fit.py", "fit"),
        ),
        ("ratings of every pool league", "data/metrics/.backtest_cache"),
        ("config/league_translation.json", "data/metrics/league_translation_ipl.json"),
        refit=True,
    ),
    Step(
        "drift",
        "Time-aware rating: aging curve and drift (METHODOLOGY §4b)",
        tuple(("scripts/rating_drift_fit.py", c) for c in ("obs", "validate", "test", "ship")),
        ("DuckDB balls of every pool league", "config/league_translation.json"),
        ("config/rating_drift.json", "data/metrics/rating_drift_ipl.json"),
        refit=True,
    ),
    Step(
        "shrink",
        "How far a value is trusted: shrink toward the role's mean (METHODOLOGY §4c)",
        tuple(("scripts/value_shrink_fit.py", c) for c in ("rows", "validate", "test", "ship")),
        ("config/rating_drift.json", "data/curated/ipl_auction_history.json"),
        ("config/value_shrink.json", "data/metrics/value_shrink_ipl.json"),
        refit=True,
    ),
    Step(
        "playing_time",
        "Playing-time model: usage, balls, replacement curves, P(plays) (METHODOLOGY §6c)",
        tuple(
            ("scripts/playing_time_fit.py", c)
            for c in ("usage", "balls", "repl", "play", "free", "buy", "value", "ship")
        )
        + (("scripts/playing_time_fit.py", "asof-contrib"),),
        ("config/rating_drift.json", "config/value_shrink.json", "auction history"),
        ("config/playing_time_model.json", "data/metrics/playing_time_ipl.json", f"{PT_CACHE}/"),
        refit=True,
        # built from the drift / shrink values: recomputed after either moved (scripts/README.md)
        clear=tuple(
            f"{PT_CACHE}/{f}"
            for f in ("minbuy_pairs.pkl", "play_rows.pkl", "fa_rows.pkl", "asof_contrib.parquet")
        ),
    ),
    Step(
        "price",
        "Market-price model: the IPL refitted before every auction, then the price fit (§6b)",
        (("scripts/ipl_price_model.py", "fits"), ("scripts/ipl_price_model.py", "fit")),
        ("data/curated/ipl_auction_history.json", f"{PT_CACHE}/asof_contrib.parquet"),
        ("config/price_model.json", "data/metrics/.backtest_cache (walk-forward fits)"),
        refit=True,
    ),
    Step(
        "keep",
        "Keep or release: retention rule backtested on every deadline (METHODOLOGY §10)",
        (
            ("scripts/keep_backtest.py", "rows", "--work", KEEP_WORK),
            ("scripts/keep_backtest.py", "score", "--work", KEEP_WORK),
        ),
        ("config/price_model.json", "config/playing_time_model.json", "forecast fits"),
        ("config/keep_model.json", "data/metrics/keep_backtest_ipl.json"),
        refit=True,
    ),
    Step(
        "forecast",
        "Form forecast: every IPL player's next three seasons (METHODOLOGY §11)",
        (
            ("scripts/form_forecast.py", "fits", "--seeds", "42"),
            ("scripts/form_forecast.py", "build"),
        ),
        ("data/metrics/scout_ratings_ipl.json", "the walk-forward fits (cached, resumable)"),
        ("data/metrics/forecast_ipl.json",),
    ),
    Step(
        "export",
        "Cook the static JSON snapshot (each league swapped in only when it fully succeeded)",
        (("scripts/export_site.py",),),
        ("DuckDB", "data/metrics/*", "data/curated/*", "config/*"),
        ("site/public/data/<league>/", "site/public/data/collections.json, leagues.json"),
        marker="export_all",
    ),
)

BY_NAME = {s.name: s for s in STEPS}


def _leagues() -> list[str]:
    from cricdesk import leagues

    env = os.environ.get("LEAGUES", "").split()
    for c in env:
        leagues.validate_collection(c)
    return env or leagues.exported_keys()


def _units(step: Step, cols: list[str]) -> Iterator[tuple[str | None, str]]:
    """(league or None, marker) for every run of the step."""
    if step.per_league:
        for c in cols:
            yield c, step.marker_for(c)
    else:
        yield None, step.marker_for()


def _argv(cmd: tuple[str, ...], league: str | None) -> list[str]:
    return [sys.executable, *(league if a == LEAGUE else a for a in cmd)]


def select(only: list[str], start: str | None, refit: bool) -> list[Step]:
    """The steps to run, in pipeline order."""
    for n in [*only, *([start] if start else [])]:
        if n not in BY_NAME:
            raise SystemExit(f"unknown step {n!r}; steps: {', '.join(BY_NAME)}")
    if only:
        return [s for s in STEPS if s.name in only]
    steps = [s for s in STEPS if refit or not s.refit]
    if start:
        if BY_NAME[start].refit and not refit:
            raise SystemExit(f"{start} is a refit step: add --refit (or use --only {start})")
        steps = steps[[s.name for s in steps].index(start) :]
    return steps


def _say(msg: str, log: Path | None) -> None:
    line = f"=== {time.strftime('%Y-%m-%d %H:%M:%S')} {msg}"
    print(line, flush=True)
    if log is not None:
        with log.open("a", encoding="utf-8") as f:
            f.write(line + "\n")


def _run(argv: list[str], log: Path | None) -> int:
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    if log is None:
        return subprocess.run(argv, cwd=ROOT, env=env, check=False).returncode
    with log.open("a", encoding="utf-8") as f:
        return subprocess.run(
            argv, cwd=ROOT, env=env, stdout=f, stderr=subprocess.STDOUT, check=False
        ).returncode


def _tail(log: Path, n: int = 30) -> str:
    lines = log.read_text(encoding="utf-8", errors="replace").splitlines()
    return "\n".join(lines[-n:])


def list_steps(cols: list[str]) -> str:
    out = []
    for i, s in enumerate(STEPS, 1):
        tag = " [refit: only with --refit]" if s.refit else ""
        scope = f" (per league: {' '.join(cols)})" if s.per_league else ""
        out.append(f"{i:2}. {s.name}{tag}{scope}\n    {s.about}")
        for c in s.commands:
            out.append(f"    $ python {' '.join(c)}")
        out.append(f"    in:  {'; '.join(s.inputs)}")
        out.append(f"    out: {'; '.join(s.outputs)}")
        if s.clear:
            out.append(f"    clears first: {'; '.join(s.clear)}")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="python -m cricdesk.pipeline", description=__doc__.split("\n\n")[0]
    )
    ap.add_argument("--list", action="store_true", help="print the steps and exit")
    ap.add_argument("--fresh", action="store_true", help="clear every marker first")
    ap.add_argument("--from", dest="start", metavar="STEP", help="start here (earlier steps kept)")
    ap.add_argument("--only", metavar="STEP[,STEP]", default="", help="run just these steps")
    ap.add_argument("--refit", action="store_true", help="include the refit (model-fit) steps")
    a = ap.parse_args(argv)

    cols = _leagues()
    if a.list:
        print(list_steps(cols))
        return 0
    only = [s for s in a.only.split(",") if s]
    if only and a.start:
        ap.error("use --only or --from, not both")
    steps = select(only, a.start, a.refit)

    state = ROOT / os.environ.get("CRICDESK_REBUILD_STATE", "data/.rebuild_state")
    log_env = os.environ.get("CRICDESK_REBUILD_LOG", "data/rebuild.log")
    log = None if log_env == "-" else ROOT / log_env
    if a.fresh and state.exists():
        shutil.rmtree(state)
    state.mkdir(parents=True, exist_ok=True)
    if log is not None:
        log.parent.mkdir(parents=True, exist_ok=True)
    # the steps named run again even when marked done; with --from, the default steps before it count
    # as done, so a later plain re-run resumes instead of downloading everything again
    for s in steps if (only or a.start) else ():
        for _, m in _units(s, cols):
            (state / m).unlink(missing_ok=True)
    if a.start:
        for s in STEPS[: [x.name for x in STEPS].index(a.start)]:
            for _, m in _units(s, cols):
                if not s.refit:
                    (state / m).touch()
    (state / "READY").unlink(missing_ok=True)

    _say(f"leagues: {' '.join(cols)}", log)
    _say(f"steps: {' '.join(s.name for s in steps)}", log)
    for s in steps:
        for league, m in _units(s, cols):
            if (state / m).exists():
                continue
            label = f"{s.name} {league}" if league else s.name
            for f in s.clear:
                (ROOT / f).unlink(missing_ok=True)
            _say(label, log)
            for cmd in s.commands:
                rc = _run(_argv(cmd, league), log)
                if rc != 0:
                    where = f"see {log}" if log is not None else "see the output above"
                    _say(
                        f"!! {label} failed (exit {rc}): {where}; re-run without --from / --only "
                        "to resume (with --refit if refitting)",
                        log,
                    )
                    if log is not None:
                        print(_tail(log), file=sys.stderr)
                    return 1
            (state / m).touch()
    (state / "READY").touch()
    _say("READY: run the tests, check the site, then commit site/public/data", log)
    return 0


if __name__ == "__main__":
    sys.exit(main())
