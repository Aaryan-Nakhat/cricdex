# CricDex REST API

FastAPI app at `cricdex.api.main:app`, served on port 8080 inside the
`cricdex-app` container. Auto-generated OpenAPI explorer at
[`http://localhost:8080/docs`](http://localhost:8080/docs).

## Conventions

- Read endpoints: `GET` + query-string params.
- Write-shape or large-body endpoints: `POST` + JSON body.
- All responses JSON. Errors are FastAPI's standard
  `{"detail": "..."}` shape.
- No auth in v1 — bind behind a reverse proxy (Cloudflare Workers
  planned) before exposing publicly.

## Endpoints

### Health

| Method | Path | Notes |
|---|---|---|
| GET | `/health` | Liveness probe. Returns `{status, version}`. |

### Records (`docs/METRICS.md` cousin)

| Method | Path | Notes |
|---|---|---|
| GET | `/v1/records` | Lists every record query slug. |
| GET | `/v1/records/{record}?collection=&top_n=` | Top-N for a record (e.g. `career_run_leaders`, `fastest_fifty`, `best_bowling_innings`). |
| GET | `/v1/records-on-this-day?month=&day=&collection=&top_n=` | Notable ≥50-run innings + ≥4-wicket spells from the same calendar date. |

### Venues

| Method | Path | Notes |
|---|---|---|
| GET | `/v1/venues?collection=&min_matches=` | Every venue with ≥N matches, sorted by sample size. |
| GET | `/v1/venues/{venue}/profile?collection=` | Per-venue innings totals + chase/set winrate + phase rates + dismissal mix. |

### Players + scout

| Method | Path | Notes |
|---|---|---|
| GET | `/v1/players/{name}?collection=` | Full profile: IDs + Wikidata + career + every metric + Bayes + style twins. |
| GET | `/v1/players/{name}/style-twins?role=&k=&collection=` | k-NN over the metric+rating vector. |
| POST | `/v1/compare` body `{players, collection}` | Side-by-side comparison rows. |

### Rules QA

| Method | Path | Notes |
|---|---|---|
| POST | `/v1/rules/ask` body `{query, formats?, top_k}` | RAG QA with citations (`[source_id §law_number]`). Supports format filter (`ipl`, `t20i`, `mcc_laws`, `code_of_conduct`, …). |

### Auction

| Method | Path | Notes |
|---|---|---|
| POST | `/v1/auction/solve` body `{pool, purse, squad_size, overseas_cap, role_mins}` | MILP squad optimiser. Returns selected players + totals or an infeasibility reason. |

## Quick curl examples

```bash
curl -s localhost:8080/health | jq

curl -s "localhost:8080/v1/records/career_run_leaders?collection=ipl&top_n=5" | jq '.[].batter'

curl -s "localhost:8080/v1/venues/Wankhede%20Stadium%2C%20Mumbai/profile?collection=ipl" | jq '.chase_vs_set'

curl -s localhost:8080/v1/players/V%20Kohli?collection=ipl | jq '.career'

curl -s -X POST localhost:8080/v1/rules/ask \
    -H 'content-type: application/json' \
    -d '{"query":"impact player rule","formats":["ipl"]}' | jq '.answer'
```

## Future shape

- GraphQL layer once schemas stabilise.
- Cloudflare-Worker edge for rate-limit + auth.
- Web-socket endpoint for live-match insights (depends on the
  `live` Cricbuzz scraper unblocking).
