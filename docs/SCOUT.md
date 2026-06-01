# Scout module

Player graph + opposition-bridged ratings + scout search. The eventual
product is a tool an IPL analyst (or a fan!) can use to ask:

- "Which uncapped Mumbai leg-spinners aged 18-22 dismissed at least
  three semi-pro batters last season?"
- "Who plays most like a 22-year-old Tilak Varma?"
- "Show me Bumrah's hardest five batters this IPL by adjusted average."

Today's reality is narrower — we have the pro tier (Cricsheet + people
register) and the graph + ratings infrastructure that the answers will
ride on. Other tiers (BCCI domestic, CricHeroes grassroots) land in
Phase 2 follow-ups.

## Tiers

| Tier | Source | Status |
|---|---|---|
| Pro (intl + IPL + major T20) | Cricsheet ball-by-ball | ✅ ingested |
| Identity bridge | Cricsheet People Register (17,981 players, 99.8% Cricinfo coverage) | ✅ — see [IDENTITY.md](IDENTITY.md) |
| Player graph | Neo4j — Player / Match / Venue + FACED edges, **scoped per collection** (each Player node carries a `collection` tag, so ipl / bbl / t20s_male / indian_domestic_male / recently_played_30_male are independent subgraphs in one DB). Twins / find-replacement / advisor all take a `collection` arg. | ✅ all 5 collections |
| Bayesian opponent-adjusted ratings | NumPyro / JAX (ADVI default, NUTS available) | ✅ — first cut |
| Cricinfo player profile (DOB, role, style) | Cricinfo scrape | planned |
| Semi-pro (Ranji / SMAT / Hazare) | BCCI Domestic scrape | planned |
| Grassroots (CricHeroes) | CricHeroes scrape / partner API | planned |
| Style-twin (k-NN over rating vector) | sentence-transformers + Qdrant | planned |
| `/scout` web filter | Streamlit / Next.js | planned |

## End-to-end pipeline today

```bash
# Ingest Cricsheet + cross-IDs
make docker-ingest-cricsheet COLLECTION=ipl
make docker-ingest-people

# Spin up Neo4j, populate the graph
make docker-scout-up
make docker-scout-bootstrap
make docker-scout-populate COLLECTION=ipl

# Bayesian ratings
make docker-scout-rate COLLECTION=ipl STEPS=12000

# Browse
# - Neo4j Browser: http://localhost:7474
# - Streamlit dashboard (Phase 1 metrics): http://localhost:8511
```

## Why Bayesian instead of plain SQL averages

A standard scorecard average treats a wicket from Bumrah and a wicket
from a county trundler as equivalent. The Bayesian model fits latent
skills per batter and per bowler, so the strength of every opponent
feeds into every estimate. Hierarchical priors handle small samples
gracefully — a player with 30 balls faced is shrunk toward the global
mean, while a player with 3,000 balls is barely shrunk at all.

The model is **dismissal-aware**: a joint fit of two coupled
likelihoods (a runs Negative-Binomial + a per-ball dismissal
Binomial) gives each batter both a **scoring** skill and a **survival**
(dismissal-resistance) skill, and each bowler both an **economy** and
a **strike** (wicket-taking) skill — four opponent-adjusted axes, all
higher = better. A player's **complete value** is the sum of their two
relevant axes, so a fast slogger who gets out often is no longer
over-rated on scoring alone. See `docs/STUDY_GUIDE.md` §5.7 for the
full model.

The same model design extends downward later: when we add CricHeroes
amateur balls, batters who happen to have faced one or two known
semi-pro bowlers get their grassroots ratings sharpened via the
"bridge" of those known opponents. That's the
Opposition-Adjusted Rating (OAR) that powers the grassroots scout.

## What's strictly Phase 2 work, not yet shipped

- BCCI Domestic / CricHeroes scrapers + their identity bridges.
- Photo-CLIP embedding for hard identity disambiguation.
- `TWIN_OF` edges in the graph using k-NN over rating + metric vectors.
- `/scout` web UI with 25+ filter dimensions.
- Press-tour outreach to KKR / GT / RR analytics teams.

## Where to read next

- [graph/README.md](../src/cricdex/scout/graph/README.md) — Neo4j schema and Cypher cookbook.
- [ratings/README.md](../src/cricdex/scout/ratings/README.md) — model spec.
- [IDENTITY.md](IDENTITY.md) — cross-ID bridge.
