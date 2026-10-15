# CricDex CLI reference

`cricdex` is the one console entry point — available after `uv sync`
(run as `uv run cricdex …`, or inside the activated venv).

```
cricdex                          open the interactive TUI (`cricdex --help` for the commands)
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
prompts for an optional LLM model + key (used for the player taxonomy enrichment),
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
`llm_model`, `llm_api_key`, `llm_api_base`.

Env vars override the file (e.g., `LLM_MODEL=<provider>/<model>`).

---

## data

```
cricdex data status
cricdex data ingest <slice> [-c <collection>] [--force]
```

Slices: `cricsheet`, `ratings`, `metrics`, `wikidata`.
`cricsheet` and `ratings` skip a collection that's already loaded —
pass `--force` to re-download / refit. `metrics` always recomputes and
then rebuilds that collection's site data (`site/public/data/<c>/`),
which `leaderboard`, `matchups`, `phase`, `form`, `partnerships`,
`aging`, `scout` and `auction` read. A failed step exits with code 4.
`status` prints a table of every artifact + size + last-updated.

---

## leaderboard

```
cricdex leaderboard <metric> [-c <collection>] [--top 15] [--json]
```

Metrics: `ngi`, `pressure_runs`, `intent_curve`, `dot_ball_recovery`,
`counter_attack`, `boundary_dependency`, `pressure_conversion`,
`wicket_quality`, `crease_longevity`, `slow_start_cost`, `keeping`
(wicketkeeping dismissals), `fielding` (outfield dismissals). Reads
the exported `site/public/data/<collection>/leaderboards/<metric>.json`
(shipped with the repo; `cricdex data ingest metrics` rebuilds it).

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

```
cricdex partnerships [<name>] [-c ipl] [--top 15] [--min-runs 50] [--json]
```

- **partnerships** — batter-pair stands. With a name: that player's most
  productive partners; always the all-time best partnerships (runs, innings, best
  stand, SR, average, fifty/hundred stands).

```
cricdex aging [--role batting|bowling] [--metric sr|average|economy|strike_rate] [-c ipl] [--json]
```

- **aging** — performance-vs-age curve (per-age mean over player-seasons), with a
  sparkline + table. Ages from Wikidata dob (~⅓ of players; indicative).

All read the same exported JSON the web app does. The filter flags share the
`cricdex.common.filters` port with Leaderboards (role values: batter / bowler /
allrounder / wk_batter).

---

## scout

```
cricdex scout look-alikes "V Kohli" [--role batter] [--pos opener|no3|middle|finisher|lower|tailender] [-k 8]
```

Cross-competition look-alike finder across six pools (IPL, SMAT,
BBL, SA20, CPL, T20 Blast), ranked by within-tier Bayesian
skill-standing z-score. Each row carries an est. crore price +
saving-vs-pick, an uncapped-gem flag, and role/slot filters. Shares
one implementation with the web via `cricdex.web_parity`.

---

## auction

```
cricdex auction room [--mode mega|mini] [--purse 120] [--squad-size 25] [--overseas-cap 8] [--trials 300] [--top-n 20]
```

Real-rules IPL auction Monte-Carlo: cross-collection pool (IPL +
BBL/SA20/CPL/Blast free agents + uncapped SMAT), Mega/Mini
retentions from the real 2025 lists (editable in the TUI / web), overseas cap + retention slabs,
second-price clearing, two-phase fill to 20–25-man squads (~300
trials). Shares one implementation with the web via
`cricdex.web_parity` (locked by `test_scripts/test_web_parity.py`).
See [`AUCTION_MATH.md`](AUCTION_MATH.md).

---

## dashboard

```
cricdex dashboard
```

Launches the Streamlit dashboard on a free local port (8501 if available).
Streamlit reads the same `$CRICDEX_HOME/data/` so it's always in
sync with the CLI.

---

## tui

```
cricdex tui
```

Full Textual TUI for interactive browsing. Requires the `cli`
packages, which are part of the base install (`uv sync`).
