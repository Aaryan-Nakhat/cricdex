"""Neo4j schema bootstrap for the scout player graph.

Idempotent — running it multiple times is safe. Creates the constraints
and indexes the graph writers rely on:

    (Player {cricsheet_id})              UNIQUE constraint
    (Match  {match_id})                   UNIQUE constraint
    (Venue  {name})                       UNIQUE constraint
    (Player)-[FACED  {match_id, runs, balls, dismissals}]->(Player)
    (Player)-[PLAYED_AT {match_id}]->(Venue)
    (Match)-[AT]->(Venue)
"""

from __future__ import annotations

from neo4j import Driver, GraphDatabase

from cricdex.config import settings


def driver() -> Driver:
    return GraphDatabase.driver(
        settings.neo4j_uri,
        auth=(settings.neo4j_user, settings.neo4j_password or "cricdex_dev"),
    )


CONSTRAINTS = [
    "CREATE CONSTRAINT player_id_unique IF NOT EXISTS FOR (p:Player) REQUIRE p.cricsheet_id IS UNIQUE",
    "CREATE CONSTRAINT match_id_unique IF NOT EXISTS FOR (m:Match) REQUIRE m.match_id IS UNIQUE",
    "CREATE CONSTRAINT venue_name_unique IF NOT EXISTS FOR (v:Venue) REQUIRE v.name IS UNIQUE",
]

INDEXES = [
    "CREATE INDEX player_unique_name IF NOT EXISTS FOR (p:Player) ON (p.unique_name)",
    "CREATE INDEX player_cricinfo IF NOT EXISTS FOR (p:Player) ON (p.key_cricinfo)",
    "CREATE INDEX match_date IF NOT EXISTS FOR (m:Match) ON (m.match_date)",
    "CREATE INDEX match_type IF NOT EXISTS FOR (m:Match) ON (m.match_type)",
]


def bootstrap(drv: Driver | None = None) -> None:
    own = drv is None
    drv = drv or driver()
    try:
        with drv.session() as s:
            for c in CONSTRAINTS:
                s.run(c)
            for i in INDEXES:
                s.run(i)
    finally:
        if own:
            drv.close()
