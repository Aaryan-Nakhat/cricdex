# scout

Main product. Player graph + opposition-bridged ratings spanning pro → semi-pro → grassroots.

## Subpackages

- `ingest/` — source-specific scrapers (Cricsheet, Cricinfo, Cricbuzz, BCCI Domestic, CricHeroes).
- `identity/` — entity resolution across sources (name normalization, fuzzy + photo CLIP).
- `graph/` — Neo4j schema + writer (Player, Match, FACED, BOWLED_TO, TWIN_OF, etc).
- `ratings/` — Bayesian hierarchical rating with opponent bridging.
- `search/` — filter DSL + style-twin k-NN.
