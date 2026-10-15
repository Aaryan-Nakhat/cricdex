# comparator

Career side-by-side comparator.

`compare.compare(players, collection)` returns one row per player: career
totals from DuckDB, the context metrics from `data/metrics/` and the Bayesian
skills. Used by the CLI `cricdex compare` and the REST API (`POST /v1/compare`).
The web, Streamlit and TUI Compare pages (2–4 players, radar + table) work from
the exported snapshot instead.
