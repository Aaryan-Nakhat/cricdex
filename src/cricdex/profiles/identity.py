"""Fuzzy player-name resolution.

When a user types "Bumrah" / "Boomrah" / "Jassi" the rest of CricDex
needs the exact Cricsheet `unique_name` (e.g. "JJ Bumrah") because
every join keys off it. `resolve_name(query, collection)` returns
either an exact match or a ranked suggestion list backed by
rapidfuzz token-set ratio.

Used by:
- Streamlit profile / compare / scout / player-twins pages — show a
  "did you mean?" confirmation when the typed name doesn't match.
- CLI `cricdex profile / compare / scout` — exit 1 with the top-3
  suggestions printed when there's no exact match.

`rapidfuzz` is already a project dependency (people-register
fuzzy matching) so no new wheels.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import duckdb

from cricdex.config import DATA_DIR

DEFAULT_DB_PATH = DATA_DIR / "cricsheet" / "cricsheet.duckdb"


@dataclass
class NameMatch:
    name: str
    score: int  # 0-100; 100 = exact

    def __str__(self) -> str:  # for CLI rendering
        return f"{self.name}  ({self.score}%)"


def _player_universe(
    collection: str,
    db_path: Path | str = DEFAULT_DB_PATH,
) -> list[str]:
    safe = collection.replace("-", "_")
    if not Path(db_path).exists():
        return []
    with duckdb.connect(str(db_path), read_only=True) as con:
        tables = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
        if f"balls_{safe}" not in tables:
            return []
        rows = con.execute(
            f"""
            SELECT DISTINCT name FROM (
                SELECT batter AS name FROM balls_{safe} WHERE batter IS NOT NULL
                UNION
                SELECT bowler AS name FROM balls_{safe} WHERE bowler IS NOT NULL
            )
            """
        ).fetchall()
    return [r[0] for r in rows]


def _alias_map(collection: str, db_path: Path | str = DEFAULT_DB_PATH) -> dict[str, str]:
    """Cricsheet People Register name variations → the canonical Cricsheet name,
    restricted to players who actually appear in this collection.

    Lets aliases / full names ("Jasprit Bumrah", "J Bumrah", "J B") resolve to
    the scorecard name the ball-by-ball data keys off ("JJ Bumrah"). The
    Register ships 8.8k such variations; without this, search only matched the
    terse scorecard spellings.
    """
    universe = set(_player_universe(collection, db_path=db_path))
    if not universe or not Path(db_path).exists():
        return {}
    universe_lower = {n.lower() for n in universe}
    with duckdb.connect(str(db_path), read_only=True) as con:
        tables = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
        if "people" not in tables or "people_names" not in tables:
            return {}
        rows = con.execute(
            "SELECT pn.name AS alias, p.name AS canonical "
            "FROM people_names pn JOIN people p ON pn.identifier = p.identifier "
            "WHERE pn.name IS NOT NULL AND p.name IS NOT NULL"
        ).fetchall()
    out: dict[str, str] = {}
    for alias, canonical in rows:
        # Only keep aliases whose canonical plays in this collection, and don't
        # let an alias shadow a real scorecard name.
        al = alias.lower()
        if canonical in universe and al not in universe_lower:
            out.setdefault(al, canonical)
    return out


def resolve_name(
    query: str,
    collection: str = "ipl",
    db_path: Path | str = DEFAULT_DB_PATH,
    top_k: int = 3,
    score_cutoff: int = 60,
) -> tuple[str | None, list[NameMatch]]:
    """Resolve a free-text player query against the collection's name
    universe.

    Returns:
        (exact_match, suggestions)
        - `exact_match` — the unique_name if the query matches case-
          insensitively exactly OR scores >= 95; otherwise `None`.
        - `suggestions` — top-`top_k` ranked fuzzy matches with score
          >= `score_cutoff`, sorted descending.
    """
    from rapidfuzz import fuzz, process

    if not query or not query.strip():
        return None, []

    universe = _player_universe(collection, db_path=db_path)
    if not universe:
        return None, []

    q_lower = query.strip().lower()
    # Exact scorecard-name match first.
    for name in universe:
        if name.lower() == q_lower:
            return name, [NameMatch(name=name, score=100)]

    # Exact Register-alias match next ("Jasprit Bumrah" → "JJ Bumrah").
    aliases = _alias_map(collection, db_path=db_path)
    if q_lower in aliases:
        return aliases[q_lower], [NameMatch(name=aliases[q_lower], score=100)]

    # Fuzzy over scorecard names AND aliases; alias hits map back to canonical.
    choices = list(universe) + list(aliases.keys())
    raw = process.extract(
        query,
        choices,
        scorer=fuzz.WRatio,
        limit=top_k * 3,
        score_cutoff=score_cutoff,
    )
    suggestions: list[NameMatch] = []
    seen: set[str] = set()
    for match, score, _ in raw:
        canonical = aliases.get(match.lower(), match)  # alias key → canonical
        if canonical in seen:
            continue
        seen.add(canonical)
        suggestions.append(NameMatch(name=canonical, score=int(round(score))))
        if len(suggestions) >= top_k:
            break
    # Treat very-high scores (>=95) as effectively exact — saves the
    # user one confirmation click on the "MS Dhoni" / "M S Dhoni" case.
    if suggestions and suggestions[0].score >= 95:
        return suggestions[0].name, suggestions
    return None, suggestions
