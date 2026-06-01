# Architecture

CricDex is **Cricsheet-only**: one public ball-by-ball source, everything
else derived from it offline. No scraping, no live feeds, no LLM-written
content.

## Layers

1. **Ingest** — Cricsheet ball-by-ball (per collection) + the Cricsheet
   People Register for identities. One-time Wikidata enrichment (dob /
   photo / socials) and a Gemini-built player taxonomy (role / seam-spin /
   batting slot / country) are cached on disk. Rulebook PDFs (MCC / ICC /
   board playing conditions) feed the rules RAG.
2. **Identity** — canonical `cricsheet_id` carrying cross-source IDs from
   the People Register; see [`IDENTITY.md`](IDENTITY.md).
3. **Storage**
   - DuckDB — analytics (ball-by-ball, metrics, records, venues).
   - Neo4j Community — per-collection scout graph (Player / Match / Venue
     + FACED edges).
   - Qdrant (embedded on-disk) — rules-clause vectors.
   - On-disk JSON caches — metrics, Bayes ratings, Wikidata, taxonomy.
4. **Modeling**
   - Dismissal-aware Bayesian hierarchical ratings (NumPyro / JAX, ADVI
     default, NUTS available) — opponent-adjusted, four latent skills.
   - XGBoost win-probability model behind NGI.
   - GRPO single-agent RL (PyTorch) for the auction; multi-agent
     self-play deferred (see [`DEFERRED.md`](DEFERRED.md)).
   - Gemini-proxy rule QA with citation discipline.
5. **Serve — four surfaces at parity**
   - **CLI** (`cricdex …`, typer) and **TUI** (Textual).
   - **Streamlit** dashboard (`cricdex.dashboard`).
   - **FastAPI** REST (`cricdex.api.main`).
   - **Static web** (`site/`, React + Vite) on GitHub Pages — reads a
     pre-cooked JSON snapshot, no backend.

## Data pipeline cadence

- Cricsheet ingest + metrics + Bayes ratings + scout graph + static-site
  re-cook → nightly via GitHub Actions (`refresh-data.yml`), then a Pages
  redeploy. This is the only "refresh to the latest match date" path
  (browsers can't run JAX / XGBoost / Neo4j).
- Rulebook PDFs → manual, on each board's release window.
- People Register / Wikidata / taxonomy → one-time, refreshed on demand.

## Module boundaries

Each `src/cricdex/<module>/` owns its ingest, schema, processing and
serve layer. The static export (`scripts/export_site.py`) flattens every
module's output into `site/public/data/`.

## Deployment

Local dev + the heavy pipeline run via Docker (`make docker-up`); see
[`DOCKER.md`](DOCKER.md). The static site deploys to GitHub Pages via
`deploy-pages.yml`. Distribution options (PyPI, GHCR, hosted demo) are in
[`SHIPPING.md`](SHIPPING.md).
