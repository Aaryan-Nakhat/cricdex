"""CricDex Streamlit home — sidebar nav routes to per-feature pages.

The actual feature pages live under `src/cricdex/dashboard/pages/`; Streamlit
auto-discovers them and renders the navigation in the sidebar. Naming
convention: `<order>_<Title>.py` (numeric prefix orders them).
"""

from __future__ import annotations

import streamlit as st

st.set_page_config(page_title="CricDex", page_icon="🏏", layout="wide")
st.title("🏏 CricDex")
st.caption("Open cricket intelligence — leaderboards, rule Q&A, scout, records.")

st.markdown(
    """
### What this is

CricDex is an open platform for cricket analytics — every metric, rule
answer, and scout rating is derived from public sources (Cricsheet
ball-by-ball, MCC/ICC/league rulebooks, Wikidata) and shipped with
explicit citations. No black-box scorecards.

### Where to go from here

- **Leaderboards** — six novel metric rankings (Pressure Runs,
  Recoverability, Counter-Attack, Boundary Dependency, Intent Curve,
  Sticky Dot Pressure) across whichever Cricsheet collections you have
  ingested.
- **Rules Chat** — ask a natural-language cricket question (e.g.
  *"what is the impact player rule in IPL?"* / *"can a batter be
  timed out in The Hundred?"*). Every claim is cited to the underlying
  clause.

### Useful CLI commands

```text
make docker-ingest-cricsheet COLLECTION=ipl
make docker-ingest-people
make docker-metrics-all COLLECTION=ipl
make docker-records-all COLLECTION=ipl
make docker-scout-up && make docker-scout-bootstrap && make docker-scout-populate
make docker-scout-rate COLLECTION=ipl
make docker-style-twin NAME="MS Dhoni"
```

Full runbook lives in `docs/RUNNING.md`.
"""
)
