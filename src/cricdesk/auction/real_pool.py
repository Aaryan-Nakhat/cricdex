"""The real IPL franchises the desktop Auction (TUI) lists.

The canonical, web-identical auction Monte-Carlo lives in `cricdesk.web_parity`
(shared by the web app + CLI + TUI + Streamlit, parity-locked). Every franchise
bids by the same demand model fitted on real auctions (`web_parity.auction.DEMAND`,
`scripts/auction_demand_fit.py`): teams differ by their squads and purses, not by a
hand-assigned bidding personality (those were removed on 2026-10-23, audit item 7).
"""

from __future__ import annotations

from cricdesk.web_parity.auction import IPL_TEAMS_DEFAULT

# The ten franchise codes, in the simulator's order.
IPL_TEAMS: tuple[str, ...] = tuple(t["team"] for t in IPL_TEAMS_DEFAULT)
