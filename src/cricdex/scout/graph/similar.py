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
    """Auto-flip FACED-cohort similarity:

    - Target is a batter: returns OTHER BATTERS who faced the same
      bowlers (Kohli → RG Sharma, S Dhawan, MS Dhoni, …).
    - Target is a bowler: returns OTHER BOWLERS who bowled to the same
      batters (Bumrah → Bhuvneshwar Kumar, Boult, Narine, …).

    The earlier version always assumed batter — for Bumrah it walked
    out of his rare batting FACED edges and pulled batter cohort,
    which is nonsense for a "find similar bowler" query.
    """
    drv = driver()
    try:
        with drv.session() as s:
            target_row = s.run(
                "MATCH (p:Player {unique_name: $name}) "
                "RETURN p.balls_bowled AS bb, p.balls_faced AS bf, "
                "p.bowling_style AS bowling_style",
                name=unique_name,
            ).single()
            target_bb = (target_row or {}).get("bb") or 0
            target_bf = (target_row or {}).get("bf") or 0
            # Reliable bowler-vs-batter detection: actual ball volume
            # ratio (balls_bowled > balls_faced). `role` would mis-tag
            # Bumrah as all_rounder (lenient 60-ball threshold) and
            # `bowling_style` mis-tags part-time bowlers like Kohli /
            # Rohit because they crossed 120 balls in middle overs.
            target_is_bowler = target_bb > target_bf
            # Same ratio decides which cohort to surface (q side).
            cohort_pred = (
                "q.balls_bowled > q.balls_faced"
                if target_is_bowler
                else "q.balls_faced >= q.balls_bowled"
            )
            if target_is_bowler:
                rows = s.run(
                    f"""
                    MATCH (p:Player {{unique_name: $name}})<-[:FACED]-(batter:Player)
                    MATCH (batter)-[:FACED]->(q:Player)
                    WHERE q.cricsheet_id <> p.cricsheet_id
                      AND COALESCE(q.unresolved, false) = false
                      AND {cohort_pred}
                    WITH q, COUNT(DISTINCT batter) AS shared
                    ORDER BY shared DESC
                    LIMIT $k
                    RETURN q.unique_name AS name,
                           q.cricsheet_id AS cricsheet_id,
                           q.bowling_style AS bowling_style,
                           shared AS shared_batters
                    """,
                    name=unique_name,
                    k=top_k,
                ).data()
            else:
                rows = s.run(
                    f"""
                    MATCH (p:Player {{unique_name: $name}})-[:FACED]->(b:Player)
                    MATCH (q:Player)-[:FACED]->(b)
                    WHERE q.cricsheet_id <> p.cricsheet_id
                      AND COALESCE(q.unresolved, false) = false
                      AND {cohort_pred}
                    WITH q, COUNT(DISTINCT b) AS shared
                    ORDER BY shared DESC
                    LIMIT $k
                    RETURN q.unique_name AS name,
                           q.cricsheet_id AS cricsheet_id,
                           q.role AS role,
                           shared AS shared_bowlers
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
    bowling_style: str | None = None,
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
                "MATCH (p:Player {unique_name: $name}) "
                "RETURN p.role AS role, p.bowling_style AS bowling_style, "
                "p.balls_bowled AS bb, p.balls_faced AS bf",
                name=unique_name,
            ).single()
            if target is None:
                return []
            target_bb = target["bb"] or 0
            target_bf = target["bf"] or 0

            # Auto-flip on actual ball-volume ratio. `role` mis-tags
            # Bumrah as all_rounder (lenient 60-ball threshold) and
            # `bowling_style` mis-tags part-time bowlers like Kohli /
            # Rohit (they crossed the 120-ball threshold so the
            # middle-overs heuristic fires). `balls_bowled > balls_faced`
            # is the simplest unambiguous discriminator.
            target_is_bowler = target_bb > target_bf
            cohort_pred = (
                "q.balls_bowled > q.balls_faced"
                if target_is_bowler
                else "q.balls_faced >= q.balls_bowled"
            )
            if target_is_bowler:
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
            # Always restrict q to the same archetype as the target,
            # via the ball-volume ratio.
            filters.append(cohort_pred)
            if role:
                filters.append("q.role = $role")
            if max_balls_bowled is not None:
                filters.append("q.balls_bowled <= $max_balls_bowled")
            if max_balls_faced is not None:
                filters.append("q.balls_faced <= $max_balls_faced")
            if min_last_match_date:
                filters.append("q.last_match_date >= $min_last_match_date")
            if bowling_style:
                # Only meaningful when the target *is* a bowler — but harmless
                # for batter targets (the candidate's bowling_style just won't
                # match anything sensible there, and the user opted in).
                filters.append("q.bowling_style = $bowling_style")
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
                   q.bowling_style AS bowling_style,
                   q.bowling_style_source AS bowling_style_source,
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
            if bowling_style:
                params["bowling_style"] = bowling_style
            return s.run(cypher, **params).data()
    finally:
        drv.close()
