# Deferred + blocked work

Living catalogue of every known-incomplete piece. Each row has:
- **What** the gap is.
- **Why** it's not done.
- **Fix** — concrete plan to close it.
- **Smoke test** — one-liner the future maintainer can run to verify
  it's fixed.

---

## 1. Datacenter-IP-blocked feeds

Pipelines are correct end-to-end; the issue is purely the upstream
server refusing GCP / AWS IPs. Move each pull to a residential
network / mobile hotspot / VPN, or wire the publisher's official
partner API.

### 1.1 Wikidata SPARQL (`cricdex.scout.ingest.wikidata`)

- **What:** Wikidata DOB / country / gender enrichment table
  (`wikidata_players`) for every Cricinfo-bridged player.
- **Why blocked:** WDQS aggressively rate-limits our GCP IP at
  "1 req / min", so the full 18k-row pull takes ~6 hours and burns
  through the script's retry budget.
- **Fix options (cheapest first):**
  1. Run `make docker-ingest-wikidata` from a residential network /
     home VPN. Pipeline is resumable via the JSONL checkpoint under
     `data/register/wikidata_checkpoint.jsonl`.
  2. Swap to Wikidata's `wbgetentities` REST API (different rate
     limiter, per-entity rather than SPARQL).
  3. Use WBI client with a registered OAuth consumer.
- **Smoke test:** `uv run python -c "import duckdb; con =
  duckdb.connect('data/cricsheet/cricsheet.duckdb', read_only=True);
  print(con.execute('SELECT COUNT(*) FROM
  wikidata_players').fetchone())"` — expect > 15,000.

### 1.2 Reddit JSON (`cricdex.pulse.sources.reddit_public`)

- **What:** Player sentiment + theme aggregates from r/Cricket +
  related subs.
- **Why blocked:** Reddit 403s the public `*.json` endpoint from
  datacenter IPs.
- **Fix:** Switch to PRAW with personal OAuth. The `bots` optional
  extras already pin `praw>=7.8.0`. Register an app at
  `reddit.com/prefs/apps`, set `REDDIT_CLIENT_ID` +
  `REDDIT_CLIENT_SECRET` + `REDDIT_USER_AGENT` in `.env`, write
  `pulse/sources/reddit_oauth.py` calling
  `praw.Reddit(...).subreddit(...).top(...)`.
- **Smoke test:** `make docker-pulse-run PERIOD=week LIMIT=20`
  produces a non-empty `data/pulse/posts_<date>.jsonl`.

### 1.3 Cricbuzz match-api (`cricdex.live.cricbuzz`)

- **What:** Live-match index, scorecards, and ball-by-ball
  commentary.
- **Why blocked:** Cricbuzz 403s the mobile-app JSON paths from
  datacenter IPs.
- **Fix:** Run from a residential network (works on day 1), or
  apply for Cricbuzz's official partner API. A Playwright fallback
  is possible but adds a 200 MB headless-browser dep.
- **Smoke test:** `make docker-live-snapshot` writes a
  timestamped JSON under `data/live/`.

### 1.4 ESPNcricinfo profiles

- **What:** Per-player Cricinfo profile data (DOB, batting / bowling
  style, role) layered on top of the People Register's
  `key_cricinfo`.
- **Why blocked:** Akamai 403 on every non-browser client. We
  pivoted to Wikidata as the structured-metadata source, but
  Wikidata only has DOB / country / gender — not batting hand or
  bowling style.
- **Fix:** Playwright headless browser with sensible jitter, or
  scrape via a residential-proxy provider (e.g. Bright Data /
  Smartproxy). Cache HTML on disk so we never re-fetch a page.
- **Smoke test:** A new DuckDB table `cricinfo_profiles` exists
  with one row per `key_cricinfo` ID and `batting_style` /
  `bowling_style` columns populated for ≥ 80 % of rows.

### 1.5 BCCI Domestic (Ranji + Hazare)

- **What:** Ball-by-ball or scorecard ingest for Ranji Trophy +
  Vijay Hazare. Today's `indian_domestic_male` collection covers
  only Syed Mushtaq Ali Trophy via the Cricsheet state-team
  aggregator.
- **Why blocked:** BCCI's domestic site is a SPA — there's no static
  HTML to scrape, and the data endpoints are obfuscated behind the
  JS bundle. Cricsheet doesn't publish Ranji / Hazare on India.
- **Fix:** Playwright that loads the SPA, waits for hydration, and
  scrapes the rendered DOM (or intercepts the SPA's XHR calls in
  the browser to find the real endpoint). Long term: BCCI / Cricinfo
  partnership for a clean feed.
- **Smoke test:** `matches_ranji_male` table populated with ≥ 200
  matches per recent season + appropriate `match_type='Test'` or
  `'MDM'` rows.

