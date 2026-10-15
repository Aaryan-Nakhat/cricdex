# api

Public FastAPI service.

Surfaces records, venues, player profiles / style twins, compare and the NGI leaderboard via REST, all over the local DuckDB. No auth or rate limit yet (a Cloudflare Worker edge is planned); a GraphQL layer may follow once schemas stabilize. Endpoints are listed in [`docs/API.md`](../../../docs/API.md).
