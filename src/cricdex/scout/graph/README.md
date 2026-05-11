# scout/graph

Neo4j-backed player relationship graph. Populated from the DuckDB
ball-by-ball + people register; consumed by Bayesian ratings and
(later) style-twin search.

## Schema

```
(Player {cricsheet_id, unique_name, key_cricinfo, key_cricbuzz, unresolved})
(Match  {match_id, match_date, match_type, league, overs})
(Venue  {name, city})

(Match)-[:AT]->(Venue)
(Player)-[:FACED {balls, runs, dismissals}]->(Player)
```

`FACED` edges aggregate every ball a given batter faced a given bowler
across the collection. Re-run `populate` to refresh.

## Run

```bash
make docker-scout-up           # spin up neo4j (profile=scout)
make docker-scout-bootstrap    # constraints + indexes
make docker-scout-populate     # COLLECTION=ipl by default
```

Neo4j Browser at http://localhost:7474 (user `neo4j`, pass `cricdex_dev`).

## Example queries

```cypher
// Top-faced bowlers for V Kohli
MATCH (b:Player {unique_name: 'V Kohli'})-[f:FACED]->(k:Player)
WHERE f.balls >= 30
RETURN k.unique_name, f.balls, f.runs, f.dismissals
ORDER BY f.balls DESC LIMIT 10;

// All bowlers ever to dismiss a specific batter
MATCH (b:Player {unique_name: 'MS Dhoni'})-[f:FACED]->(k:Player)
WHERE f.dismissals > 0
RETURN k.unique_name, f.dismissals ORDER BY f.dismissals DESC;
```
