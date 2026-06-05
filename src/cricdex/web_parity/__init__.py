"""Single-source parity layer for the Scout & Auction rooms.

The static web app (React/TS) computes the Auction simulation and the
3-tier Scout look-alikes in the browser. The CLI / Textual TUI / Streamlit
are Python. To keep every surface showing *exactly* the same thing from the
same inputs, this package:

1. reads the **same exported JSON** the web reads
   (`site/public/data/<collection>/{auction_pool,retentions,scout_index}.json`,
   cooked by `scripts/export_site.py`), and
2. re-implements the **same algorithms** as `site/src/lib/auction.ts` and
   `site/src/pages/Scout.tsx` — same constants, same formulas, and a
   bit-exact LCG RNG so the Monte-Carlo matches the browser trial-for-trial.

A parity test (`test_scripts/test_web_parity.py`) runs the TS implementation
under Node and asserts the Python output is identical, so the two can't drift.

This deliberately supersedes the older Neo4j-graph scout and MILP auction on
the desktop surfaces; those remain importable for advanced/offline use but
are no longer the default user path.
"""

from cricdex.web_parity.auction import (
    ARCHETYPES,
    IPL_TEAMS_DEFAULT,
    build_pool,
    default_retentions,
    simulate_auction,
)
from cricdex.web_parity.best_xi import best_xi
from cricdex.web_parity.loader import (
    load_auction_pool,
    load_retentions,
    load_scout_index,
)
from cricdex.web_parity.pricing import TIER_PENALTY, est_value
from cricdex.web_parity.scout import gem_threshold, is_gem, replacement_by_need, similar_to
from cricdex.web_parity.squad_balance import DEFAULT_ROLE_MINS, analyze_squad

__all__ = [
    "ARCHETYPES",
    "DEFAULT_ROLE_MINS",
    "IPL_TEAMS_DEFAULT",
    "TIER_PENALTY",
    "analyze_squad",
    "best_xi",
    "build_pool",
    "default_retentions",
    "est_value",
    "gem_threshold",
    "is_gem",
    "load_auction_pool",
    "load_retentions",
    "load_scout_index",
    "replacement_by_need",
    "similar_to",
    "simulate_auction",
]
