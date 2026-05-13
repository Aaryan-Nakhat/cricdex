"""Graph-traversal player similarity queries on the scout Neo4j graph.

Complements the cosine-over-feature-vector style-twin search in
`cricdex.scout.search` with a relational signal — "players who faced
the same bowlers" / "players who were teammates of the same teammates".

Why
---
Cosine style-twins answer "this player's profile looks like X". The
graph traversal answers "this player operated in the same competitive
neighbourhood as X". For unknown / thin-data players the second signal
shrinks variance better than dense embeddings.

Queries
-------
- `co_faced_bowlers(name, k)` — top-k players sharing the most distinct
  bowlers in their FACED edge set. Best for batter similarity.
- `teammate_overlap(name, k)`  — top-k players sharing the most
  teammates (with multiplicity weighted by matches_together).

Both default to filtering by `unresolved = false` so unresolved
Cricsheet names don't pollute the result list.
"""

from __future__ import annotations

from cricdex.scout.graph.schema import driver


def co_faced_bowlers(unique_name: str, top_k: int = 10) -> list[dict]:
    drv = driver()
    try:
        with drv.session() as s:
            rows = s.run(
                """
                MATCH (p:Player {unique_name: $name})-[:FACED]->(b:Player)
                MATCH (q:Player)-[:FACED]->(b)
                WHERE q.cricsheet_id <> p.cricsheet_id
                  AND COALESCE(q.unresolved, false) = false
                WITH q, COUNT(DISTINCT b) AS shared_bowlers
                ORDER BY shared_bowlers DESC
                LIMIT $k
                RETURN q.unique_name AS name,
                       q.cricsheet_id AS cricsheet_id,
                       shared_bowlers
                """,
                name=unique_name,
                k=top_k,
            ).data()
        return rows
    finally:
        drv.close()


def teammate_overlap(unique_name: str, top_k: int = 10) -> list[dict]:
    drv = driver()
    try:
        with drv.session() as s:
            rows = s.run(
                """
                MATCH (p:Player {unique_name: $name})-[:TEAMMATE_OF]-(t:Player)
                MATCH (q:Player)-[r2:TEAMMATE_OF]-(t)
                WHERE q.cricsheet_id <> p.cricsheet_id
                  AND COALESCE(q.unresolved, false) = false
                WITH q, COUNT(DISTINCT t) AS shared_teammates,
                     SUM(r2.matches_together) AS weight
                ORDER BY shared_teammates DESC, weight DESC
                LIMIT $k
                RETURN q.unique_name AS name,
                       q.cricsheet_id AS cricsheet_id,
                       shared_teammates,
                       weight
                """,
                name=unique_name,
                k=top_k,
            ).data()
        return rows
    finally:
        drv.close()


def find_replacement(
    unique_name: str,
    top_k: int = 10,
    max_balls_bowled: int | None = None,
    max_balls_faced: int | None = None,
    role: str | None = None,
    min_last_match_date: str | None = None,
) -> list[dict]:
    """Find a 'next X' candidate.

    For a bowler target: walks (q)-[:FACED]->(batter)<-[:FACED]-(p)
    and ranks q by distinct shared batters. For a batter target:
    walks (p)-[:FACED]->(bowler)<-[:FACED]-(q) and ranks by shared
    bowlers. The function reads `role` off the target Player node to
    pick the right direction automatically.

    Filters tighten the cohort to "replacement-shape" candidates:

    - `role='bowler'` requires the candidate to be heuristic-classified
      as a bowler (balls_bowled >= balls_faced AND not all_rounder).
    - `max_balls_bowled` / `max_balls_faced` cap data depth so proven
      veterans are filtered out — proxy for "younger / less established".
    - `min_last_match_date` requires the candidate to have played
      after a cutoff (e.g. '2024-01-01') — proxy for "still active".
    """
    drv = driver()
    try:
        with drv.session() as s:
            target = s.run(
                "MATCH (p:Player {unique_name: $name}) RETURN p.role AS role",
                name=unique_name,
            ).single()
            if target is None:
                return []
            target_role = target["role"]

            if target_role == "bowler":
                base = """
                MATCH (p:Player {unique_name: $name})<-[:FACED]-(batter:Player)
                MATCH (batter)-[:FACED]->(q:Player)
                """
                count_alias = "shared_batters"
                count_expr = "COUNT(DISTINCT batter)"
            else:
                base = """
                MATCH (p:Player {unique_name: $name})-[:FACED]->(opp:Player)
                MATCH (q:Player)-[:FACED]->(opp)
                """
                count_alias = "shared_bowlers"
                count_expr = "COUNT(DISTINCT opp)"

            filters = [
                "q.cricsheet_id <> p.cricsheet_id",
                "COALESCE(q.unresolved, false) = false",
            ]
            if role:
                filters.append("q.role = $role")
            if max_balls_bowled is not None:
                filters.append("q.balls_bowled <= $max_balls_bowled")
            if max_balls_faced is not None:
                filters.append("q.balls_faced <= $max_balls_faced")
            if min_last_match_date:
                filters.append("q.last_match_date >= $min_last_match_date")
            where = " AND ".join(filters)

            cypher = f"""
            {base}
            WHERE {where}
            WITH q, {count_expr} AS {count_alias}
            ORDER BY {count_alias} DESC
            LIMIT $k
            RETURN q.unique_name AS name,
                   q.cricsheet_id AS cricsheet_id,
                   q.role AS role,
                   q.balls_bowled AS balls_bowled,
                   q.balls_faced AS balls_faced,
                   q.last_match_date AS last_match_date,
                   {count_alias} AS shared
            """
            params: dict[str, object] = {"name": unique_name, "k": top_k}
            if role:
                params["role"] = role
            if max_balls_bowled is not None:
                params["max_balls_bowled"] = max_balls_bowled
            if max_balls_faced is not None:
                params["max_balls_faced"] = max_balls_faced
            if min_last_match_date:
                params["min_last_match_date"] = min_last_match_date
            return s.run(cypher, **params).data()
    finally:
        drv.close()
