"""Auto-generated match reports.

Given a Cricsheet `match_id`, assemble a compact JSON of facts
(teams, venue, result, per-innings totals, top batting + bowling,
biggest over, key dismissals), hand it to the temp Gemini proxy with
a strict citation-style prompt, and write the rendered Markdown
report under `data/reports/<collection>/<match_id>.md`.
"""

from __future__ import annotations

import json
from pathlib import Path

import duckdb

from cricdex.common import llm
from cricdex.config import DATA_DIR

DEFAULT_DB_PATH = DATA_DIR / "cricsheet" / "cricsheet.duckdb"

SYSTEM_PROMPT = """You are a cricket match-report writer.

Rules:
- Use ONLY the facts in the structured payload supplied. Do not invent
  any names, numbers, venues, or events not present in the facts.
- 350-500 words, Markdown with a `## Summary` and a `## Highlights` section.
- Stay neutral; no marketing language; no fan-style hyperbole.
- Quote scores and bowling figures verbatim from the payload (e.g.
  "62 (37b)" or "3 for 22 in 4 overs").
- Mention the venue and result clearly in the opening sentence.
- If a value in the payload is null, do not pretend it exists.
""".strip()


def _match_facts(con: duckdb.DuckDBPyConnection, collection: str, match_id: str) -> dict:
    safe = collection.replace("-", "_")
    meta = con.execute(
        f"""
        SELECT *
        FROM matches_{safe}
        WHERE match_id = ?
        """,
        [match_id],
    ).fetchone()
    if not meta:
        raise KeyError(f"match_id {match_id!r} not in matches_{safe}")
    cols = [d[0] for d in con.description]
    meta_dict = dict(zip(cols, meta, strict=True))

    innings = con.execute(
        f"""
        SELECT
            innings_idx, batting_team, bowling_team,
            SUM(runs_total) AS runs,
            COUNT(*) FILTER (WHERE wicket_kind IS NOT NULL) AS wickets,
            MAX(over) + 1 AS overs_used
        FROM balls_{safe}
        WHERE match_id = ?
        GROUP BY 1, 2, 3
        ORDER BY 1
        """,
        [match_id],
    ).fetchall()

    top_batters = con.execute(
        f"""
        SELECT batter, batting_team,
               SUM(runs_batter) AS runs,
               COUNT(*) FILTER (WHERE COALESCE(extras_type,'') NOT IN ('wides')) AS balls,
               SUM(CASE WHEN runs_batter = 4 THEN 1 ELSE 0 END) AS fours,
               SUM(CASE WHEN runs_batter = 6 THEN 1 ELSE 0 END) AS sixes
        FROM balls_{safe}
        WHERE match_id = ? AND batter IS NOT NULL
        GROUP BY batter, batting_team
        ORDER BY runs DESC, balls ASC
        LIMIT 6
        """,
        [match_id],
    ).fetchall()

    top_bowlers = con.execute(
        f"""
        SELECT bowler, bowling_team,
               SUM(CASE WHEN wicket_kind IS NOT NULL
                     AND wicket_kind NOT IN ('run out','retired hurt','retired out','obstructing the field')
                    THEN 1 ELSE 0 END) AS wickets,
               SUM(runs_batter + COALESCE(runs_extras, 0)) AS runs_conceded,
               COUNT(*) FILTER (WHERE COALESCE(extras_type,'') NOT IN ('wides','noballs')) AS legal_balls
        FROM balls_{safe}
        WHERE match_id = ? AND bowler IS NOT NULL
        GROUP BY bowler, bowling_team
        HAVING legal_balls >= 12
        ORDER BY wickets DESC, runs_conceded ASC
        LIMIT 6
        """,
        [match_id],
    ).fetchall()

    biggest_over = con.execute(
        f"""
        SELECT batting_team, bowling_team, bowler, over,
               SUM(runs_batter + COALESCE(runs_extras, 0)) AS runs_in_over
        FROM balls_{safe}
        WHERE match_id = ?
        GROUP BY 1, 2, 3, 4
        ORDER BY runs_in_over DESC
        LIMIT 1
        """,
        [match_id],
    ).fetchone()

    return {
        "match_id": match_id,
        "collection": collection,
        "meta": {
            k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in meta_dict.items()
        },
        "innings": [
            {
                "innings_idx": r[0],
                "batting_team": r[1],
                "bowling_team": r[2],
                "runs": int(r[3] or 0),
                "wickets": int(r[4] or 0),
                "overs_used": int(r[5] or 0),
            }
            for r in innings
        ],
        "top_batters": [
            {
                "batter": r[0],
                "team": r[1],
                "runs": int(r[2] or 0),
                "balls": int(r[3] or 0),
                "fours": int(r[4] or 0),
                "sixes": int(r[5] or 0),
            }
            for r in top_batters
        ],
        "top_bowlers": [
            {
                "bowler": r[0],
                "team": r[1],
                "wickets": int(r[2] or 0),
                "runs_conceded": int(r[3] or 0),
                "legal_balls": int(r[4] or 0),
            }
            for r in top_bowlers
        ],
        "biggest_over": (
            {
                "batting_team": biggest_over[0],
                "bowling_team": biggest_over[1],
                "bowler": biggest_over[2],
                "over": int(biggest_over[3] or 0) + 1,
                "runs_in_over": int(biggest_over[4] or 0),
            }
            if biggest_over
            else None
        ),
    }


def generate(
    match_id: str,
    collection: str = "ipl",
    db_path: Path | str = DEFAULT_DB_PATH,
    out_dir: Path | None = None,
    model: str = llm.DEFAULT_TEXT_MODEL,
) -> Path:
    out_dir = out_dir or (DATA_DIR / "reports" / collection)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{match_id}.md"

    with duckdb.connect(str(db_path), read_only=True) as con:
        facts = _match_facts(con, collection, match_id)

    body = (
        "FACTS (JSON):\n"
        f"```json\n{json.dumps(facts, indent=2, default=str)}\n```\n\n"
        "Write the match report following the system rules above."
    )
    text = llm.generate(SYSTEM_PROMPT, body, model=model, temperature=0.2)
    out_path.write_text(text)
    return out_path
