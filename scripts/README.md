# scripts

Command-line entry points for the offline pipeline. Run them from the repo root with `uv run python
scripts/<name>.py …`; add `--help` to any of them for the options. Most day-to-day use goes through
`cricdex data ingest …` or `make refresh COLLECTION=<c>` (download → ratings → metrics → site data),
which call these for you.

| Script | What it does | Example |
|---|---|---|
| `ingest_cricsheet.py` | Downloads a Cricsheet collection, writes Parquet and loads the DuckDB tables (`matches_`, `balls_`, `wickets_`, `players_<col>`), then merges venue names. `indian-domestic` builds the SMAT collection from the 38 state-team archives. | `ingest --collection ipl --force` · `indian-domestic` |
| `ingest_people.py` | Downloads the Cricsheet People Register (`people`, `people_names`). | `--force` to refresh |
| `ingest_wikidata.py` | The older bulk Wikidata path (SPARQL, rate-limited from datacenter IPs). The entity-API path is `cricdex data ingest wikidata`. | — |
| `enrich_taxonomy.py` | Tags each player's role, bowling type, batting slot, hand and country with an LLM via LiteLLM (any provider, set in `.env`); cached in `data/curated/player_taxonomy.json`, shown as "AI-classified". Only players missing from the cache are queried. | `--batch 20` |
| `compute_metrics.py` | Computes the leaderboards into `data/metrics/<metric>_<col>.json`; `all` runs NGI, the nine context metrics and the two fielding boards. | `all -c ipl` |
| `scout_rate.py` | Fits the dismissal-aware Bayesian ratings into `data/metrics/scout_ratings_<col>.json` (ADVI by default, `--sampler nuts` for the exact run). | `-c ipl --sampler nuts` |
| `export_site.py` | Cooks everything into the static JSON snapshot in `site/public/data/` that every surface reads (leaderboards and time windows, profiles, auction pool, scout index, matchups, …). | `-c ipl` (blank = all eight) |
| `records.py` | Records and On This Day from the DuckDB. | `list` · `top fastest_fifty -c ipl` · `today` · `all` |
| `style_twin.py` | Nearest-neighbour style twins for one player. | `"MS Dhoni" -c ipl` |
| `backtest_ratings.py` | Walk-forward check: fit before each IPL season, compare with that season, against career averages. | `-c ipl --seasons 2021-2026 --half-life 2` |
| `backtest_newcomers.py` | Rates IPL newcomers from BBL / SA20 / CPL / Blast / SMAT only and scores their first IPL season, with a bootstrap of the model-vs-raw gap. | `--seasons 2014-2026 --boot 2000` |
| `render_video.py` | Renders the README video from `docs/media/src/*.html`. | `uv run --with playwright python scripts/render_video.py docs/media/src/hero.html --out docs/media/hero` |
| `render_images.py` | Renders the README images from `docs/media/src/img-*.html`. | `uv run --with playwright python scripts/render_images.py` |

What each model does and why: [`docs/METHODOLOGY.md`](../docs/METHODOLOGY.md). The backtest results are in
[§8](../docs/METHODOLOGY.md#8-does-it-predict-the-backtest).
