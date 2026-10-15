# profiles

Per-player profile assembler.

- `builder.py` — `build(name, collection)` returns one dict per player: People
  Register cross-IDs, Wikidata enrichment (DOB / photo / socials), the LLM
  taxonomy, career totals from DuckDB, every computed metric row, the Bayesian
  skills and the top style twins. Used by the CLI `cricdex profile` and the REST
  API (`/v1/players/{name}`); needs the local DuckDB + `data/metrics/`.
- `identity.py` — fuzzy name resolution (`resolve_name`, rapidfuzz) plus the
  People Register name variations, so "Jasprit Bumrah" finds "JJ Bumrah".

The web, Streamlit and TUI Player Profile pages read the exported
`profiles/<cid>.json` that `scripts/export_site.py` cooks instead.
