from contextlib import contextmanager

import duckdb

from cricdesk.config import settings


@contextmanager
def duck():
    con = duckdb.connect(settings.duckdb_path)
    try:
        yield con
    finally:
        con.close()
