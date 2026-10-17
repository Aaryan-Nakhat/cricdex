# scripts

Command-line entry points for the offline pipeline. Run them from the repo root with `uv run python
scripts/<name>.py …`; add `--help` to any of them for the options. Most day-to-day use goes through
`cricdex data ingest …`, `make refresh COLLECTION=<c>` (download → ratings → metrics → site data) or
`make refresh-all` (every exported league, one export at the end), which call these for you. The
league list itself is [`config/leagues.toml`](../config/leagues.toml) — see
[`docs/LEAGUES.md`](../docs/LEAGUES.md).

| Script | What it does | Example |
|---|---|---|
| `ingest_cricsheet.py` | Downloads a Cricsheet collection (which zip(s) is set in the league registry, [`config/leagues.toml`](../config/leagues.toml)), writes Parquet and loads the DuckDB tables (`matches_`, `innings_`, `balls_`, `wickets_`, `replacements_`, `match_players_`, `players_<col>`, plus `ingest_meta`), then merges venue names. `all` ingests every exported league; `list` prints the registry. SMAT (`indian_domestic_male`) is one more collection, from Cricsheet's `sma_json.zip`. | `ingest --collection ipl --force` · `all --force` · `list` |
| `rebuild_all.sh` | Rebuilds everything for every exported league in the registry: ingest → People Register → ratings for all → metrics for all → one export (only after every league is refit). Resumable (markers in `data/.rebuild_state`, log in `data/rebuild.log`); `--fresh` starts over; `LEAGUES="ipl psl"` limits the refit. Multi-hour — on Windows run it as a scheduled task. | `bash scripts/rebuild_all.sh` |
| `auction_check.py` | Sanity-checks the IPL mega auction on the exported data (same simulator as the website): purse used per team, squad sizes, price spread and the top of the pool. Run it after a rebuild or a pricing change. | `--trials 300` |
| `ingest_people.py` | Downloads the Cricsheet People Register (`people`, `people_names`). | `--force` to refresh |
| `ingest_wikidata.py` | The older bulk Wikidata path (SPARQL, rate-limited from datacenter IPs). The entity-API path is `cricdex data ingest wikidata`. | — |
| `enrich_taxonomy.py` | Tags each player's role, bowling type, batting slot, hand and country with an LLM via LiteLLM (any provider, set in `.env`); cached in `data/curated/player_taxonomy.json`, shown as "AI-classified". Only players missing from the cache are queried. | `--batch 20` |
| `compute_metrics.py` | Computes the leaderboards into `data/metrics/<metric>_<col>.json`; `all` runs NGI, the nine context metrics and the two fielding boards. | `all -c ipl` |
| `scout_rate.py` | Fits the dismissal-aware Bayesian ratings into `data/metrics/scout_ratings_<col>.json` (ADVI by default, `--sampler nuts` for the exact run). | `-c ipl --sampler nuts` |
| `export_site.py` | Cooks everything into the static JSON snapshot in `site/public/data/` that every surface reads (leaderboards and time windows, profiles, auction pool, scout index, matchups, …), plus `leagues.json` (the league registry the web app reads labels, Scout pools and price discounts from). | `-c ipl` (blank = every exported league in the registry) |
| `records.py` | Records and On This Day from the DuckDB. | `list` · `top fastest_fifty -c ipl` · `today` · `all` |
| `style_twin.py` | Nearest-neighbour style twins for one player. | `"MS Dhoni" -c ipl` |
| `backtest_ratings.py` | Walk-forward check: fit before each IPL season, compare with that season, against career averages. | `-c ipl --seasons 2021-2026 --half-life 2` |
| `backtest_newcomers.py` | Rates IPL newcomers from the other auction-pool leagues only (every `auction_pool` league in the registry except the IPL; the published run used BBL / SA20 / CPL / Blast / SMAT) and scores their first IPL season, with a bootstrap of the model-vs-raw gap. | `--seasons 2014-2026 --boot 2000` |
| `render_video.py` | Renders the README video from `docs/media/src/*.html`. | `uv run --with playwright python scripts/render_video.py docs/media/src/hero.html --out docs/media/hero` |
| `render_images.py` | Renders the README images from `docs/media/src/img-*.html`. | `uv run --with playwright python scripts/render_images.py` |

What each model does and why: [`docs/METHODOLOGY.md`](../docs/METHODOLOGY.md). The backtest results are in
[§8](../docs/METHODOLOGY.md#8-does-it-predict-the-backtest).
