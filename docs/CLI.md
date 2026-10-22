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
| 4 | a pipeline step (ingest / metrics / export) failed |

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

Stored at `$CRICDEX_HOME/config.toml` (valid TOML, values escaped), chmod 600.
A hand-edited file that isn't valid TOML gives a clear error naming the file
instead of breaking every command. Allowed keys:
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
cricdex venues "Wankhede Stadium, Mumbai"   # exact Cricsheet venue name
```

These four query the local DuckDB (`data/cricsheet.duckdb`) plus `data/metrics/`,
so they need `cricdex data ingest cricsheet` (and `metrics`) first; they don't
read the exported snapshot.

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

All read the same exported JSON the web app does, player names included: a
name is looked up in `site/public/data/<collection>/players.json` (exact
scorecard or full name, then a unique prefix / part of the name; several
matches are listed instead of guessed), so they work without the DuckDB.
`profile` and `compare` build live from the DuckDB and say so when it's
missing. The filter flags share the
`cricdex.common.filters` port with Leaderboards (role values: batter / bowler /
allrounder / wk_batter).

---

## scout

```
cricdex scout look-alikes "V Kohli" [--role batter] [--pos opener|no3|middle|finisher|lower|tailender] [-k 8]
```

Cross-competition look-alike finder across every Scout pool in the
league registry (IPL peers, SMAT, then each overseas league in
`config/leagues.toml`), ranked by within-tier Bayesian
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

## keep

```
cricdex keep --team RCB [--keep NAME]… [--release NAME]… [--purse 125] [--need TAG=N]… [--sort surplus|price|onfield|outlook|salary|value|age|name] [--csv out.csv] [--check]
```

Keep or release, the retention calculator: one franchise's squad with each
player's salary, value (± uncertainty), estimated auction price, surplus
(price − salary), a Keep / Release / Borderline call with a one-line reason,
then the squad if you follow it (purse left, open slots) and the role gaps
(keepers, openers, death bowlers, spinners, overseas) with the cheapest
players in the likely auction pool that fill them. The rules (purse, squad
limits, deadline) come from [`config/competitions.toml`](../config/competitions.toml);
assumed rules are listed under the table.

- `--keep` / `--release` flip a player (part of the name is enough; a typo gets a did-you-mean).
- `--need spinner=4` sets a role target (`keeper`, `opener`, `death`, `spinner`, `overseas`).
- `--purse` overrides the purse (the 2027 figure isn't published; 125 cr is assumed).
- The **3-season outlook** column is the player's Form forecast (the medians for the next three
  seasons, the shape, P(regular) in the third); `--sort outlook` orders by its three-season average.
- `--csv` writes the table (same columns as the page's Export CSV); `--check` shows the salary
  data check against the published 2026 purses and the players we can't rate.

Reads `site/public/data/ipl/keep.json` + `auction_pool.json`; the same
calculator as the website's Keep or release page (`cricdex.web_parity.keep`,
locked by `test_scripts/test_keep_parity.py`). Method:
[METHODOLOGY §10](METHODOLOGY.md#10-keep-or-release).

---

## bidplan

```
cricdex bidplan --team RCB [--keep NAME]… [--release NAME]… [--purse 125] [--open 8] [--need NEED=N]…
                [--max "NAME=CR"]… [--squad-max 25] [--squad-min 18] [--overseas-cap 8] [--trials 200]
                [--register list.json] [--csv out.csv]
```

**Bid plan**, the auction bidding sheet: the squad going in (Keep or release's plan with your
`--keep` / `--release` calls; every team opens at least `--open` places, default 8, lowest-valued players
first), then the targets in priority order with the price rivals would likely pay (the simulator's
calibrated rivals), the bid that is enough 9 times in 10, a **max bid** (his worth to the squad: the
walk-away price), the chance of landing him at or under it and how often the plan lands him, the **fallback chain** per role,
and the squad that follows (strength now and expected, spend, the likely buys, role needs met, anything
still missing, and "reconsider keeping" for any of your releases worth more to the squad than his salary:
the plan never buys back its own releases). About 5–15 seconds (200 rival auctions in Python).

- `--need spinner=4` sets a role need (`keeper`, `opener`, `death`, `spinner`, `pace`).
- `--max "Rashid Khan=12"` sets your own max bid for a pool player (0 = never bid); repeatable.
- `--register` uses the official auction list (`[{"id": cricsheet id, "base_price": cr}]`) instead of the
  inferred pool; the export's `auction_register.json` is used by default when there is one.
- `--csv` writes the targets (same columns as the page's Export CSV).

Reads `site/public/data/ipl/keep.json` + `auction_pool.json`; the same optimiser as the website's Bid plan
page (`cricdex.web_parity.bidplan`, locked by `test_scripts/test_bidplan_parity.py`). Method and the replay
of the 2025 and 2026 auctions: [METHODOLOGY §12](METHODOLOGY.md#12-bid-plan-beta).

---

## forecast

```bash
cricdex forecast "Virat Kohli" [--json]
cricdex forecast --team RCB [--json]
```

**Form forecast**: a player's `value` (runs per 100 balls above the average ball) over the next three
IPL seasons, starting from his current level. For one player, per role: his current level and career
rating, his last seasons, the plain-English outlook ("About +5 next season (current level +11), likely to
hold that for two seasons, then decline (+2 by 2029)"), and per season the median, the 80% range of his
level, the 80% range of one season at his usual workload, and P(regular) (120+ balls that season). With
`--team`, the squad on one table: current level, career rating, the three medians, their average,
P(regular) in the third season and the outlook flag, sorted by the average. Part of a name is enough; among
namesakes the one with a forecast is picked.

Reads `site/public/data/ipl/forecast.json` (written by `scripts/export_site.py` for the IPL, or `scripts/form_forecast.py export`). Retired
players and players without an IPL season in the last two have no forecast. Method and backtest:
[METHODOLOGY §11](METHODOLOGY.md#11-form-forecast).

---

## dashboard

```
cricdex dashboard
```

Launches the Streamlit dashboard (needs `uv sync --extra ui`; run from
the repo root) on a free local port picked by the OS — it prints the URL;
`--port` pins one. Streamlit reads the same exported `site/public/data/`
as the web app and the JSON-backed CLI commands.

---

## tui

```
cricdex tui
```

Full Textual TUI for interactive browsing (same as bare `cricdex`), part of
the base install (`uv sync`). 14 tabs: Leaders, Records, Compare, H2H,
Matchups, Phase, Form, Partners, Aging, Venues, Profile, Auction, Scout, Update.
