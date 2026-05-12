# Roadmap

## Phase 1 (Month 1–2): Foundations + CricMetrics + CricRules

- Cricsheet ETL → DuckDB.
- Cricinfo Statsguru scraper.
- Identity resolution v1 (pro tier).
- Novel metrics v1: Pressure Runs ✅, Intent Curve ✅, Recoverability ✅, Counter-Attack ✅, Boundary Dependency ✅, Sticky Dot Pressure ✅. (Wicket Quality deferred — needs scout OAR ratings.)
- Identity resolution v1 ✅ — via Cricsheet People Register cross-ID load.
- Public leaderboard ✅ — Streamlit dashboard on :8511 with per-metric tabs.
- Public leaderboards.
- Rulebook PDF ingest (MCC + ICC PCs + IPL + Hundred + BBL + SA20 + ILT20 + MLC + CPL + LPL + WPL + Domestic).
- Marker PDF parser + clause-hierarchy chunker.
- Qdrant index + hybrid retrieval (BM25 + dense + rerank).
- `/rules` chat UI.

## Phase 2 (Month 3–4): Scout v1

- BCCI Domestic scrapers — partial: Syed Mushtaq Ali Trophy ✅ via Cricsheet state-team aggregator (689 matches). Ranji Trophy + Vijay Hazare + age-group ⏳ (Cricsheet doesn't publish them; need BCCI scrape or Cricinfo scrape, both behind anti-bot walls).
- CricHeroes scraper (slow respectful) + partner-API outreach.
- Photo CLIP embeds for identity resolution.
- Neo4j graph populated for pro + semi-pro tiers ✅ for IPL; SMAT pending populate.
- Bayesian rating with opponent bridging ✅ for IPL.
- `/scout` filter UI + player cards.
- Style-twin search (k-NN in metric space) ✅.

## Phase 3 (Month 5–6): Social Pulse + records + comparator + reports

- Reddit + Bluesky + YouTube comments + Telegram public channel ingest.
- Twitter via Apify spot-scrape.
- Sentiment + emotion + claim extraction (Gemini Flash).
- Hype-Reality gap weekly post.
- Rumor cluster detection.
- Records search + On-This-Day digest.
- Career comparator UI.
- Auto match-report generator.

## Phase 4 (Month 7–8): AuctionGT (pre-Nov-2026 auction)

- Auction history scrape (iplt20.com + Wikipedia).
- Player price predictor (XGBoost).
- Per-franchise personality YAMLs (LLM-extracted).
- PettingZoo + SB3 multi-agent self-play.
- OR-Tools constraint solver for purse/slot/overseas caps.
- Streamlit war-room UI.
- Auction-week live marketing blitz.

## Phase 5 (Month 9–10): Live + Venues + Predict Game + Newsletter + DRS Sim

- Live scorecard aggregator (Cricbuzz unofficial JSON).
- Win-probability model + live-insight tagger.
- Per-venue pitch + dew + weather archive.
- Predict-game leaderboard.
- Newsletter engine (per-team/player subscriptions).
- DRS scenario simulator + umpire practice game.

## Phase 6 (Month 11–12): Profiles + Commentary translation (text) + Women's first-class + Press tour

- Public player profiles + claim flow.
- Multi-language commentary translation — text only (Hindi, Tamil, Bengali, Urdu, Sinhala).
- Women's cricket data parity audit (BCCI Women's Domestic, WBBL, Hundred Women's, WPL).
- IPL franchise outreach + private demos.
- v1.0 launch press tour.

## Deferred (year 2+)

- OpenBoundary — ball tracking from broadcast video (CV stack).
- ChuckCheck — bowler elbow flex via monocular 3D pose.
- Voice analyst — coach earpiece (LiveKit / STT-LLM-TTS).
- ScoutVLM — VLM-driven ball-by-ball extraction from YouTube grassroots video.
- Highlight CV — auto key-moment clip extraction.
- Tournament management B2B (partner with CricHeroes instead of competing).
- **Voice-cloned commentary translation — final-feature milestone.** Clone English commentators (XTTS-v2 / F5-TTS / OpenVoice) and synthesise target-language audio in their voice. Ship after text-translation v1 proven + opt-in licensing secured with retired commentators.
