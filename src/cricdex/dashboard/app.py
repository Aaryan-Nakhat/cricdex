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
    "Open cricket intelligence — novel metrics, cross-competition scouting, and a "
    "real-rules IPL auction. The desktop mirror of the web app, over one data dir."
)

st.markdown(
    """
### What CricDex is

An open cricket-analytics platform built entirely from public
**[Cricsheet](https://cricsheet.org/) ball-by-ball data** + the
**[Cricsheet People Register](https://cricsheet.org/register/)** for
cross-source identity. No scraping, no live feed, no LLM guessing — a
Python pipeline computes everything offline.

These pages **mirror the React web app** ([live](https://aaryan-nakhat.github.io/cricdex/));
the Scout + Auction run the *same* logic as the site via `cricdex.web_parity`
(locked by a parity test). Every page is also a terminal command
(`cricdex --help`); both read `$CRICDEX_HOME/data/` (default
`~/.cricdex/data/`).

---

### Pages

| Page | What it answers | Source |
|---|---|---|
| **Leaderboards** | Top players by each of the 10 novel metrics | Cricsheet → metric JSONs |
| **Player Profile** | Everything CricDex knows about one player | all of the below |
| **Compare** | 2–5 players side-by-side, radar + table | career totals + metrics + Bayes |
| **Head-to-head** | P(A is better than B) from the Bayesian posteriors | scout ratings |
| **Scout** | Cross-competition look-alikes (IPL / SMAT / BBL / SA20 / CPL / Blast) + est. price, savings, gem flag, draft | exported scout index via `cricdex.web_parity` |
| **Auction** | Real-rules IPL auction Monte-Carlo (retain → bid), web-identical | exported pool via `cricdex.web_parity` |
| **Records** | Highest score, fastest fifty, most sixes, on-this-day | exported `records.json` |
| **Venues** | Per-venue totals, chase vs set, phase run-rates | exported `venues.json` |
| **Update Data** | Refresh a collection → re-export the JSON every page reads | local pipeline → exported JSON |

All read-only pages read the **exported JSON** (the same files the web app
fetches); **Update Data** is the one page that *writes* — it re-ingests +
re-exports so the rest stay in sync. Best of both worlds: edit once, read
everywhere.

---

### The 10 metrics, in plain English

The Leaderboards page splits these across tabs; the Player Profile page
surfaces them per-player with the same definitions.

- **NGI (Net Game Impact)** — WPA-style flagship. Per ball we estimate the
  win-probability swing and credit batter (+) / bowler (−); career NGI =
  mean per-match contribution. One currency for offense + defense + clutch.
- **Pressure Runs** — strike rate when the required rate is climbing in a
  chase. Higher = lifts when it's tight.
- **Dot-Ball Recovery** — runs in the six balls after a dot. Higher =
  doesn't let dots spiral.
- **Counter-Attack** — strike rate right after a partner is dismissed.
- **Boundary Dependency** — share of runs from 4s + 6s. Lower = rotates
  strike; higher = relies on the rope.
- **Intent Curve** — strike rate from ball one: ranks batters by **early SR**
  (balls 1–10) with the full innings curve as an inline sparkline.
- **Pressure Conversion (bowler)** — wicket rate on pressure balls (after a
  run of dots). Higher = finishes the squeeze.
- **Crease Longevity (batter)** — balls survived per dismissal vs the cohort.
- **Slow-Start Cost (batter)** — career SR minus setting (1st-innings) SR.
- **Wicket Quality (bowler)** — wickets weighted by the Bayes batting skill
  of the batter dismissed.

### CLI commands you'll touch

```bash
cricdex data status                              # inventory

# refresh data (add --force to regenerate)
cricdex data ingest cricsheet -c ipl             # ball-by-ball -> DuckDB
cricdex data ingest ratings   -c ipl             # Bayesian scout fit
cricdex data ingest metrics   -c ipl             # every leaderboard JSON

# the queries
cricdex leaderboard ngi -c ipl --top 25
cricdex profile "V Kohli"                        # fuzzy — "Kohli" works too
cricdex compare "V Kohli" "RG Sharma"
cricdex scout look-alikes "JJ Bumrah"            # 6-pool look-alikes
cricdex auction room --mode mega                 # real-rules auction sim

cricdex tui                                       # full Textual UI
```

### Available collections

`-c <collection>` accepts: `ipl`, `bbl`, `t20s_male`,
`indian_domestic_male` (SMAT), `recently_played_30_male`, `sa20`, `cpl`,
`blast`. Ratings / metrics are fit per-collection so cross-collection
comparisons stay honest.

Full reference: [`docs/CLI.md`](docs/CLI.md). Onboarding:
[`docs/FIRST_RUN.md`](docs/FIRST_RUN.md). Architecture:
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).
"""
)
