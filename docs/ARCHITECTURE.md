# Architecture

CricDex is **Cricsheet-only**: one public ball-by-ball source, everything
else derived from it offline. No scraping, no live feeds, no LLM-written
content.

## Pipeline (end to end)

Everything is cooked **once**, offline, into a JSON snapshot; then all four
surfaces just *read* it. The dashed line is the git boundary.

```
 SOURCES                INGEST → DuckDB              DERIVE  (data/, gitignored)        COOK once                 SNAPSHOT (committed)
 ───────                ───────────────              ───────────────────────────       ─────────                ────────────────────
 Cricsheet              data/cricsheet/              data/metrics/                      scripts/                 site/public/data/
  ball-by-ball   ─────► cricsheet.duckdb      ─┬───► scout_ratings_<col>.json   ──┐     export_site.py    ─────► <col>/
  (per league)          • balls_<col>          │     (NumPyro/JAX Bayes: 4         │    flattens DuckDB +       • meta.json
 Cricsheet People       • matches_<col>        │      latent skills/player)        ├──► metrics + ratings +     • players.json
  config/leagues.toml   • innings_<col>        │                                   │
  (which leagues, zips, • wickets_ · players_  │                                   │
   tiers, pools)        • replacements_ · match_players_ · ingest_meta             │
  Register              • balls_<col>_last1y   │     <metric>_<col>[_win].json  ───┤    curated, builds         • ratings.json
  (ids + 7.5k           •        _last3y       │     (12 boards ×8 col ×3 win,     │   windowed boards +        • leaderboards/<slug>[.win].json
   name variations)     • people / people_names│      compute_metrics.py)          │   cohorts (SQL)            • profiles/<cid>.json
                                               │     data/curated/              ───┘                            • cohorts/<cid>.json
                                               │     • player_taxonomy.json (LLM)                             • records.json · venues.json
                                               └───► • wikidata_enrichment.json                                  • auction_pool · retentions
                                                     • bowling_styles.json                                       • scout_index.json · matchups/<cid>.json · phase.json · activity_index.json · partnerships.json · aging.json
                                                                                                          (+ root collections.json, leagues.json)
        each step = `cricdex data ingest <cricsheet|ratings|metrics|wikidata>`              ╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌ git: this snapshot (+ data/curated player facts) is committed
                                                                                                                          │
                                                              ┌───────────────────────────────────────────────────────────┤  read-only views read the SAME JSON (see Fresh checkout)
                                                              ▼                                ▼                ▼          ▼
                                                        React (web)                     Streamlit            TUI         CLI
                                                        getJSON("<col>/…")              web_parity.loader.SITE_DATA + common.filters/metrics
                                                        Scout/Auction/H2H               Scout/Auction → cricdex.web_parity (Python port,
                                                        in-browser TS                   bit-exact, parity-locked to the TS)
                                                        (auction.ts /                   H2H → data/metrics/scout_ratings_<col>.json
                                                         headtohead.ts)                 Update tab/page → re-runs ingest→compute→export
```

- **Cook boundary** = `scripts/export_site.py`. Upstream is the Python pipeline
  (writes `data/` + the snapshot); downstream everyone only reads the snapshot.
- **Parity by construction**: every surface eats identical inputs, and
  Scout/Auction/H2H run identical logic — TypeScript in the browser, a bit-exact
  Python port (`cricdex.web_parity`) elsewhere, locked by
  `test_scripts/test_web_parity.py` + `test_filters_parity.py`.
- **Fresh checkout**: the web app, the Streamlit/TUI read-only tabs and the
  JSON-backed CLI commands (`leaderboard`, `matchups`, `phase`, `form`,
  `partnerships`, `aging`, `scout`, `auction`) work from the committed
  `site/public/data` alone. These need the local `data/` (DuckDB +
  `data/metrics/`, rebuilt via `cricdex data ingest …`, `make refresh` or the
  Update tab): the CLI `profile` / `compare` / `records` / `venues` commands,
  the whole FastAPI app, H2H (`scout_ratings_<col>.json`) and the Update path.
  The curated player facts (`data/curated/player_taxonomy.json`,
  `wikidata_enrichment.json`) are committed.

