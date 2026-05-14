# CricDex — phased TODO

Living queue of pending work. Reference catalogue is
[`DEFERRED.md`](DEFERRED.md); this file groups its entries into the
order they should land and adds the CLI command that would verify
each one once unblocked.

---

## Phase 1 — residential-IP unblock pulls

All pipelines below are shipped and tested; they just fail end-to-end
because the upstream server refuses GCP / AWS / datacenter IPs.
Re-run from a domestic uplink or via a residential proxy.

| Slice | DEFERRED ref | Verify with |
|---|---|---|
| Wikidata player metadata (DOB, role, handedness, bowling style) | §1.1 | `cricdex data ingest wikidata` then `cricdex profile "V Kohli"` |
| Reddit JSON pulse | §1.2 | `cricdex data ingest reddit` then `cricdex profile "MS Dhoni"` |
| Cricbuzz match-api live feed | §1.3 | `cricdex live --match <id>` (cmd lands once feed unblocks) |
| ESPNcricinfo player profile scrape | §1.4 | `cricdex profile "RG Sharma"` should populate Cricinfo fields |
| BCCI Domestic Ranji + Hazare | §1.5 | `cricdex data ingest cricsheet -c indian_domestic_male` |
| WPL 2026 PC + SA20 2023 PC PDFs | §1.6 | `cricdex data ingest rules` should pick them up |
| BCCI Code of Conduct mirror (TLS fix) | §1.7 | `cricdex data ingest rules` (drops the CoC clauses) |

## Phase 2 — grassroots + identity

| Slice | DEFERRED ref | Verify with |
|---|---|---|
| Predict daily-prediction game (blocked by §1.3) | §2.1 | `cricdex predict play` |
| CricHeroes grassroots scraper | §2.2 | `cricdex data ingest cricheroes` |
| Photo-CLIP identity disambiguation (blocked by §2.2) | §2.3 | `cricdex scout disambiguate "JJ Smith"` |
| Replacement Delta (blocked by §1.5) | METRICS | `cricdex leaderboard replacement_delta` |

## Phase 3 — auction-v2 (GPU)

| Slice | DEFERRED ref | Verify with |
|---|---|---|
| Multi-agent PettingZoo self-play | §2.6 | `cricdex auction train-grpo --multi-agent` |
| Bid-history-mined personality YAML | §2.6 | `cricdex auction train-grpo --personalities yaml` |
| Squad-quality terminal bonus refinements | §2.6 (open follow-on) | reward-shape A/B in same trainer |

## Phase 4 — year-2 advanced (CV + voice)

| Slice | DEFERRED ref |
|---|---|
| OpenBoundary Hawk-Eye OSS | §3.1 |
| ChuckCheck elbow flex from monocular pose | §3.2 |
| Voice analyst earpiece (LiveKit + STT/LLM/TTS) | §3.3 |
| ScoutVLM YouTube ball-by-ball | §3.4 |
| Highlight CV auto-clip | §3.5 |
| Tournament management B2B | §3.6 |
| Voice-cloned commentary translation | §3.7 |

## Phase 5 — API + infra

| Slice | DEFERRED ref | Verify with |
|---|---|---|
| GraphQL layer | §4.1 | `cricdex api graphql --serve` (when wired) |
| Auth + rate-limit (Cloudflare Worker + API keys) | §4.2 | curl with API key header |
| GHCR pre-built image | §4.3 | done — `docker pull ghcr.io/aaryan-nakhat/cricdex:latest` |
| Live → dashboard websocket | §2.8 (blocked by §1.3) | dashboard auto-refresh on a live match |

## Phase 6 — maintenance

Rolling cadence work: rule corpus refresh, People Register refresh,
Cricsheet ETL refresh, metrics + records JSON refresh. See
[`DEFERRED.md`](DEFERRED.md) §5.
