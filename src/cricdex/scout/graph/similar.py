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
