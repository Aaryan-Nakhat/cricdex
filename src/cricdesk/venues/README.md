# venues

Per-venue pitch + conditions archive, from the Cricsheet ball-by-ball in DuckDB
(`profile.py`). Five SQL functions:

- `list_venues` — every venue with at least N matches.
- `innings_totals` — average / median total and wickets per innings.
- `chase_vs_set_winrate` — chasing vs setting win rate.
- `phase_run_rates` — run rate by powerplay / middle / death.
- `dismissal_mix` — how wickets fall there.

Venue names are matched exactly (e.g. "Wankhede Stadium, Mumbai"). Used by the
CLI `cricdesk venues`, the REST API (`/v1/venues…`) and `scripts/export_site.py`,
which cooks `venues.json` for the web, Streamlit and TUI Venues pages.
