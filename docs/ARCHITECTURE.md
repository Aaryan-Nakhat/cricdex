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
  Register              • balls_<col>_last1y   │     <metric>_<col>[_win].json  ───┤    curated, builds         • ratings.json
  (ids + 8.8k           •        _last3y       │     (10 metrics ×8 col ×3 win,     │   windowed boards +        • leaderboards/<slug>[.win].json
   name variations)     • people / people_names│      compute_metrics.py)          │   cohorts (SQL)            • profiles/<cid>.json
                                               │     data/curated/              ───┘                            • cohorts/<cid>.json
                                               │     • player_taxonomy.json (Gemini)                             • records.json · venues.json
                                               └───► • wikidata_enrichment.json                                  • auction_pool · retentions
                                                     • bowling_styles.json                                       • scout_index.json · matchups/<cid>.json · phase.json · activity_index.json · partnerships.json
                                                                                                          (+ root collections.json)
        each step = `cricdex data ingest <cricsheet|ratings|metrics|wikidata>`              ╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌ git: only this snapshot is committed
                                                                                                                          │
                                                              ┌───────────────────────────────────────────────────────────┤  all read the SAME JSON
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
- **Fresh checkout**: read-only tabs work from the committed `site/public/data`
  alone. H2H + the Update/refresh path also need the gitignored `data/`
  (DuckDB + `scout_ratings` + curated) — transferred once or rebuilt via Update.

## Layers

1. **Ingest** — Cricsheet ball-by-ball (per collection) + the Cricsheet
   People Register for identities. One-time Wikidata enrichment (dob /
   photo / socials) and a Gemini-built player taxonomy (role / seam-spin /
   batting slot / country) are cached on disk.
2. **Identity** — canonical `cricsheet_id` carrying cross-source IDs from
   the People Register; see [`IDENTITY.md`](IDENTITY.md).
3. **Storage** — file-driven: no vector DB, no graph DB.
   - DuckDB — analytics (ball-by-ball, metrics, records, venues).
   - On-disk JSON caches — metrics, Bayes ratings, Wikidata, taxonomy.
   - Exported JSON snapshot (`site/public/data/`) — the canonical payload
     every surface reads.
4. **Modeling**
   - Dismissal-aware Bayesian hierarchical ratings (NumPyro / JAX, ADVI
     default, NUTS available) — opponent-adjusted, four latent skills.
   - XGBoost win-probability model behind NGI.
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
  manual "Run workflow"), then a Pages redeploy. This is the only "refresh
  to the latest match date" path (browsers can't run JAX / XGBoost).
  Manual (not cron) so the 35 MB snapshot isn't re-committed nightly.
- People Register / Wikidata / taxonomy → one-time, refreshed on demand.

## Module boundaries

Each `src/cricdex/<module>/` owns its ingest, schema, processing and
serve layer. The static export (`scripts/export_site.py`) flattens every
module's output into `site/public/data/`.

## Deployment

Local dev + the heavy pipeline run via Docker (`make docker-up`); see
[`DOCKER.md`](DOCKER.md). The static site deploys to GitHub Pages via
`deploy.yml`. Hosting notes are in [`SHIPPING.md`](SHIPPING.md).