### 1.6 WPL 2026 PC, SA20 2023 PC PDFs

- **What:** Two rule-corpus PDFs that the rules pipeline can't
  fetch.
- **Why blocked:** `wplt20.com` and `sa20.co.za` serve a Next.js
  SPA shell instead of the underlying PDF when the request doesn't
  come from a real browser.
- **Fix:** Playwright fetcher in `cricdex.rules.ingest` that
  navigates the SPA, locates the actual PDF blob, and saves it.
  Once landed, the rest of the rules pipeline picks them up
  automatically.
- **Smoke test:** `data/rules/raw/wpl_pc_2026.pdf` and
  `data/rules/raw/sa20_pc_2023.pdf` are real PDF files (magic
  bytes `%PDF`), and `make docker-embed-rules` indexes their
  clauses without warnings.

### 1.7 BCCI Code of Conduct mirror (TLS hostname mismatch)

- **What:** The 2025 BCCI Code of Conduct PDF mirrored at
  `hycricket.org`.
- **Why blocked:** Host's TLS certificate is for a different
  hostname; httpx rejects it.
- **Fix:** Either (a) get BCCI's own URL once they publish it, or
  (b) allow per-source TLS overrides in `cricdex.rules.ingest` via
  an httpx `verify=False` opt-in flag — only for sources that
  explicitly opt-in in the manifest, so the global default stays
  strict.
- **Smoke test:** `data/rules/raw/bcci_code_of_conduct_2025.pdf`
  exists and starts with `%PDF`.

---

## 2. Module-level partials

### 2.1 `predict` daily-prediction game

- **What:** Daily / match-day predictions (winner, top scorer,
  total over/under, player-of-match) with a leaderboard.
- **Why deferred:** Requires upcoming-match metadata, which only
  arrives once the `live` Cricbuzz feed unblocks (see §1.3).
- **Fix:** Once `live.cricbuzz.live_index()` returns real rows,
  build:
  1. `predict.engine` with DuckDB tables `predictions(user,
     match_id, pick_type, pick_value, submitted_at)` +
     `scoring(user, match_id, points)`.
  2. Streamlit page with pre-match form + post-match leaderboard.
  3. Cron that calls `score_match(match_id)` after the live feed
     marks a match as completed.
- **Smoke test:** Submit a prediction via the page, run the cron,
  see your row in the leaderboard with the correct points.

### 2.2 CricHeroes grassroots scraper

- **What:** Per-player profiles + match scorecards from
  cricheroes.com for the long-tail amateur tier.
- **Why deferred:** ToS sensitivity (their site is public but
  scraping at scale needs care), plus the official partner-API
  path is the right long-term solution.
- **Fix:**
  1. Apply for the CricHeroes partner API. Pitch is "open scout
     platform credits CricHeroes as the upstream."
  2. Until then, slow respectful scrape (1 req / 2s) of public
     player URLs with aggressive caching.
- **Smoke test:** `people` table's `key_cricheroes` column
  populated for ≥ 1000 rows (currently 111).

### 2.3 Photo-CLIP identity disambiguation

- **What:** When two players share `unique_name` after
  normalization, use CLIP embeddings of their Cricinfo profile
  headshots to disambiguate.
- **Why deferred:** Cricsheet's People Register already resolves
  the vast majority (~17,937 / 17,981) of pro-tier ambiguity. The
  ambiguous cases live in the long tail that depends on the
  CricHeroes + BCCI Domestic scrapes (§1.5, §2.2) landing first.
- **Fix:** `cricdex.scout.identity.photo_match` — download
  headshots, embed via CLIP ViT-B/32, cosine-similarity match.
- **Smoke test:** Top-10 most ambiguous `unique_name` cases each
  resolve to one canonical `cricsheet_id` with confidence ≥ 0.9.

### 2.4 `sticky_dot_pressure` returns 0 rows on small collections — ✅ shipped

- `min_pressure_balls` is now optional; when omitted with
  `auto_threshold=True` (the default) the metric picks
  `max(5, round(0.5 × p75_pressure_balls))` for the collection.
- CLI dropped the hard-coded `--min-balls 30` default in favour of
  the auto-pick.
- Verified: ipl=131 rows, indian_domestic_male=140 rows, bbl=70
  rows, recently_played_30_male=109 rows — every collection now
  yields a populated leaderboard.

### 2.5 Missing novel metrics

Documented in `docs/METRICS.md` "Planned — not yet shipped"
section. Specifically: Net Game Impact (NGI) / Replacement Delta /
Wicket Quality / Phase Dilation / Setting Tax / Disguise
Coefficient. Each needs either a win-probability model (NGI),
opponent OAR (Wicket Quality), or CV-derived release data
(Disguise).

