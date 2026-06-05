# scout

Opposition-adjusted Bayesian ratings + cross-competition look-alikes. Powers
the Scout look-alike finder (one implementation in `cricdex.web_parity`, shared
by web + CLI + TUI + Streamlit) and the Head-to-head P(A>B). File-driven —
DuckDB + exported JSON; no graph database.

## Modules

- `cohort.py` — the **graph cohort** ("who faced the same bowlers / bowled to the
  same batters"), computed straight from the ball-by-ball in DuckDB — a pure-SQL
  replacement for the removed Neo4j FACED traversal (axis chosen by ball volume:
  batter → `shared_bowlers`, bowler → `shared_batters`). `export_site.py` writes it
  to `cohorts/<cid>.json`, rendered on the Player Profile.

## Subpackages

- `ingest/` — source-specific loaders.
  - `cricsheet.py` — ball-by-ball.
  - `people_register.py` — Cricsheet cross-ID register + name variations — see [`docs/IDENTITY.md`](../../../docs/IDENTITY.md).
  - `wikidata.py` — DOB / photo / socials enrichment for active players.
- `identity/` — entity resolution helpers.
- `ratings/` — dismissal-aware Bayesian hierarchical rating with opponent bridging via NumPyro / JAX (ADVI default, NUTS available); `head_to_head.py` for P(A>B).
- `search/` — filter DSL + style-twin k-NN (on the Player Profile).
