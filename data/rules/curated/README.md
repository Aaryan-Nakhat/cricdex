# Curated rule clauses

Hand-written supplementary clauses for rules whose authoritative version
does NOT have a publicly hosted PDF. The pipeline merges these with the
auto-parsed PDF JSONL during `scripts/embed_rules.py embed`, so they end
up in the same Qdrant collection as the rest of the corpus and answer
queries with proper citations.

## When to add a file here

Add a JSONL when:

1. The rule is consequential (i.e. fans / coaches / analysts ask about
   it frequently).
2. The authoritative source (BCCI / ICC / league) does not host a
   downloadable PDF, OR the rule lives in a separate non-public
   document (e.g. the IPL Player Regulations — published to franchises
   but not to the public).
3. There is a clearly authoritative public announcement / explainer
   you can cite (publisher's own news article, ICC press release,
   reputable cricket journalism such as ESPNcricinfo, Cricbuzz, Wisden).

## Schema

One JSON object per line, matching the parser output schema:

```json
{
  "source_id":      "ipl_impact_player_2025_27",
  "edition":        "2025-2027 cycle",
  "page":           0,
  "law_number":     "IP.1",
  "parent_chain":   ["IP.1"],
  "title":          "Introduction — Impact Player Regulation continues",
  "text":           "<the clause body, ideally close to the publisher's wording>"
}
```

- `source_id` must also be registered in
  `src/cricdex/rules/manifest.py` with `tier="supplementary"` and full
  provenance notes.
- `law_number` should use a custom namespace (e.g. `IP.1`, `IP.2` …)
  separate from the auto-parsed clause numbering, so they never collide.
- Keep the wording faithful to the source. The point is to be
  citation-grade; loose paraphrasing defeats the purpose.

## Workflow

1. Identify the rule and the authoritative source(s).
2. Add the JSONL file under this directory.
3. Add a `RuleSource` entry in `manifest.py` (`tier="supplementary"`,
   `verified=True` if the source is authoritative, `url` pointing to
   the public announcement, `notes` explaining why it is curated).
4. Update `FORMAT_TO_SOURCE_IDS` in `rules/qa.py` so the relevant
   format filter (e.g. `"ipl"`) includes the new `source_id`.
5. Add the new tier badge to `SOURCES.md`.
6. Re-embed (`make docker-embed-rules` or `uv run python
   scripts/embed_rules.py embed`).
7. Test with a CLI query.

## When BCCI / publisher releases a public PDF

Promote the source to the main manifest as a normal `tier=league_*`
entry, point `url` at the PDF, drop the curated JSONL, and re-embed.
The curated row stays in git history for provenance, but the live
corpus moves to the canonical document.
