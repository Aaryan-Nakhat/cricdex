# CricDex CLI reference

`cricdex` is the one console entry point — available after `uv sync`
(run as `uv run cricdex …`, or inside the activated venv).

```
cricdex                          show help
cricdex --version / -V           print version
cricdex --help / -h              top-level help
cricdex <subcommand> --help      per-subcommand help
```

Exit codes:

| code | meaning |
|---|---|
| 0 | success |
| 1 | user error (bad arguments / missing argument) |
| 2 | missing data (run `cricdex data ingest …` first) |
| 3 | missing credential (run `cricdex config set …`) |

---

## init

```
cricdex init
```

First-run wizard. Creates `$CRICDEX_HOME` (default `~/.cricdex/`),
prompts for the Gemini key (used for the player taxonomy enrichment),
prints the next-step commands. Idempotent.

---

## config

```
cricdex config path
cricdex config get [KEY]
cricdex config set KEY VALUE
cricdex config unset KEY
cricdex config edit
```

Stored at `$CRICDEX_HOME/config.toml`, chmod 600. Allowed keys:
`gemini_api_key`, `gemini_tmp_url`, `gemini_tmp_api_key`.

Env vars override the file (e.g., `GEMINI_API_KEY=… cricdex data ingest wikidata`).

---

## data

```
cricdex data status
cricdex data ingest <slice> [-c <collection>] [--force]
```

Slices: `cricsheet`, `ratings`, `metrics`, `wikidata`.
Every ingest skips its output if it already exists — pass `--force`
to regenerate. `status` prints a table of every artifact + size +
last-updated.

---

## leaderboard

```
cricdex leaderboard <metric> [-c <collection>] [--top 25] [--json]
```

Metrics: `ngi`, `pressure_runs`, `intent_curve`, `dot_ball_recovery`,
`counter_attack`, `boundary_dependency`, `pressure_conversion`,
`wicket_quality`, `crease_longevity`, `slow_start_cost`. Reads
`$CRICDEX_HOME/data/metrics/<metric>_<collection>.json` — emit it
via `cricdex data ingest metrics` first.

---

## profile / compare / records / venues

```
cricdex profile "V Kohli" [-c ipl]
cricdex compare "V Kohli" "RG Sharma"
cricdex records today                        # on-this-day
cricdex records list                         # list record keys
cricdex records career_run_leaders --top-n 25
cricdex venues "Wankhede"
```

---

## matchups / phase / form

```
cricdex matchups "V Kohli" [-c ipl] [--top 15] [--min-balls 6] [--json]
cricdex phase [powerplay|middle|death] [-c ipl] [--top 15] \
              [--role …] [--bowling seam|spin] [--position …] \
              [--activity all|active|retired] [--country IND] [--min-matches 0] [--json]
cricdex form <metric> [-c ipl] [--top 15] [--window last1y|last3y] \
             [--role …] [--bowling …] [--position …] [--activity …] \
             [--country IND] [--min-matches 0]
```

- **matchups** — a player's batter-vs-bowler head-to-heads (as batter and as
  bowler) plus their pace-vs-spin split with a "weaker vs" read; `--min-balls`
  drops thin head-to-heads.
- **phase** — powerplay / middle / death specialist boards (best strike rates,
  tightest economies), with the full player filter bar.
- **form** — a metric recomputed over the recent window (pick with `--window`;
  defaults to last 1y, else 3y) vs the career baseline; positive form Δ =
  improving (direction-corrected for "lower is better" metrics). Heating-up then
  cooling-down, with the full player filter bar.

All read the same exported JSON the web app does. The filter flags share the
`cricdex.common.filters` port with Leaderboards (role values: batter / bowler /
allrounder / wk_batter).

---

## scout

```
cricdex scout look-alikes "V Kohli" [-c ipl] [--role batter] [--slot top]
```

Cross-competition look-alike finder across six pools (IPL, SMAT,
BBL, SA20, CPL, T20 Blast), ranked by within-tier Bayesian
skill-standing z-score. Each row carries an est. crore price +
saving-vs-pick, an uncapped-gem flag, and role/slot filters. Shares
one implementation with the web via `cricdex.web_parity`.

---

## auction

```
cricdex auction room [-c ipl]
```

Real-rules IPL auction Monte-Carlo: cross-collection pool (IPL +
BBL/SA20/CPL/Blast free agents + uncapped SMAT), editable Mega/Mini
retentions from the real 2025 lists, overseas cap + retention slabs,
second-price clearing, two-phase fill to 20–25-man squads (~300
trials). Shares one implementation with the web via
`cricdex.web_parity` (locked by `test_scripts/test_web_parity.py`).
See [`AUCTION_MATH.md`](AUCTION_MATH.md).

---

## dashboard

```
cricdex dashboard
```

Launches the Streamlit dashboard on `http://localhost:8501`.
Streamlit reads the same `$CRICDEX_HOME/data/` so it's always in
sync with the CLI.

---

## tui

```
cricdex tui
```

Full Textual TUI for interactive browsing. Requires the `cli`
extra: `uv sync --extra cli`.
