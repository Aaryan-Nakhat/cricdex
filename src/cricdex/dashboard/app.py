"""CricDex Streamlit home — sidebar nav routes to per-feature pages.

The actual feature pages live under `src/cricdex/dashboard/pages/`; Streamlit
auto-discovers them and renders the navigation in the sidebar. Naming
convention: `<order>_<Title>.py` (numeric prefix orders them).
"""

from __future__ import annotations

import streamlit as st

st.set_page_config(page_title="CricDex", page_icon="🏏", layout="wide")
st.title("🏏 CricDex")
st.caption(
    "Open cricket intelligence — novel metrics, rule Q&A, scout graph, "
    "auction war-room, multilingual commentary."
)

st.markdown(
    """
### What this is

CricDex is an open platform for cricket analytics — every metric, rule
answer, scout rating, and auction recommendation is derived from public
sources (Cricsheet ball-by-ball, MCC / ICC / league rulebooks, men's
T20Is for nationality, the Cricsheet People Register for identity)
and shipped with explicit citations or reproducible code. No
black-box scorecards.

### Pages

- **Leaderboards** — nine novel-metric rankings: Pressure Runs,
  Recoverability, Counter-Attack, Boundary Dependency, Intent Curve,
  Sticky Dot Pressure, Phase Dilation, Setting Tax, Wicket Quality,
  plus **NGI (Net Game Impact)** — the WPA-style flagship player
  impact score.
- **Rules Chat** — natural-language Q&A grounded in 11 k+ parsed
  clauses from MCC + ICC + IPL + Hundred + BBL + SA20 + Cricket
  Australia domestic + ICC Codes + Anti-Corruption. Every answer
  cites the source clause.
- **Records** — searchable record book + On-This-Day digest.
- **Match Reports** — auto-generated, hallucination-guarded
  Markdown match reports cached per match.
- **Compare** — side-by-side player comparator (radar + table).
- **Venues** — per-venue innings totals, chase/set win-rate, phase
  rates, dismissal mix.
- **DRS Practice** — 20-scenario umpire-decision game with MCC /
  ICC citations.
- **Auction** — MILP squad optimiser over the real 429-player IPL
  pool (Bayes-skill-driven projected_value), with a war-room
  substitute advisor (graph similarity + budget + role).
- **Player Profile** — per-player aggregate of every CricDex source
  (career totals + novel metrics + Bayes skill + style twins).
- **Translate Commentary** — English → Hindi / Tamil / Bengali /
  Urdu / Sinhala / Marathi / Telugu / Kannada (text-only).
- **Auction Simulator** — Monte-Carlo price-band distribution + an
  optional GRPO RL agent that runs greedy auctions against MC
  opponents.
- **Player Twins** — graph-traversal similarity over the scout
  Neo4j (FACED + TEAMMATE_OF). Run "next Bumrah" / "Dhoni's CSK
  graph cohort" / co-faced-bowlers cohort queries.

### Useful CLI commands

```text
# data ingest
make docker-ingest-cricsheet COLLECTION=ipl
make docker-ingest-people
make docker-metrics-all COLLECTION=ipl
make docker-records-all COLLECTION=ipl

# scout graph + ratings
make docker-scout-up
make docker-scout-bootstrap
make docker-scout-populate COLLECTION=ipl
make docker-scout-rate COLLECTION=ipl

# scout queries
make docker-style-twin NAME="MS Dhoni"
uv run python scripts/scout_graph.py find-replacement "JJ Bumrah" \\
    --role bowler --max-balls-bowled 2000 --min-last-match 2023-01-01 -k 10

# auction
uv run python scripts/auction_advisor.py "JJ Bumrah" --budget 8 --role bowler -n 5
uv run python scripts/train_auction_grpo.py --pool real --epochs 8000 \\
    --group-size 16 --diverse-franchises

# rule QA
make docker-query Q="what is the impact player rule in IPL" FORMATS=ipl

# off-VM persistence (once R2 keys are provisioned)
make backup WHAT=all
```

Full runbook in `docs/RUNNING.md`. Deferred catalogue in
`docs/DEFERRED.md`. Architecture in `docs/ARCHITECTURE.md`.
"""
)