## The league registry

Every competition CricDex knows is one entry in
[`config/leagues.toml`](../config/leagues.toml), read through
`cricdex.leagues` (standard-library `tomllib`, validated on load): its key
(the `<col>` of every table and folder), display name, Cricsheet zip(s),
gender, kind, region, strength tier (and the group it is pooled with when its
translation onto the IPL is fitted: `scripts/league_translation_fit.py` →
`config/league_translation.json`, read by `cricdex.scout.translation`), whether it is exported, whether it is a Scout pool
(draftable, gem pool) or feeds the auction pool, and the auction target's
nationality allow/deny lists. Ingest, the exporter, pricing
(`web_parity/pricing.py`), the API's collection check (an unknown
collection is a 400 listing the valid keys), the CLI/TUI/Streamlit pickers,
the Makefile and the refresh workflow all read it; the exporter writes it to
`site/public/data/leagues.json` and the web app reads labels, Scout pools,
each league's fitted translation and pool membership from there (`site/src/lib/leagues.ts`). The
time-window suffixes (`_last1y`, `_last3y`) are defined once, in
`common/sql.py`. A league can also list **eras** (`[[league.era]]`, e.g. the
IPL's Impact Player era since 2023-03-31): each becomes one more recomputed
window, `<col>_era_<key>`, built and exported next to the time windows
(`meta.windows` / `meta.window_labels`, so the Leaderboards period selector
offers "Impact Player era"). Adding a league or an era: [LEAGUES.md](LEAGUES.md).

## Layers

1. **Ingest** — Cricsheet ball-by-ball (per collection) + the Cricsheet
   People Register for identities. The parser
   (`scout/ingest/cricsheet.py`, `SCHEMA_VERSION` stored per match and in
   `ingest_meta`) reads every field of the Cricsheet JSON format into
   `matches_`, `innings_` (targets, powerplays, penalty runs …), `balls_`
   (every extras type, DRS review, non-boundary), `wickets_` (every wicket,
   substitute fielders), `replacements_` (Impact Player and others),
   `match_players_` (playing XIs) and `players_` (match registries); a
   missing key is NULL, never an error. One-time Wikidata enrichment (dob /
   photo / socials) and an LLM-built player taxonomy (role / seam-spin /
   batting slot / country, shown as "AI-classified") are cached on disk.
2. **Identity** — one canonical `cricsheet_id` per player: scorecard names
   resolve through each match's own registry (`players_<col>`), then the
   People Register, which also carries the cross-source IDs; see
   [`IDENTITY.md`](IDENTITY.md). The resolution is **per match**, and every
   derived number is keyed by the id, never by the name:
   `common/sql.py::keyed_balls` / `keyed_wickets` are the ball and wicket
   tables with every player column (batter, non-striker, bowler, player out,
   fielders) swapped for the id and the scorecard spelling kept alongside;
   metrics, ratings, NGI, boards, records, profiles, matchups, partnerships,
   phase boards, aging, cohorts and style twins all group by those ids, and
   `relabel` turns them back into `name` / `cricsheet_id` / `display_name` for
   display. So two different players sharing a scorecard name in one league
   stay two players. Venue spellings are merged to one
   `"<ground>, <city>"` per ground after every ingest
   (`common/venue_names.py`, old names kept in `venue_aliases`).
3. **Storage** — file-driven: no vector DB, no graph DB.
   - DuckDB — analytics (ball-by-ball, metrics, records, venues).
   - On-disk JSON caches — metrics, Bayes ratings, Wikidata, taxonomy.
   - Exported JSON snapshot (`site/public/data/`) — the canonical payload
     every surface reads.
4. **Modeling**
   - Dismissal-aware Bayesian hierarchical ratings (NumPyro / JAX, ADVI
     default, NUTS available) — opponent- and context-adjusted (season random
     walk, phase, innings, ground), dispersion scaled by balls, batting-slot /
     bowler-role prior means, a wides + no-balls sub-model; four latent skills.
   - XGBoost win-probability model behind NGI (monotone constraints, beta
     calibration, era-relative features), every ball scored out of fold; the
     out-of-fold scores are cached per league in `data/metrics/.ngi_cache/`
     so the time-window and era boards reuse them.
   - Scout look-alikes + auction Monte-Carlo run through
     `cricdex.web_parity`, a Python port of the web's TypeScript logic
     locked by `test_scripts/test_web_parity.py`.
5. **Serve — the web is canonical; the others mirror it**
   - **Static web** (`site/`, React + Vite) on GitHub Pages — single
     source of truth; reads a pre-cooked JSON snapshot, no backend.
   - **CLI** (`cricdex …`, typer) and **TUI** (Textual).
   - **Streamlit** dashboard (`cricdex.dashboard`).
   - **FastAPI** REST (`cricdex.api.main`).
   The CLI, TUI, Streamlit, and web all run the same analytical pages and
   the same scout/auction logic via `cricdex.web_parity`.

## Data pipeline cadence

- Cricsheet ingest + metrics + Bayes ratings + scout/auction snapshot +
  static-site re-cook → on demand via GitHub Actions (`refresh-data.yml`,
  manual "Run workflow"): re-downloads every exported league in the registry
  (`python -m cricdex.leagues list --exported`) with `--force` and runs the
  default steps of `python -m cricdex.pipeline` ([PIPELINE.md](PIPELINE.md)),
  runs the LLM taxonomy for new players only if the `LLM_MODEL` secret is
  set, commits the snapshot, runs CI on that commit, then calls `deploy.yml`
  (`workflow_call`) to redeploy Pages. This is the only "refresh to the
  latest match date" path for the live site (browsers can't run JAX /
  XGBoost); locally, `make refresh COLLECTION=<c>` does the same for one
  collection and `make refresh-all` for every exported league (one export at
  the end, after every league is refit). `bash scripts/rebuild_all.sh` does
  the same resumably; `--from ratings` keeps the ingested data, People
  Register and player master and refits ratings, recomputes metrics and the
  forecast and exports (`--from metrics`, `--from export` start later still).
  The order of the steps lives in one place, `src/cricdex/pipeline.py`. Manual (not cron) so the ~70 MB snapshot isn't re-committed
  on a schedule.
