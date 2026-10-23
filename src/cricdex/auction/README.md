# auction

The auction is a **real-rules IPL auction Monte-Carlo** — and its canonical
implementation lives in [`cricdex.web_parity`](../web_parity/) (one engine
shared by the web app + CLI `cricdex auction room` + TUI + Streamlit, locked to
the web by `test_scripts/test_web_parity.py`).

This package only holds:

- `real_pool.py` — the real IPL franchise list (`IPL_TEAMS`) the desktop
  auction reads. Every franchise bids by the same fitted demand model
  (`web_parity.auction.DEMAND`); the hand-set personalities were removed on
  2026-10-23.

The earlier MILP squad solver, Monte-Carlo price-band simulator, Gym/GRPO RL
self-play, and graph-based war-room advisor have been removed (see
`docs/CHANGELOG.md`); the live auction is the web-parity Monte-Carlo.
How it works, in plain English: [`docs/METHODOLOGY.md` §6–7](../../../docs/METHODOLOGY.md#7-the-auction-room);
step by step: [`docs/AUCTION_MATH.md`](../../../docs/AUCTION_MATH.md).
