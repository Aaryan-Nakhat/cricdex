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

Wikidata one-time enrichment stays (331 of 342 cached players found,
all with a DOB; the remaining 11 are obscure players absent from Wikidata).

## A — grassroots + identity (year 2)

| Slice | DEFERRED ref | Verify with |
|---|---|---|
| CricHeroes grassroots scraper | §2.2 | `cricdex data ingest cricheroes` |
| Photo-CLIP identity disambiguation (blocked by §A-CricHeroes) | §2.3 | `cricdex scout disambiguate "JJ Smith"` |
| **Replacement Delta** metric (needs a domestic-tier baseline) | METRICS §"Still planned" | `cricdex leaderboard replacement_delta` |

## C — auction-v2 (GPU compute)

| Slice | DEFERRED ref | Verify with |
|---|---|---|
| Multi-agent PettingZoo self-play (every slot a policy) | §2.6 | new RL trainer over the auction env |
| Bid-history-mined personality YAMLs (replace hand-authored archetypes) | §2.6 | franchise archetypes extracted via an LLM |

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
| Public API / dashboard hosting | n/a | The web app is already live on GitHub Pages; only the FastAPI app and Streamlit dashboard are local-only today. Hosting them needs the auth + rate-limit row above first. |

## F — maintenance cadence

Rolling work the v1 release surfaces but doesn't automate:

- People Register refresh — Cricsheet's `people.csv` updates monthly.
- Cricsheet ETL refresh — pull when new matches add to a collection
  (the manual `refresh-data` workflow for the live site, or
  `make refresh COLLECTION=<c>` locally).
- Metrics + site JSON refresh — `cricdex data ingest metrics
  -c <collection>` after a Cricsheet update (it also re-exports that
  collection's site data).
- WP / Bayes refits when the underlying data shifts materially.