- People Register / Wikidata / taxonomy → one-time, refreshed on demand.

## Module boundaries

Each `src/cricdex/<module>/` owns its ingest, schema, processing and
serve layer. The static export (`scripts/export_site.py`) flattens every
module's output into `site/public/data/`.

## Deployment

CricDex ships as a **free static website** plus a **run-it-yourself toolkit**; there is no hosted server
and no paid infrastructure.

- **The website** (https://aaryan-nakhat.github.io/cricdex/) is the public face. `scripts/export_site.py`
  cooks everything into `site/public/data/`; `deploy.yml` builds `site/` and publishes it to GitHub Pages
  on every push that touches `site/**`.
- **Refreshing the data** is the manual `refresh-data.yml` workflow (described above): it re-ingests,
  recomputes, re-cooks, commits the snapshot and then calls `deploy.yml` to redeploy. GitHub Actions does
  the compute; GitHub Pages hosts the result.
- **CI**: `ci.yml` runs lint, the test suite (including the web ↔ Python parity tests, which need Node)
  and a TypeScript type-check of `site/`; `docker.yml` checks that the image still builds (nothing is
  pushed).
- **Locally**, the CLI / TUI / Streamlit / FastAPI surfaces run over your own `data/` with `uv`
  ([`RUNNING.md`](RUNNING.md)) or Docker (`make docker-up`, [`DOCKER.md`](DOCKER.md)).

There is no PyPI package or published image (see [`ROADMAP.md`](ROADMAP.md#out-of-scope)). How every
model works is in [`METHODOLOGY.md`](METHODOLOGY.md).
