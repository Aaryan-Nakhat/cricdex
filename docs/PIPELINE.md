# The rebuild pipeline

One list of steps takes CricDesk from the Cricsheet download to the site's JSON. It lives in
[`src/cricdesk/pipeline.py`](../src/cricdesk/pipeline.py) and nowhere else: `scripts/rebuild_all.sh`,
`make refresh-all` and the refresh workflow (`.github/workflows/refresh-data.yml`) all run it.

```bash
uv run python -m cricdesk.pipeline --list            # every step, its commands, inputs and outputs
uv run python -m cricdesk.pipeline                   # resume (or start) the default steps
uv run python -m cricdesk.pipeline --fresh           # clear the markers and start over
uv run python -m cricdesk.pipeline --from ratings    # keep the ingested data; ratings onward
uv run python -m cricdesk.pipeline --only export     # just these steps (comma-separated)
uv run python -m cricdesk.pipeline --refit           # the default steps plus the model fits
```

## The steps, in order

| # | Step | Runs | What it makes |
|---|---|---|---|
| 1 | `ingest` | per league | the league's DuckDB tables, from its Cricsheet zip(s) |
| 2 | `people` | once | the Cricsheet People Register (`people`, `people_names`) |
| 3 | `master` | once | the player master, `data/curated/player_master.json` ([IDENTITY](IDENTITY.md)) |
| 4 | `ratings` | per league | `data/metrics/scout_ratings_<league>.json` |
| 5 | `metrics` | per league | `data/metrics/<metric>_<league>.json` (Wicket Quality reads the ratings) |
| 6 | `translation` | refit | `config/league_translation.json` |
| 7 | `drift` | refit | `config/rating_drift.json` (aging curve and drift) |
| 8 | `shrink` | refit | `config/value_shrink.json` |
| 9 | `playing_time` | refit | `config/playing_time_model.json`, and its caches cleared first |
| 10 | `price` | refit | `config/price_model.json` (walk-forward fits, then the price fit) |
| 11 | `keep` | refit | `config/keep_model.json` (work folder `data/metrics/.keep_backtest`) |
| 12 | `forecast` | once | `data/metrics/forecast_ipl.json` (the walk-forward fits are cached) |
| 13 | `export` | once | `site/public/data/` |

`$LEAGUES` (space-separated keys) limits the per-league steps. The export always cooks every
exported league, because the IPL export reads every league's ratings (auction pool, Scout).

## Refit steps

Steps 6 to 11 refit a model: they choose among declared candidates on the validation seasons,
test the chosen one once on 2025 and 2026, and ship it to `config/`. That protocol is frozen
([METHODOLOGY](METHODOLOGY.md)), so a routine rebuild never runs them. They run only with
`--refit`, or when you name one in `--only` (for example `--only drift,shrink,playing_time`).

## Resuming

Each finished step leaves a marker file in `$CRICDESK_REBUILD_STATE` (default
`data/.rebuild_state`, per league for per-league steps). A re-run skips the marked steps, so after a
failure or a reboot run the same command again. `--from STEP` marks the steps before it as done and
clears the markers from it on; `--only` always reruns the steps it names. Command output goes to
`$CRICDESK_REBUILD_LOG` (default `data/rebuild.log`; `-` prints it instead). The first failing step
stops the run and prints the end of the log.

A full rebuild takes hours on a laptop. On Windows, run `bash scripts/rebuild_all.sh` as a scheduled
task.

## The export is atomic per league

`scripts/export_site.py` cooks each league into `site/public/data/.staging/<league>/` and moves it
over `site/public/data/<league>/` only when every file of that league was written. If a file is
briefly locked (Windows), the move is retried a few times and then the export fails with the path.
`collections.json` and `leagues.json` are written last, through a temporary file. A crash leaves the
published leagues as they were; the next run clears `.staging/`.