### 2.6 Auction RL self-play (partially landed)

- **What:** End-state goal is PettingZoo + per-franchise personality
  multi-agent self-play across thousands of auction trajectories.
- **Status today:**
  - ✅ `cricdex.auction.rl_env.AuctionEnv` — single-agent Gym-style
    env (16-dim state, 11 discrete bid buckets, shaped per-round
    reward), learner vs N-1 opponents.
  - ✅ `cricdex.auction.grpo` — GRPO (DeepSeek 2024) trainer, no
    value head, group-relative advantage. Produces a `policy.zip`
    that `dashboard/pages/B_Auction_Simulator.py` can load.
  - ✅ `cricdex.auction.real_pool` — real 429-player IPL pool driven
    by NumPyro Bayes skills (skill → projected_value, T20I dominant
    team → nationality, IPL career balls → role + recency) plus 6
    hand-authored franchise archetypes (`FRANCHISE_ARCHETYPES`).
  - ✅ `scripts/train_auction_grpo.py` accepts `--pool real
    --diverse-franchises` to train against the real pool with mixed
    opponent personalities. CPU smoke (30 epochs × 4 group, real
    pool, 6 archetypes) lands in -15..+3 reward (vs -40..-30 on the
    synthetic random pool), trending positive — the env now carries
    learnable signal.
  - ⏳ Actual GPU training run (8 k epochs × 16 group, ~10-30 min on
    A100 / 4090) — pending user-side GPU. Command + watch signals
    documented in `docs/RUNNING.md`.
  - ✅ Squad-quality terminal bonus is shipped — see
    `TERMINAL_VALUE_COEF` / `ROLE_UNFILL_PENALTY` in `rl_env.py`.
    meanR shifted from -15..+3 to 0..+30 on the real-pool smoke,
    so the env now has clean positive signal for assembling a
    full XI.
  - ⏳ Multi-agent PettingZoo self-play (every slot a policy, not
    just slot 0), with personality YAML extracted via Gemini from
    10 yr of IPL bid history (the real auction-v2 milestone).
- **Known training-data limits to fix before the policy is
  trustworthy:**
  - **People Register name collisions** — e.g., Rashid Khan resolves
    to country = `Nepal` because two players share the unique_name.
    Cheap fix is a manual override map keyed on cricsheet_id.
  - **`value_scale` is hand-calibrated**, not fit to historical IPL
    auction prices. iplt20.com / espncricinfo auction-history pages
    are datacenter-IP-blocked (§1) — once that scrape unblocks, fit
    `value_scale` (and per-role floors) to real sold-price residuals.
  - **No handedness / bowling-style on Player nodes.** Filters like
    "left-arm pace replacement" can't be expressed yet. Same
    Wikidata / Cricinfo scrape unblock as §1 covers this.
  - **Franchise archetypes are guesses**, not bid-history-mined.
    Improve by extracting per-team per-year aggression / role-bias
    YAMLs (Gemini on the unblocked auction-ledger PDFs).
- **Why the v2 leg stays deferred:** Full multi-agent self-play on
  10 agents needs hours of GPU compute; current scaffold runs on CPU
  in minutes which is sufficient for the practitioner-facing
  "realistic price band + AI bidder vs MC opponents" demo.
- **Fix path:** Wrap `AuctionEnv` in a PettingZoo AECEnv, lift the
  learner from slot 0 to all slots, train each franchise's policy
  with personality-conditioned priors. Re-use `grpo.PolicyMLP` per
  agent.

### 2.7 Rules retrieval reranker — ✅ shipped

- Hybrid retrieval is dense (`Snowflake/snowflake-arctic-embed-l-v2.0`,
  multilingual, MRL-truncated to 384-dim) + BM25 + RRF fusion + Jina
  cross-encoder rerank (`jina-reranker-v2-base-multilingual`) on the
  fused top-K. Falls back to RRF order when `JINA_API_KEY` is unset.
- Open follow-on: build a 50-query hand-labelled eval set to track
  top-1 accuracy across model swaps. Not blocking.

### 2.8 Live → dashboard web socket

Depends on §1.3 unblocking. Once live feed lands, push insights
via FastAPI WebSocket to a new dashboard page.

---

## 3. Year-2 deferred per scope cuts

These shipped to `DEFERRED` in `docs/DECISIONS.md`. Recapped here
so the catalogue is complete.

### 3.1 OpenBoundary — Hawk-Eye OSS

Ball tracking + pitch map + speed estimation from any broadcast
video. Heavy CV stack: YOLO11 fine-tuned on cricket-ball dataset,
SAM2 zero-shot pitch corners, ByteTrack + Kalman, single-cam
physics-aware optimisation for 3D recovery. Validate vs published
Hawk-Eye on 50 IPL deliveries.

