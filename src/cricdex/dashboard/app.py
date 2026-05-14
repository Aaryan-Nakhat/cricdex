"""CricDex Streamlit home — sidebar nav routes to per-feature pages.

Streamlit auto-discovers everything under `pages/`; this module is the
landing page that explains what CricDex is, what each page does, and
what the underlying data source is so a first-time viewer can navigate
without reading the codebase.
"""

from __future__ import annotations

import streamlit as st

st.set_page_config(page_title="CricDex", page_icon="🏏", layout="wide")
st.title("🏏 CricDex")
st.caption(
    "Open cricket intelligence — novel metrics, rule Q&A, scout graph, "
    "auction war-room. Two surfaces over one data dir."
)

st.markdown(
    """
### What CricDex is

A terminal-first open cricket-analytics platform. Every number you see
is derived from public sources — primarily **[Cricsheet](https://cricsheet.org/)
ball-by-ball JSON archives**, the **[Cricsheet People Register](https://cricsheet.org/register/people.csv)**
for cross-source identity, and **21 versioned rulebook PDFs** from MCC,
ICC, IPL, The Hundred, BBL/WBBL, SA20, Cricket Australia domestic, and
the ICC Codes of Conduct + Anti-Corruption.

This Streamlit dashboard is one of two surfaces — every page can also
be queried from the terminal via the `cricdex` CLI
(`uvx --from cricdex cricdex --help`). Both read `$CRICDEX_HOME/data/`
(default `~/.cricdex/data/`) so updates from `cricdex data ingest …`
show up here without restart.

---

### Pages — what each does, what data it uses

| Page | What it answers | Source |
|---|---|---|
| **Leaderboards** | Top players by each novel metric — see definitions below | Cricsheet → metric JSONs |
| **Rules Chat** | "what is the impact player rule?" with cited clauses | 21 rulebook PDFs + Gemini |
| **Records** | Highest score, fastest fifty, most sixes, on-this-day | Cricsheet ball-by-ball |
| **Match Reports** | LLM-written 350-500 word reports grounded in facts | Cricsheet + Gemini |
| **Compare** | 2-5 players side-by-side, radar + tooltipped table | Cricsheet career totals + novel metrics + Bayes scout-rating |
| **Venues** | Per-venue innings totals, chase vs set, phase-by-phase RR | Cricsheet ball-by-ball |
| **DRS Practice** | 20 hand-curated umpire scenarios with MCC/ICC citations | Hand-curated + rulebook corpus |
| **Auction** | MILP squad optimiser + war-room substitute advisor | Real-IPL pool (Bayes-driven projected_value) + scout graph |
| **Player Profile** | Everything CricDex knows about one player | All of the above |
| **Translate Commentary** | English → Hindi / Tamil / Bengali / 5 more (needs Gemini key) | Gemini |
| **Auction Simulator** | Monte-Carlo price-band distribution + GRPO RL agent demo | Same as Auction page |
| **Player Twins** | "Next Bumrah" / Dhoni's CSK cohort — graph traversal | Scout Neo4j (built from Cricsheet) |

---

### The metrics, in plain English

The Leaderboards page splits these across separate tabs; the Player
Profile page surfaces them per-player with the same definitions.

- **NGI (Net Game Impact)** — WPA-style flagship. For every ball we
  estimate the win-probability swing and credit it to the batter (+)
  and bowler (−). Career NGI = mean per-match contribution. One
  currency for offense + defense + clutch — a 30* in a tight chase
  outranks a 100 against a beaten side. The win-probability model
  is calibrated — when it says "70% win chance", the batting team
  actually wins ~70% of the time.
- **Pressure Runs** — strike rate on balls where the required run rate
  is ≥ 1.5× the venue median (chase only). Higher = harder to slow
  down when the team needs it.
- **Recoverability** — how efficiently a batter recovers strike rate
  after a slow patch. Higher = doesn't let one dot ball spiral.
- **Counter-Attack** — strike-rate inflation right after a wicket
  falls. Higher = aggressive after partnership-breaking dismissals.
- **Boundary Dependency** — share of runs from 4s + 6s. Lower = strong
  strike-rotator; higher = relies on boundaries.
- **Intent Curve** — per-over batter strike-rate curve. Tab shows the
  curve shape, not a single number.
- **Sticky Dot Pressure (bowler)** — wicket rate on the next ball
  after a 4+ consecutive dot streak in the same over. Higher = turns
  pressure into dismissals.
- **Phase Dilation (batter)** — average balls per dismissal vs the
  cohort. Anchor archetypes score high.
- **Setting Tax (batter)** — career SR minus first-20-balls SR.
  Higher = slower starter even after they're set.
- **Wicket Quality (bowler)** — mean Bayes batter-skill of dismissed
  batters per bowler. Picks up Kohli + Rohit + Buttler scores higher
  than tail-enders.

### CLI commands you'll touch

```bash
# inventory
cricdex data status

# ingest data — all skippable with --force to regenerate
cricdex data ingest cricsheet -c ipl            # ~600 MB ball-by-ball
cricdex data ingest rules                       # 21 PDFs + 11 k clauses
cricdex data ingest ratings -c ipl              # Bayes scout fit
cricdex data ingest metrics -c ipl              # every leaderboard JSON
cricdex data ingest graph -c ipl                # populate Neo4j

# the queries
cricdex leaderboard ngi -c ipl --top 25
cricdex profile "V Kohli"                       # fuzzy — "Kohli" also works
cricdex compare "V Kohli" "RG Sharma"
cricdex rules ask "impact player rule" --formats ipl
cricdex scout twins "MS Dhoni" --mode teammates
cricdex scout find-replacement "JJ Bumrah" --role bowler
cricdex auction recommend "JJ Bumrah" --budget 8 --role bowler
cricdex auction solve --pool real --purse 120

# the TUI
cricdex tui                                     # full Textual UI
```

### Available collections

`-c <collection>` accepts: `ipl`, `bbl`, `t20s_male`,
`indian_domestic_male` (SMAT-only — Ranji and Hazare TBD), and
`recently_played_30_male` (rolling 30-day window). NGI / Bayes are
fit per-collection so cross-collection comparisons stay honest.

Full reference: [`docs/CLI.md`](docs/CLI.md). Onboarding:
[`docs/FIRST_RUN.md`](docs/FIRST_RUN.md). Architecture:
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md). Pending work:
[`docs/TODO.md`](docs/TODO.md).
"""
)
