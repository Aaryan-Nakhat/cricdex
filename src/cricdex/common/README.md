# common

Shared utilities: DuckDB connection (`db.py`), LLM client (`llm.py`), logging.

Only `common/` may be imported by every other module. Modules must not import each other directly — communicate via the shared data layer.
