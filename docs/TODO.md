# CricDex — phased TODO

Pending work, in landing order. The fuller backlog with rationale is
[`VNEXT.md`](VNEXT.md); known gaps are in [`DEFERRED.md`](DEFERRED.md).

> **Scope:** CricDex is **Cricsheet-only**. Non-Cricsheet sources
> (Reddit/Cricbuzz/ESPNcricinfo scrape, BCCI Ranji/Hazare, extra rule
> PDFs) and the LLM-convenience features on top of them (commentary
> translate, match reports, newsletter, sentiment) were **removed**, not
> deferred. Wikidata one-time enrichment stays (289/300 active players).

---

## Phase 1 — grassroots + identity (year 2)

| Slice | Ref | Verify with |
|---|---|---|
| CricHeroes grassroots scraper | VNEXT §A | `cricdex data ingest cricheroes` |
| Photo-CLIP identity disambiguation (needs §CricHeroes) | VNEXT §A | `cricdex scout disambiguate "JJ Smith"` |
| Replacement Delta metric (needs a domestic-tier baseline) | METRICS | `cricdex leaderboard replacement_delta` |

## Phase 2 — auction-v2 (GPU)

| Slice | Ref | Verify with |
|---|---|---|
| Multi-agent PettingZoo self-play | VNEXT §C | new RL trainer over the auction env |
| Bid-history-mined personality YAML | VNEXT §C | franchise archetypes extracted via Gemini |

## Phase 3 — year-2 advanced (CV + voice)

| Slice | Ref |
|---|---|
| OpenBoundary Hawk-Eye OSS | VNEXT §D |
| ChuckCheck elbow flex from monocular pose | VNEXT §D |
| Voice analyst earpiece (LiveKit + STT/LLM/TTS) | VNEXT §D |
| ScoutVLM YouTube ball-by-ball | VNEXT §D |
| Highlight CV auto-clip | VNEXT §D |
| Tournament management B2B | VNEXT §D |

## Phase 4 — API + infra

| Slice | Ref | Verify with |
|---|---|---|
| GraphQL layer | VNEXT §E | `cricdex api graphql --serve` (when wired) |
| Auth + rate-limit (Cloudflare Worker + API keys) | VNEXT §E | curl with API-key header |

## Phase 5 — maintenance

Rolling cadence: People Register refresh, Cricsheet ETL refresh, metrics
+ records JSON refresh, Bayes refits when data shifts. See
[`DEFERRED.md`](DEFERRED.md) §maintenance.
