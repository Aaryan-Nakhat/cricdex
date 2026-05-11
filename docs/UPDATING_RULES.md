# Updating rules when they change

Cricket rule corpora rotate annually (ICC PCs every ~6 months, league PCs once a season, MCC Laws every few years, ad-hoc bulletins mid-season). The pipeline is designed to absorb new versions without losing the old ones.

## Versioning model

Each rule clause carries:

- `source_id` — stable identifier (e.g. `icc_pc_men_t20i_2025`)
- `edition` — human-readable label
- `effective_from` / `effective_to` — date range
- `clause_text` + `law_number` + `parent_chain`

When a publisher releases a new version, we **add a new entry** to the manifest rather than overwriting. Both versions coexist in the DB. Retrieval defaults to the version where today's date ∈ [effective_from, effective_to]. Historical queries (`as_of=2024-09-15`) are supported.

## Manual update flow (v1)

When ICC / BCCI / ECB / CSA publishes a new version:

1. **Find the new URL** — usually on the publisher's Playing Conditions index page.
2. **Add a new `RuleSource` entry** in `src/cricdex/rules/manifest.py` with:
   - new `id` suffixed by year (`icc_pc_men_test_2026`)
   - new `url`
   - new `effective_from`
   - `verified=True`
3. **Set `effective_to`** on the previous entry to one day before the new effective date.
4. **Re-run**:
   ```bash
   uv run python scripts/ingest_rules.py download
   uv run python scripts/ingest_rules.py parse-pdfs
   uv run python scripts/embed_rules.py            # (Phase 1 W3 — to be added)
   ```
5. Vector index is rebuilt with both old and new clauses tagged by `source_id`.
6. **Diff report** — script outputs a clause-level diff (new clauses, deleted clauses, edited clauses) for human review, posted to Discord and committed to `data/rules/diffs/<date>.md`.

## Automated update flow (v2 — planned)

GitHub Actions cron job, weekly:

1. **HEAD-poll each verified URL** — store and compare:
   - `Last-Modified` header
   - `ETag`
   - SHA-256 of the first 64 KB
2. **If any source changed**:
   - Re-download.
   - Re-parse → JSONL.
   - Compute clause-level diff vs previous version (rapidfuzz on `law_number` + cosine sim on embedded text).
   - Open a GitHub PR with: new manifest entry, fresh JSONL, diff summary.
3. Human reviews the diff, merges, triggers re-embed.

Detection edge cases:
- Some publishers overwrite the same URL → caught by content hash, not URL.
- Some publishers rotate the URL each season → caught by 404, falls back to homepage scrape.

## Automated change-detection across the web (v3 — far future)

Beyond the manifest:

- Watch the publisher's RSS / news feed (ICC publishes "Several changes made to ICC Playing Conditions" articles).
- Subscribe to MCC press releases.
- Cross-reference cricket-Twitter (via `pulse` module) for "new rule announced" mentions, surface to maintainer.

## How a question routed in `rules` picks the right version

```
user query → format-disambiguator → retrieve from corpus
                                       where source_id ∈ {applicable formats}
                                         and effective_from ≤ as_of
                                         and (effective_to IS NULL OR effective_to ≥ as_of)
                                    → rerank → LLM with citation discipline
```

If a user explicitly asks "before 2025", `as_of` is overridden.

If a user asks "what changed in the 2026 IPL PC vs 2025", we serve the precomputed diff document directly without LLM hallucination risk.

## Why this matters

Rules are the one corpus where the cost of being wrong is high (an umpire / coach / journalist citing CricDex must be confident the citation is current). Hence:

- Always cite `source_id` + `effective_from` in answers.
- Never silently overwrite a version.
- Run the diff report as a first-class artifact, not an afterthought.

## Bulletin / addendum handling

Mid-season ICC sometimes ships an Addendum (e.g. "Playing Conditions Addendums" PDF). These attach to existing PCs rather than replace them. Manifest entry tier: `addendum`, with `parent_source_id` pointing at the PC it amends. Retrieval applies the latest matching addendum on top of the parent PC, like a patch layer.

## Operational checklist

When you suspect a rule has changed:

1. Visit publisher's Rules & Regulations page.
2. Compare PDF effective-date vs the manifest entry's `effective_from`.
3. If newer → follow the manual update flow above.
4. Commit + push the manifest change; CI re-runs download + parse.
5. Once embed pipeline lands (Phase 1 W3), re-embed and push the new vector index version.
