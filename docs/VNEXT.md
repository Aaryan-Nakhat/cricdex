# vNext — work that didn't make v1

Single rolling backlog for features intentionally left out of the
v0.1.0 release. Cross-referenced against the canonical fix catalogue
in [`DEFERRED.md`](DEFERRED.md) and the phase-grouped view in
[`TODO.md`](TODO.md).

Group ordering reflects priority for the next release, not strict
dependency.

---

## Scope: Cricsheet-only

CricDex is intentionally **Cricsheet-only**. All non-Cricsheet
sources and the LLM-convenience features built on them were
**removed** (not deferred) — out of scope:

- Reddit sentiment (`pulse`), Cricbuzz live (`live`), ESPNcricinfo
  scrape, BCCI Ranji/Hazare ingest, WPL 2026 / SA20 2023 / BCCI Code
  rule PDFs.
- Commentary translate, match reports, newsletter digest, the DRS
  placeholder.

Wikidata one-time enrichment stays (289/300 active players; the
remaining 11 are obscure players genuinely absent from Wikidata).

## A — grassroots + identity (year 2)

| Slice | DEFERRED ref | Verify with |
|---|---|---|
| CricHeroes grassroots scraper | §2.2 | `cricdex data ingest cricheroes` |
| Photo-CLIP identity disambiguation (blocked by §A-CricHeroes) | §2.3 | `cricdex scout disambiguate "JJ Smith"` |
| **Replacement Delta** metric (needs a domestic-tier baseline) | METRICS §"Still planned" | `cricdex leaderboard replacement_delta` |

## C — auction-v2 (GPU compute)

| Slice | DEFERRED ref | Verify with |
|---|---|---|
| Multi-agent PettingZoo self-play (every slot a policy) | §2.6 | `cricdex auction train-grpo --multi-agent` |
| Bid-history-mined personality YAMLs (replace hand-authored archetypes) | §2.6 | `cricdex auction train-grpo --personalities yaml` |
| GRPO reward-shape A/B | §2.6 open follow-on | Tracked in `auction.grpo.HISTORY` |

## D — year-2 advanced (CV + voice)

| Slice | DEFERRED ref |
|---|---|
| OpenBoundary Hawk-Eye OSS (ball tracking + pitch map + speed) | §3.1 |
| ChuckCheck elbow-flex from monocular pose | §3.2 |
| Voice analyst earpiece (LiveKit + STT/LLM/TTS) | §3.3 |
| ScoutVLM — YouTube ball-by-ball via VLM | §3.4 |
| Highlight CV auto-clip | §3.5 |
| Tournament management B2B | §3.6 |

## E — API + infra

| Slice | DEFERRED ref | Notes |
|---|---|---|
| GraphQL layer over REST | §4.1 | Strawberry on top of existing FastAPI functions. Speculative consumer demand. |
| Auth + rate-limit | §4.2 | Cloudflare Worker in front of the API + API keys table. Required before any public deploy. |
| Live → dashboard websocket | §2.8 (blocked by §A) | Push insights to a new dashboard page when the live feed unblocks. |
| HF Datasets publish (`cricdex-rules-clauses`) | n/a | Open-benchmark distribution of the 11k parsed clauses. |
| Public deploy | n/a | HuggingFace Spaces (16 GB free, Docker, ephemeral disk) or Oracle Cloud Always Free (24 GB / 4 vCPU ARM, persistent). Both options scoped in earlier sessions. |

## F — maintenance cadence

Rolling work the v1 release surfaces but doesn't automate:

- Rule corpus refresh — `cricdex data ingest rules --force` whenever
  a PC document drops a new edition.
- People Register refresh — Cricsheet's `people.csv` updates monthly.
- Cricsheet ETL refresh — pull when new matches add to a collection.
- Metrics + records JSON refresh — `cricdex data ingest metrics
  --force -c <collection>` after a Cricsheet update.
- WP / Bayes / GRPO refits when the underlying data shifts
  materially.
