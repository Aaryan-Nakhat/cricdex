# Scout module

Opposition-bridged ratings + cross-competition look-alike search. The
eventual product is a tool an IPL analyst (or a fan!) can use to ask:

- "Which uncapped Mumbai leg-spinners aged 18-22 dismissed at least
  three semi-pro batters last season?"
- "Who plays most like a 22-year-old Tilak Varma?"
- "Show me Bumrah's hardest five batters this IPL by adjusted average."

Today's reality is narrower — we have the pro tier (Cricsheet + people
register) and the ratings infrastructure that the answers ride on. Scout
is file-driven (DuckDB + exported JSON); there is no graph database. The
semi-pro tier is SMAT via Cricsheet; a CricHeroes grassroots tier is year-2
backlog, and BCCI-domestic scrapes are out of scope (Cricsheet-only).

## Tiers

| Tier | Source | Status |
|---|---|---|
| Pro (intl + IPL + major T20) | Cricsheet ball-by-ball | ✅ ingested |
| Identity bridge | Cricsheet People Register (18,651 players, 99.8% Cricinfo coverage) | ✅ — see [IDENTITY.md](IDENTITY.md) |
| Bayesian opponent-adjusted ratings | NumPyro / JAX (ADVI default, NUTS available) | ✅ — first cut |
| Player profile (DOB, photo, socials) | Wikidata one-time enrichment | ✅ — 342 players cached, 331 with a DOB |
| Role / bowling type (seam-spin) / batting slot / country | LLM taxonomy (an LLM via LiteLLM, `LLM_MODEL`; shown as "AI-classified") | ✅ — 2,525 players |
| Semi-pro (SMAT) | Cricsheet `indian_domestic_male` | ✅ ingested (Ranji / Hazare removed — out of scope) |
| Grassroots (CricHeroes) | CricHeroes scrape / partner API | year-2 ([`ROADMAP.md`](ROADMAP.md#later)) |
| Style-twin (k-NN over rating vector) | feature-space nearest neighbours | ✅ — on every profile |
| Scout look-alikes (all surfaces) | **One implementation** (`cricdex.web_parity` ⇄ `site/src/pages/Scout.tsx`, locked by `test_web_parity.py` in CI) shipped identically on the React site, Streamlit, CLI (`cricdex scout look-alikes`) and the TUI **Scout** tab: pick an active IPL player → similar IPL peers, then uncapped SMAT, then overseas BBL / SA20 / CPL / T20 Blast (within-tier skill-standing z-score), with per-row est. crore price + saving-vs-pick (budget swap), an uncapped-**gem** flag, role/batting-slot filters, and one-click **draft** into the Auction room | ✅ |

## End-to-end pipeline today

```bash
# Ingest Cricsheet + cross-IDs
make docker-ingest-cricsheet COLLECTION=ipl
make docker-ingest-people

# Bayesian ratings
make docker-scout-rate COLLECTION=ipl STEPS=12000

# Re-cook the exported JSON the scout surfaces read
make docker-export COLLECTION=ipl

# Look-alikes (web-identical) + browse
cricdex scout look-alikes "V Kohli"
# - Streamlit dashboard: http://localhost:8511
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
higher = better. A player's **complete value** adds their two relevant
axes after putting each in the same unit (its population spread — the
axes are a runs rate and a wicket log-odds), so a fast slogger who gets
out often is no longer over-rated on scoring alone. Every matchup is
fitted, even a 1-ball one; the prior does the shrinking. The plain-English
walkthrough (with a worked example) is [METHODOLOGY.md §4](METHODOLOGY.md#4-bayesian-skill-ratings);
the look-alike formula is [§5](METHODOLOGY.md#5-scout-look-alikes); the full
model is in [`STUDY_GUIDE.md`](STUDY_GUIDE.md) §5.

The same model design extends downward later: when we add CricHeroes
amateur balls, batters who happen to have faced one or two known
semi-pro bowlers get their grassroots ratings sharpened via the
"bridge" of those known opponents. That's the
Opposition-Adjusted Rating (OAR) that powers the grassroots scout.

## Not yet shipped

- CricHeroes grassroots tier + its identity bridge (year-2; BCCI-domestic
  scrapes are out of scope).
- Photo-CLIP embedding for hard identity disambiguation.
- A `/scout` filter UI with 25+ filter dimensions (today: role /
  batting-slot filters).

## Where to read next

- [METHODOLOGY.md](METHODOLOGY.md) — every model in plain English.
- [ratings/README.md](../src/cricdex/scout/ratings/README.md) — model spec.
- [IDENTITY.md](IDENTITY.md) — cross-ID bridge.
