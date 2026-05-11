# rules

Natural-language Q&A over cricket rulebooks.

## Sources

MCC Laws + ICC PC (Test/ODI/T20I/Women/U19/WTC) + IPL + The Hundred + BBL + SA20 + ILT20 + MLC + CPL + LPL + WPL + BCCI Domestic + Spirit of Cricket + Code of Conduct + Anti-Corruption.

## Pipeline

1. `ingest.py` — download versioned PDFs (manifest of URL + edition + effective_date).
2. `parse.py` — Marker → Markdown → clause-hierarchy chunker (preserve Law/Clause numbering).
3. `retrieval.py` — Jina dense + BM25 + RRF fusion + Jina rerank.
4. `qa.py` — Gemini Flash with citation discipline (cite source-id + clause).

## Modes

- Default Q&A
- Format compare (side-by-side table)
- Timeline (when rule changed)
- Scenario walk-through
- Vernacular glossary ("Mankad", "doosra")
- Multilingual (translate via Gemini)

## Coverage + update flow

- See [SOURCES.md](./SOURCES.md) for the current state of every rulebook source (verified ✅, blocked 🔒, not yet released ⏳, or adopted-from-ICC ↪️).
- See [docs/UPDATING_RULES.md](../../../docs/UPDATING_RULES.md) for how rule changes flow into the app — versioning model, manual update flow today, planned cron + diff PR automation, and bulletin/addendum handling.
