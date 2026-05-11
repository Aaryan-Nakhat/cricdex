# Architecture

## Layers

1. **Ingest** — pull free public sources (Cricsheet YAML, Cricinfo/Cricbuzz scrape, BCCI Domestic, CricHeroes, social platforms, rulebook PDFs, YouTube videos).
2. **Identity resolution** — canonical `player_id` linking Cricsheet ID + Cricinfo ID + CricHeroes ID + BCCI ID via name normalization + DOB + hometown + photo CLIP embeds + manual review queue.
3. **Storage**
   - DuckDB (Parquet) — analytics (ball-by-ball, metrics).
   - Postgres (Supabase) — user data, profiles, claims.
   - Neo4j Community — player-opponent graph (FACED / BOWLED_TO / TWIN_OF).
   - Qdrant — vector embeddings (rules clauses, social posts, player style space).
   - Redis (Upstash) — cache + streams.
   - Cloudflare R2 — raw PDFs, model artifacts, exports.
4. **Modeling**
   - Bayesian hierarchical ratings (PyMC) with opponent-strength bridging — propagates pro-tier opponent strength into grassroots ratings.
   - XGBoost auction price predictor.
   - Multi-agent RL (PettingZoo + SB3) for auction sim.
   - LLM-based rule QA, social sentiment, match reports, commentary translation.
5. **Serve**
   - FastAPI app (`cricdex.api.main`) on Oracle ARM free VM.
   - Cloudflare Worker as edge cache + rate-limit.
   - Next.js frontend on Vercel (later).
   - Telegram + WhatsApp Cloud bots.

## Compute

- **Primary host:** Oracle Cloud Always-Free ARM (4 cores, 24 GB RAM, 200 GB).
- **Training:** Colab T4 + Kaggle T4×2 (free tiers).
- **GPU inference (later):** HF Space + Modal free credits.

## Data pipeline cadence

- Cricsheet → nightly via GitHub Actions cron.
- Cricinfo Statsguru + Cricbuzz player profiles → weekly.
- BCCI Domestic → after each tournament round.
- CricHeroes → continuous slow scrape (1 req / 2 s) + manual contributor uploads.
- Rulebook PDFs → annual (each board's release window).
- Social pulse sources → continuous stream into Redis.

## Module boundaries

Each `src/cricdex/<module>/` owns its own ingest, schema, ratings/processing, and search/serve layer. Cross-module communication via Postgres + DuckDB + Qdrant — no in-process imports across modules except `common/`.

## Identity resolution priorities

Hard keys (DOB, state, role, batting/bowling style) > fuzzy name > photo CLIP > manual review.
