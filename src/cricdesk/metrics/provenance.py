"""What a metric cache was built from, so the export can refuse a stale one.

`scripts/compute_metrics.py` writes `data/metrics/<metric>_<collection>.json`; next to it goes
`<metric>_<collection>.stamp.json` with the collection's matches (count and last date), a hash of this
package's code and, for the boards that read its wicket-keeper tags (keeping, fielding), the player
master build. The export compares each cache's stamp with the current ones: an all-time board
computed before a data refresh or a code fix (the IPL keeping board kept a non-keeper's 47 catches
for ten days that way) fails the export instead of shipping next to fresh window boards.
"""

from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from pathlib import Path

import duckdb

from cricdesk.common.sql import table_suffix

PKG = Path(__file__).resolve().parent


@lru_cache(maxsize=1)
def code_hash() -> str:
    """sha256 (first 16 hex) over every module of `cricdesk.metrics`: any change to how a metric is
    computed makes every cache stale."""
    h = hashlib.sha256()
    for p in sorted(PKG.glob("*.py")):
        if p.name == "provenance.py":
            continue
        h.update(p.name.encode())
        h.update(p.read_bytes().replace(b"\r\n", b"\n"))
    return h.hexdigest()[:16]


# metrics whose rows depend on the player master's tags (who is a wicket-keeper)
USES_MASTER = frozenset({"keeping", "fielding"})


def fingerprint(con: duckdb.DuckDBPyConnection, collection: str, metric: str) -> dict:
    """The data, code (and, for `USES_MASTER`, identity build) a metric cache is computed from."""
    safe = table_suffix(collection)
    n, last = con.execute(f"SELECT COUNT(*), MAX(match_date) FROM matches_{safe}").fetchone()
    fp = {
        "matches": int(n or 0),
        "last_match": str(last)[:10] if last else None,
        "code": code_hash(),
    }
    if metric in USES_MASTER:
        from cricdesk.scout.identity import master

        fp["player_master"] = master.build_stamp()["hash"]
    return fp


def stamp_path(cache: Path) -> Path:
    return cache.with_name(cache.stem + ".stamp.json")


def write_stamp(cache: Path, fp: dict) -> Path:
    path = stamp_path(cache)
    path.write_text(json.dumps(fp, indent=1, sort_keys=True), encoding="utf-8")
    return path


def stale_reason(cache: Path, fp: dict) -> str | None:
    """Why this cache doesn't match the current fingerprint (None = current)."""
    path = stamp_path(cache)
    if not path.exists():
        return "no stamp (computed before stamps existed)"
    old = json.loads(path.read_text(encoding="utf-8"))
    diffs = [f"{k} {old.get(k)!r} → {v!r}" for k, v in fp.items() if old.get(k) != v]
    return "; ".join(diffs) or None


__all__ = [
    "USES_MASTER",
    "code_hash",
    "fingerprint",
    "stale_reason",
    "stamp_path",
    "write_stamp",
]