### 3.2 ChuckCheck — bowler elbow flex

Monocular 3D pose via GVHMR / WHAM, compute elbow extension at
delivery, compare against ICC's 15° threshold. Controversy
gradient — strong disclaimer + research-tool framing required.

### 3.3 Voice analyst — coach earpiece

LiveKit + STT (faster-whisper) + multi-agent LLM
(MatchupAgent / VenueAgent / FormAgent / OppoAgent /
StrategyAgent) + TTS (Coqui XTTS-v2). User's existing
`tele-server-new` repo is the natural starting fork.

### 3.4 ScoutVLM — VLM-driven ball-by-ball from YouTube

Gemini 2.5 Flash video understanding extracts ball-by-ball JSON
from grassroots match uploads (BCCI Domestic channel + state
assoc channels). Feeds the scout grassroots tier with data
Cricsheet doesn't publish.

### 3.5 Highlight CV — auto key-moment clips

CV detect wickets + boundaries from broadcast frames → ffmpeg
trim clips → S3-ish CDN. Pairs naturally with match-report
generation.

### 3.6 Tournament management B2B

CricHeroes already does grassroots tournament management. Partner
via API instead of competing.

### 3.7 Voice-cloned commentary translation

Final-feature year-2 milestone. XTTS-v2 / F5-TTS / OpenVoice +
AI4Bharat IndicTTS. Need opt-in licensing from retired
commentators (Harsha Bhogle, Sunil Gavaskar, Ramiz Raja) before
shipping cloned voices publicly.

---

## 4. API + infra deferrals

### 4.1 GraphQL layer

- **Why:** REST + Pydantic models is fine for v1. GraphQL
  becomes valuable once external consumers want partial fetches
  + nested traversal (player → metrics → twins → matches).
- **Fix:** Strawberry-FastAPI on top of the existing REST
  endpoints' underlying functions.

### 4.2 Auth + rate-limit

- **Why:** No auth in v1 — bind behind a reverse proxy.
- **Fix:** Cloudflare Worker in front of the FastAPI app
  (Workers free tier 100 k req/day). Auth via API keys issued
  through a simple `cricdex.api.keys` table in Supabase.

### 4.3 GHCR pre-built image

- **Why:** Today a fresh clone builds the cricdex:dev image
  locally (~10 min, ~9.8 GB). Acceptable for one-time setup but
  painful for CI / multi-machine usage.
- **Fix:** GitHub Actions step that pushes `cricdex:dev` to
  `ghcr.io/aaryan-nakhat/cricdex:latest` on every main push.
  Docker compose pulls instead of builds.

### 4.4 R2 backup activation

- **Why:** Backup CLI + Makefile targets shipped (`make backup`,
  `make restore`, `make backup-list`) but the bucket itself doesn't
  exist yet so no off-VM copy of the 43-min Qdrant reindex or the
  599 MB Cricsheet DuckDB has been pushed. VM dies → that work is
  redone from scratch.
- **Fix (5 min, browser-side):**
  1. `dash.cloudflare.com → R2 → Create bucket "cricdex-backups"`.
  2. R2 → "Manage R2 API Tokens" → Create token, Object Read & Write,
     scoped to the bucket.
  3. Paste `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`,
     `R2_BUCKET=cricdex-backups` into `.env`.
  4. `make backup WHAT=all` — uploads ~700 MB tarball, takes a couple
     of minutes on a domestic uplink, free.
- **Smoke test:** `make backup-list` shows the timestamped object;
  `make restore WHAT=rules` on a fresh checkout pulls it back.

---

## 5. Maintenance items

### 5.1 Rule corpus refresh

Run `make docker-ingest-rules-download && parse-pdfs && embed`
quarterly (each ICC playing conditions revision). The version
model in `cricdex.rules.manifest` already allows new entries to
coexist with old.

### 5.2 People Register refresh

Cricsheet updates `people.csv` continuously. Re-run
`make docker-ingest-people` monthly to pick up new cross-IDs.

### 5.3 Cricsheet ETL refresh

Match data grows with every IPL / intl match. Run
`make docker-ingest-cricsheet COLLECTION=ipl` after a season
ends (or daily during a season via GitHub Actions cron).

### 5.4 Metrics + records JSON refresh

After any ball-by-ball refresh, re-run:

```bash
make docker-metrics-all COLLECTION=ipl
make docker-records-all COLLECTION=ipl
```

so the dashboard + newsletter pick up the latest snapshots.

---

## How to use this doc

When you (or future-you) come back to CricDex:

1. Read this file before anything else.
2. Pick one item.
3. Apply its **fix**.
4. Run the **smoke test**.
5. Update this file — remove the row, or move it to a
   "shipped after v1" archive section below.

### Shipped after v1

_(empty — every row above is still open.)_
