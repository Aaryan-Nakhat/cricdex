# Deferred work + known gaps

Genuine gaps in the **Cricsheet-only** CricDex. Each row: what's missing,
why, and the concrete fix. The phase-ordered view is [`TODO.md`](TODO.md);
the prioritised backlog with rationale is [`VNEXT.md`](VNEXT.md).

> **Removed, not deferred.** Non-Cricsheet sources (Reddit sentiment,
> Cricbuzz live, ESPNcricinfo scrape, BCCI Ranji/Hazare ingest, WPL 2026 /
> SA20 2023 / BCCI Code rule PDFs) and the LLM-convenience features on
> them (commentary translate, match reports, newsletter, DRS placeholder)
> were deleted from the codebase — they are **out of scope**, not pending.
> Wikidata one-time enrichment **shipped** (dob/photo/socials for 289/300
> active players; the other 11 are genuinely absent from Wikidata).

---

## §grassroots — domestic + grassroots tiers (year 2)

- **§2.2 CricHeroes grassroots scraper** — pull club/age-group scorecards
  to extend the player graph below first-class. Fix: build
  `cricdex.scout.ingest.cricheroes`; verify `cricdex data ingest cricheroes`.
- **§2.3 Photo-CLIP identity disambiguation** (needs §2.2) — resolve
  namesakes across tiers via profile-photo embeddings.
- **Replacement Delta metric** (needs a domestic-tier baseline) — "cricket
  WAR" against replacement level; deferred until a sub-IPL tier exists to
  define replacement.

## §auction — auction-v2 (GPU)

- **§2.6 Multi-agent GRPO self-play** — every auction slot its own policy
  (PettingZoo), and bid-history-mined personality YAMLs replacing the
  hand-authored archetypes. Needs GPU. The shipped sim uses fixed
  archetypes (see `src/cricdex/auction/`).

## §cv — year-2 advanced (computer vision + voice)

- **§3.1 OpenBoundary** — Hawk-Eye-style ball tracking / pitch maps from
  broadcast video.
- **§3.2 ChuckCheck** — elbow-flex (chucking) estimate from monocular pose.
- **§3.3–3.6** — voice analyst earpiece, ScoutVLM YouTube ingest, highlight
  auto-clip, tournament-management B2B.

## §api — API + infra

- **§4.1 GraphQL layer** over the existing FastAPI functions (Strawberry).
- **§4.2 Auth + rate-limit** — Cloudflare Worker + API-keys table; required
  before any authenticated public deploy.

## §maintenance — rolling cadence

- People Register refresh (Cricsheet `people.csv`, ~monthly).
- Cricsheet ETL refresh when new matches land in a collection.
- Metrics + records JSON refresh after a Cricsheet update
  (`cricdex data ingest metrics --force -c <collection>`).
- Bayes / GRPO refits when the underlying data shifts materially.
