# scout

Main product. Player graph + opposition-bridged ratings spanning pro → semi-pro → grassroots.

## Subpackages

- `ingest/` — source-specific loaders.
  - `cricsheet.py` — ball-by-ball (shipped, Phase 1).
  - `people_register.py` — Cricsheet cross-ID register (shipped, Phase 1) — see [`docs/IDENTITY.md`](../../../docs/IDENTITY.md).
  - Cricinfo, Cricbuzz, CricHeroes, BCCI Domestic scrapers — Phase 2.
- `identity/` — entity resolution across sources (Phase 2: name normalization, fuzzy + photo CLIP).
- `graph/` — Neo4j schema + writer (Player, Match, FACED, TEAMMATE_OF, PLAYED_IN, AT) + traversal helpers (`similar.co_faced_bowlers`, `similar.teammate_overlap`, `similar.find_replacement`). Player nodes also carry heuristic `role` + raw `balls_faced` / `balls_bowled` + `last_match_date`. Dashboard page **Player Twins** wraps the queries.
- `ratings/` — Bayesian hierarchical rating with opponent bridging via NumPyro / JAX (ADVI default, NUTS available).
- `search/` — filter DSL + style-twin k-NN.
