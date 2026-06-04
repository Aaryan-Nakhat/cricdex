# auction

The auction is a **real-rules IPL auction Monte-Carlo** — and its canonical
implementation lives in [`cricdex.web_parity`](../web_parity/) (one engine
shared by the web app + CLI `cricdex auction room` + TUI + Streamlit, locked to
the web by `test_scripts/test_web_parity.py`).

This package only holds:

- `real_pool.py` — the real IPL franchise list + bidding-personality defaults
  (`IPL_TEAMS_DEFAULT`, `PERSONALITY_IDS`, `load_team_overrides`) that the
  desktop auction reads, plus a Bayes-priced pool builder kept for offline
  experiments.

The earlier MILP squad solver, Monte-Carlo price-band simulator, Gym/GRPO RL
self-play, and graph-based war-room advisor have been removed (see
`docs/CHANGELOG.md`); the live auction is the web-parity Monte-Carlo.
