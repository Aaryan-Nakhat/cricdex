# scout

Main product. Player graph + opposition-bridged ratings spanning pro → semi-pro → grassroots.

## Subpackages

- `ingest/` — source-specific loaders.
  - `cricsheet.py` — ball-by-ball (shipped, Phase 1).
  - `people_register.py` — Cricsheet cross-ID register (shipped, Phase 1) — see [`docs/IDENTITY.md`](../../../docs/IDENTITY.md).
  - Cricinfo, Cricbuzz, CricHeroes, BCCI Domestic scrapers — Phase 2.
- `identity/` — entity resolution across sources (Phase 2: name normalization, fuzzy + photo CLIP).
- `graph/` — Neo4j schema + writer (Player, Match, FACED, BOWLED_TO, TWIN_OF, etc.) — Phase 2.
- `ratings/` — Bayesian hierarchical rating with opponent bridging — Phase 2.
- `search/` — filter DSL + style-twin k-NN — Phase 2.
