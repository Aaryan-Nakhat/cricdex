# scout

Opposition-adjusted Bayesian ratings + cross-competition look-alikes. Powers
the Scout look-alike finder (one implementation in `cricdex.web_parity`, shared
by web + CLI + TUI + Streamlit) and the Head-to-head P(A>B). File-driven —
DuckDB + exported JSON; no graph database.

## Subpackages

- `ingest/` — source-specific loaders.
  - `cricsheet.py` — ball-by-ball.
  - `people_register.py` — Cricsheet cross-ID register + name variations — see [`docs/IDENTITY.md`](../../../docs/IDENTITY.md).
  - `wikidata.py` — DOB / photo / socials enrichment for active players.
- `identity/` — entity resolution helpers.
- `ratings/` — dismissal-aware Bayesian hierarchical rating with opponent bridging via NumPyro / JAX (ADVI default, NUTS available); `head_to_head.py` for P(A>B).
- `search/` — filter DSL + style-twin k-NN (on the Player Profile).
