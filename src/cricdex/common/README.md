# common

Shared utilities: DuckDB connection, Postgres engine, Qdrant client, LLM clients, logging.

Only `common/` may be imported by every other module. Modules must not import each other directly — communicate via the shared data layer.
