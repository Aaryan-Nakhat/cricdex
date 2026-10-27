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
- `playing_time.py` — who plays and what he adds a match (METHODOLOGY §6c): expected balls, P(plays), and the
  replacement levels, since 2026-10-26 curves in usual batting position and balls bowled (`curve_at`,
  `fit_curve`; the slot-group form is still read). Fitted by `scripts/playing_time_fit.py` into
  `config/playing_time_model.json`.

## Subpackages

- `ingest/` — source-specific loaders.
  - `cricsheet.py` — ball-by-ball.
  - `people_register.py` — Cricsheet cross-ID register + name variations — see [`docs/IDENTITY.md`](../../../docs/IDENTITY.md).
  - `wikidata.py` — DOB / photo / socials enrichment via the Wikidata entity API.
- `identity/` — the player master (`master.py`, `sources.py`; docs/IDENTITY.md): names, roles, country, squads and dates of birth (overrides → Wikipedia infobox → Wikidata at day precision, since 2026-10-26).
- `ratings/` — dismissal-aware Bayesian hierarchical rating with opponent bridging via NumPyro / JAX (ADVI default, NUTS available); `head_to_head.py` for P(A>B); `drift.py`, since 2026-10-27, moves a career rating to his level in the coming season (the fitted aging curve, METHODOLOGY §4b), which the contribution per match and everything after it read; `shrink.py` then calibrates it toward its role's mean (§4c).
- `search/` — `style_twin.py`, the cosine style-twin k-NN (on the Player Profile).
