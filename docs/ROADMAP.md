# Roadmap

What CricDex does today, what comes next, what's further out, and what it deliberately won't do. How each
shipped model works is in [METHODOLOGY.md](METHODOLOGY.md); the reasoning behind past choices is in
[DECISIONS.md](DECISIONS.md); dated changes are in [CHANGELOG.md](CHANGELOG.md).

CricDex is **Cricsheet-only**: every number comes from Cricsheet's ball-by-ball data, plus the Cricsheet
People Register for identity, a one-time Wikidata pull for dates of birth and photos, and one AI-classified
taxonomy (role, bowling type, batting slot, country).

---

## Shipped

**Data and identity**
- Cricsheet ingest → DuckDB for eight men's collections (IPL, BBL, SA20, CPL, T20 Blast, SMAT, men's T20Is,
  recently played), with all-time, last-3-years and last-year windows.
- One Cricsheet id per player from each match's registry, with the People Register (18,651 players, 99.8%
  linked to ESPNcricinfo) as fallback and ~7,500 name variants for search.
- Merged venue names: one `"<ground>, <city>"` per ground, renamed grounds under their current name, old
  spellings kept as aliases.
- Indian domestic T20 (Syed Mushtaq Ali Trophy) via Cricsheet's state-team archives: 689 matches.
- Wikidata enrichment: date of birth, photo and socials for 331 of 342 cached players.
- AI-classified taxonomy for 2,525 players (an LLM via LiteLLM, any provider set in `.env`).

**Models and metrics**
- **Net Game Impact (NGI)**: a calibrated XGBoost win-probability model, ΔWP per ball credited to batter
  and bowler.
- Nine context metrics: Pressure Runs, Intent Curve, Dot-Ball Recovery, Counter-Attack, Boundary
  Dependency, Pressure Conversion, Wicket Quality, Crease Longevity, Slow-Start Cost.
- Wicketkeeping and Fielding boards: twelve leaderboards in all, each in three time windows.
- Dismissal-aware Bayesian ratings (NumPyro / JAX): scoring, survival, economy and strike skills with
  uncertainty, ADVI by default and NUTS available; checked against NUTS on the IPL.
- Ratings backtests: established IPL players and IPL newcomers rated from other leagues
  (`scripts/backtest_ratings.py`, `scripts/backtest_newcomers.py`).
- Head-to-head probabilities from the rating uncertainty.
- Style twins (cosine k-NN: 13 axes for batters, 3 for bowlers) and co-faced cohorts on every profile.

**Rooms and pages**
- **Scout**: cross-league look-alikes across IPL, SMAT, BBL, SA20, CPL and T20 Blast, with estimated price,
  saving versus the pick, a gem flag, role and batting-slot filters, and one-click draft into the auction.
- **Auction room**: real-rules IPL auction Monte-Carlo with a cross-league pool, IPL-relevance weighting,
  editable Mega / Mini retentions, team personalities, budget-aware bidding, second-price clearing with a
  27 cr cap, two-phase fill and a post-auction player search.
- Matchups, Phase, Form, Partnerships, Aging, Venues, Records (with On This Day), Player Profile and
  Compare pages.

**Surfaces**
- Static website on GitHub Pages (React + Vite), the canonical surface:
  https://aaryan-nakhat.github.io/cricdex/
- `cricdex` CLI and Textual TUI, Streamlit dashboard and FastAPI REST API, all reading the same data.
- `cricdex.web_parity`: the Python twin of the web's Scout, Auction and Head-to-Head logic, held
  identical by parity tests in CI.
- Docker image and Compose stack; a manual `refresh-data` workflow that re-ingests, refits, re-cooks and
  redeploys the site.

---

## Next

Work that needs no new data source.

- **Fielder and non-striker credit in NGI**: share a catch's or run-out's swing with the fielder, and book
  a non-striker run-out to the batter who was out.
- **Venue, phase and era effects in the ratings**: one skill set per career today.
- **Women's collections**: the ingester already knows the WPL, WBBL and women's T20I archives; nothing
  downstream has been built or checked on them yet.
- **Replacement Delta**: NGI against a replacement-level player ("cricket WAR"). Needs a sub-IPL baseline
  to define replacement level; SMAT is the obvious candidate.

## Later

Bigger pieces, most needing new data, a GPU or hosting.

**Grassroots**
- CricHeroes grassroots tier, if a partner API or a Cricsheet-compatible export becomes available; the
  rating model's opponent bridging is what would carry it (a grassroots batter who faced a few known
  semi-pro bowlers gets a sharper rating through them).
- Photo-based identity disambiguation for namesakes across tiers (only needed once a grassroots tier exists).

**Auction v2**
- Multi-agent self-play (every franchise its own learned bidding policy) instead of today's fixed
  personalities.
- Team personalities learned from real auction bid history instead of hand-assigned.

**Video and voice (year 2)**
- Ball tracking and pitch maps from broadcast video; a bowler-action (elbow flex) estimate from pose;
  automatic highlight clips; ball-by-ball extraction from grassroots video; a voice analyst.
- Disguise Coefficient for bowlers (outcome variance for the same line and length), which needs ball
  tracking.

**API and hosting**
- Auth and rate limiting in front of the REST API (required before any public API deploy), then hosting
  the API and the Streamlit dashboard. The website itself is already public.
- A GraphQL layer over the REST functions, if anyone needs it.

---

## Ongoing upkeep

- **Cricsheet refresh** when new matches land: the manual `refresh-data` workflow for the live site, or
  `make refresh COLLECTION=<c>` locally (download → ratings → metrics → site data).
- **People Register refresh** (Cricsheet updates it roughly monthly):
  `uv run python scripts/ingest_people.py --force` (also the first step of `refresh-data`).
- **Taxonomy for new players**: runs inside `refresh-data` when an LLM is configured.
- **Model checks after changes**: re-run the NUTS comparison and the backtests after any change to the
  rating model.

---

## Out of scope

Decided against, not pending.

- **Non-Cricsheet sources**: Reddit sentiment, Cricbuzz live scores, ESPNcricinfo or BCCI scraping (so no
  Ranji Trophy or Vijay Hazare, which Cricsheet doesn't cover ball by ball), extra rulebook PDFs.
- **LLM-written content**: commentary translation, match reports, newsletters, a rules Q&A bot. The LLM
  only tags player facts.
- **Earlier subsystems removed in the consolidation**: the Neo4j scout graph, the MILP auction solver,
  war-room advisor and RL auction prototype, and the rules RAG stack (see the changelog).
- **Fantasy-team optimiser** and **tournament-management software** (CricHeroes already does the latter
  well).
- **Package distribution**: no PyPI package and no published Docker image. The website is the public
  artifact; running it yourself is clone + `uv` or `make docker-up` (see [RUNNING.md](RUNNING.md)).
