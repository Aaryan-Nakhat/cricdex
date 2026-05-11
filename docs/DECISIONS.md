# Decisions

Locked design choices and their reasoning. Append new entries with date.

## 2026-05-11 — Name: CricDex

Cricket-prefixed, evokes pokedex-style catalog metaphor — fits scout-first thesis. Unique vs CricInfo / CricViz / CricVision / Cricbuzz.

## 2026-05-11 — License: MIT

Maximises permissive adoption. Compatible with all dependencies in scope. Re-evaluate AGPL only if a commercial fork becomes a real threat.

## 2026-05-11 — Visibility: private repo until v1 launch

Build quietly, ship loud. Flip to public on day-1 of launch week to harvest stars from press hits.

## 2026-05-11 — Stack defaults

- Python 3.12, UV package manager (matches user's other workspace).
- DuckDB for OLAP (free, in-process, no Postgres dependency for analytics).
- Postgres (Supabase) for relational + user data.
- Neo4j Community for player-opponent graph.
- Qdrant 1 GB free for vectors.
- FastAPI for service layer.
- Next.js + Vercel for web (deferred).
- Gemini Flash as default LLM (1500/day free), Cerebras Llama for sub-second live, Claude/Perplexity for premium fallback.

## 2026-05-11 — Cost philosophy

Ship every module on $0 free tiers until product-market-fit. Domain + sponsorship of optional paid tiers (Supabase Pro, HF Space GPU) only when scale forces it.

## 2026-05-11 — Defer voice + CV modules

Voice analyst and OpenBoundary / ChuckCheck deferred to year 2. They are user's biggest moats but highest build cost. Ship cheaper viral modules first to hit 10k stars, then leverage that audience for the heavy modules.

## 2026-05-11 — Women's cricket first-class

Women's data treated as first-class from day 1 across every module. Avoids retrofitting later and creates a press/PR angle.

## 2026-05-11 — Do not build a tournament management product

CricHeroes already does grassroots tournament management. Partner via API instead of competing — they own the user funnel, we own the analytics layer.

## 2026-05-11 — Drop PSL from rules corpus

Pakistan Super League playing conditions excluded from rule-RAG ingest. Re-evaluate only on explicit user request.

## 2026-05-11 — Drop fantasy module

`fantasy/` removed from scope. Dream11-style optimizer not on critical path; revisit only if a clear non-gambling angle emerges.

## 2026-05-11 — Voice-cloned commentary as final feature

`commentary_translate` ships text-only in Phase 6. Voice-cloned target-language TTS (XTTS-v2 / F5-TTS / OpenVoice + AI4Bharat IndicTTS) deferred to year-2 final milestone. Reasons: GPU inference cost, commentator likeness-rights risk, dependency on text-translation quality + audience first. Plan to secure opt-in licensing from retired commentators before launching cloned voices.

## 2026-05-11 — Docker is the single deployment artefact

Every contributor runs the stack the same way: `make docker-up`. The
same image is the production artefact. Compose covers Qdrant + app
today; Postgres / Redis / Neo4j are commented-out placeholders that
come online with scout / cache / graph modules respectively. The image
pre-bakes the embedding model so first-run is instant.

Rationale: the project's positioning is "open cricket intelligence —
anyone can run it locally and verify the data themselves." A friction-
free `docker compose up` is non-negotiable for that promise.

## 2026-05-11 — Curated supplementary clauses fill non-PDF rule gaps

Not every authoritative cricket rule lives in a public PDF. The IPL
Impact Player rule, for instance, is published in the BCCI's "TATA IPL
Player Regulations 2025-27" — a document that is not hosted publicly.
Rather than leaving those questions unanswered, the pipeline supports
a `data/rules/curated/` directory of hand-written JSONL clauses synthesised
from authoritative announcements + reputable explainers (e.g.
ESPNcricinfo, Wisden, Olympics.com). Curated entries carry a
`supplementary` tier in the manifest with full source provenance.

This is a deliberate trade-off: the LLM citation discipline always
cites `source_id` so a user can verify the underlying source. The
alternative (silent "Not in corpus") would have made the rule module
unusable for the most common IPL question.

Re-curate whenever BCCI publishes a public PDF.

## 2026-05-11 — Sources for scout opposition bridging

Pro tier: Cricsheet ball-by-ball. Semi-pro: BCCI Domestic + state assoc + Ranji/SMAT/Hazare. Grassroots: CricHeroes + CricClubs + state-league YouTube broadcasts (year-2 ScoutVLM). Ratings sharpen with bridge-score; unbridged grassroots stay flagged low-confidence.
