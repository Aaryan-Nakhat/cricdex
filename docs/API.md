# CricDex REST API

FastAPI app at `cricdex.api.main:app`, served on port 8080 inside the
`cricdex-app` container. Auto-generated OpenAPI explorer at
[`http://localhost:8080/docs`](http://localhost:8080/docs).

## Conventions

- Read endpoints: `GET` + query-string params.
- Write-shape or large-body endpoints: `POST` + JSON body.
- All responses JSON. Errors are FastAPI's standard
  `{"detail": "..."}` shape: 400 for a malformed collection name, 404 for
  an unknown player (the player routes and `/v1/compare`), 503 when the data
  a route needs hasn't been built yet (the detail says which command to run).
- No auth in v1 — bind behind a reverse proxy (Cloudflare Workers
  planned) before exposing publicly.
- Every endpoint queries the local DuckDB (`data/cricsheet.duckdb`) and
  `data/metrics/`, not the exported site snapshot — run
  `cricdex data ingest cricsheet` / `metrics` (or `make refresh`) first.

## Endpoints

### Health

| Method | Path | Notes |
|---|---|---|
| GET | `/health` | Liveness probe. Returns `{status, version}`. |

### Records (`docs/METRICS.md` cousin)

| Method | Path | Notes |
|---|---|---|
| GET | `/v1/records` | Lists every record query slug as `{records: [...]}`. |
| GET | `/v1/records/{record}?collection=&top_n=` | Top-N for a record (e.g. `career_run_leaders`, `fastest_fifty`, `best_bowling_innings`). |
| GET | `/v1/records-on-this-day?month=&day=&collection=&top_n=` | Notable ≥50-run innings + ≥4-wicket spells from the same calendar date. |

### Venues

| Method | Path | Notes |
|---|---|---|
| GET | `/v1/venues?collection=&min_matches=` | Every venue with ≥N matches, sorted by sample size. |
| GET | `/v1/venues/{venue}/profile?collection=` | Per-venue innings totals + chase/set winrate + phase rates + dismissal mix. |

### Players

| Method | Path | Notes |
|---|---|---|
| GET | `/v1/players/{name}?collection=` | Full profile: IDs + Wikidata + career + every metric + Bayes + style twins. `name` is the exact Cricsheet scorecard name (`V Kohli`); an unknown name is a 404 with the closest names. |
| GET | `/v1/players/{name}/style-twins?role=&k=&collection=` | Style twins: same role and bowling type, closest on slot, phase tempo, boundaries / dots, spin vs pace, risk (batters) or phase usage, economy / strike by phase, wicket types (bowlers). Rows: `name`, `cricsheet_id`, `distance` (1 − alike), `alike` (0–100). METHODOLOGY §5a. |
| POST | `/v1/compare` body `{players, collection}` | Side-by-side comparison rows (a bare JSON list). |

### Metrics

| Method | Path | Notes |
|---|---|---|
| GET | `/v1/metrics/ngi?collection=&min_matches=&top_n=` | NGI leaderboard as `{collection, rows}` (defaults `ipl`, 20, 50), sorted by NGI per match. Reads `data/metrics/ngi_<collection>.json`; when that file is missing it returns 503 with a hint to run `cricdex data ingest metrics -c <collection>` (the model fit is too heavy for a request). |

## Quick curl examples

```bash
curl -s localhost:8080/health | jq

curl -s "localhost:8080/v1/records/career_run_leaders?collection=ipl&top_n=5" | jq '.[].batter'

curl -s "localhost:8080/v1/venues/Wankhede%20Stadium%2C%20Mumbai/profile?collection=ipl" | jq '.chase_vs_set'

curl -s localhost:8080/v1/players/V%20Kohli?collection=ipl | jq '.career'

curl -s -X POST localhost:8080/v1/compare \
    -H 'content-type: application/json' \
    -d '{"players":["V Kohli","RG Sharma"],"collection":"ipl"}' | jq '.'

curl -s "localhost:8080/v1/metrics/ngi?collection=ipl&top_n=10" | jq '.rows'
```

## Future shape

- GraphQL layer once schemas stabilise.
- Cloudflare-Worker edge for rate-limit + auth.
