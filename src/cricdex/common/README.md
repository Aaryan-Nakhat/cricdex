# common

Shared utilities, imported across every surface:

- `db.py` — DuckDB connection.
- `llm.py` — LLM client.
- `filters.py` — the player-row FilterBar (Python port of `site/src/lib/filters.ts`):
  `Filters`, the `*_OPTS` option lists, `apply_filters`, plus the windowed-leaderboard
  (`load_leaderboard`) and graph-cohort (`load_cohorts`) loaders. Parity-locked to the
  TS by `test_scripts/test_filters_parity.py`.
- `metrics.py` — the canonical 10-metric catalog (`METRICS` / `METRIC_BY_SLUG`,
  mirror of `site/src/lib/metrics.ts`). Single source for the Streamlit + TUI
  leaderboards and the `cricdex leaderboard` CLI.
- `spark.py` — the Unicode `sparkline()` shared by the CLI/TUI and Streamlit.

Only `common/` may be imported by every other module. Modules must not import each other directly — communicate via the shared data layer.
