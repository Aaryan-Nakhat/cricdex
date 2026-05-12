"""Bulk fetch cricket-player metadata from Wikidata via SPARQL.

We use Wikidata as the enrichment source instead of scraping
ESPNcricinfo (which is Akamai-walled) — and Wikidata happens to ship
P2697 = "ESPNcricinfo player ID" as a structured property, so the join
back to the People Register's `key_cricinfo` is trivial.

The full-corpus query (`?player wdt:P2697 ?id`) is too heavy for the
public WDQS endpoint and hits 429 immediately. We chunk by reading the
list of Cricinfo IDs we actually care about from the People Register
and querying in batches of `BATCH_SIZE` ids via SPARQL `VALUES`.

Wikidata properties used
------------------------
P2697   ESPNcricinfo player ID   (cricinfo_id)
P569    date of birth
P27     country of citizenship
P19     place of birth
P21     sex / gender
"""

from __future__ import annotations

import time
from pathlib import Path

import duckdb
import httpx
import polars as pl
from loguru import logger

from cricdex.config import DATA_DIR

DEFAULT_DB_PATH = DATA_DIR / "cricsheet" / "cricsheet.duckdb"

SPARQL_ENDPOINT = "https://query.wikidata.org/sparql"
USER_AGENT = "cricdex/0.1 (https://github.com/Aaryan-Nakhat/cricdex)"
# WDQS rate-limits broad queries from datacenter IPs aggressively.
# 50-id batches with 3 OPTIONALs reliably get HTTP 200; 200-id with 4
# OPTIONALs gets 429 immediately.
BATCH_SIZE = 50
SLEEP_BETWEEN_BATCHES_S = 2.0
CHECKPOINT_FILENAME = "wikidata_checkpoint.jsonl"


def _query_template(values_block: str) -> str:
    # Trimmed to 3 OPTIONALs to keep WDQS happy from datacenter IPs.
    # Birthplace label dropped — re-fetch later per-Q-id if needed.
    return f"""
    SELECT
        ?cricinfo_id ?player ?dob
        ?countryLabel ?genderLabel
    WHERE {{
        VALUES ?cricinfo_id {{ {values_block} }}
        ?player wdt:P2697 ?cricinfo_id .
        OPTIONAL {{ ?player wdt:P569 ?dob }}
        OPTIONAL {{ ?player wdt:P27 ?country }}
        OPTIONAL {{ ?player wdt:P21 ?gender }}
        SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }}
    }}
    """


def _load_cricinfo_ids(con: duckdb.DuckDBPyConnection) -> list[str]:
    tables = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
    if "people" not in tables:
        raise RuntimeError("`people` table missing — run scripts/ingest_people.py first")
    rows = con.execute(
        "SELECT DISTINCT CAST(key_cricinfo AS VARCHAR) AS k "
        "FROM people WHERE key_cricinfo IS NOT NULL"
    ).fetchall()
    return [r[0] for r in rows]


def _query_batch(ids: list[str], cx: httpx.Client) -> list[dict]:
    values_block = " ".join(f'"{i}"' for i in ids)
    r = cx.get(
        SPARQL_ENDPOINT,
        params={"query": _query_template(values_block), "format": "json"},
    )
    r.raise_for_status()
    raw = r.json()["results"]["bindings"]
    out: dict[str, dict] = {}
    for b in raw:
        cid = b["cricinfo_id"]["value"]
        row = out.setdefault(
            cid,
            {
                "cricinfo_id": cid,
                "wikidata_id": b["player"]["value"].rsplit("/", 1)[-1],
                "dob": None,
                "country": None,
                "gender": None,
            },
        )
        for key, sparql_key in [
            ("dob", "dob"),
            ("country", "countryLabel"),
            ("gender", "genderLabel"),
        ]:
            if row[key] is None and sparql_key in b:
                row[key] = b[sparql_key]["value"]
    return list(out.values())


def fetch_sparql_all(
    cricinfo_ids: list[str],
    timeout: float = 120.0,
    checkpoint_dir: Path | None = None,
) -> list[dict]:
    """Fetch in resumable batches.

    A JSONL checkpoint is appended after every successful batch under
    `<checkpoint_dir>/wikidata_checkpoint.jsonl`, plus a sibling
    `wikidata_done_ids.txt`. If the run dies mid-way (WDQS 429
    storm, network blip, etc.), the next call resumes where we left
    off rather than refetching the whole corpus.
    """
    import json

    headers = {"User-Agent": USER_AGENT, "Accept": "application/sparql-results+json"}
    checkpoint_dir = checkpoint_dir or (DATA_DIR / "register")
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    cp_path = checkpoint_dir / CHECKPOINT_FILENAME
    done_path = checkpoint_dir / "wikidata_done_ids.txt"

    done_ids: set[str] = set()
    if done_path.exists():
        done_ids = {line.strip() for line in done_path.read_text().splitlines() if line.strip()}

    results: list[dict] = []
    if cp_path.exists():
        with open(cp_path) as f:
            for line in f:
                results.append(json.loads(line))
        logger.info(f"resumed from checkpoint: {len(results):,} rows already fetched")

    remaining = [i for i in cricinfo_ids if i not in done_ids]
    logger.info(
        f"WDQS plan — total {len(cricinfo_ids):,}, "
        f"done {len(done_ids):,}, remaining {len(remaining):,}, "
        f"batch_size {BATCH_SIZE}, sleep {SLEEP_BETWEEN_BATCHES_S}s"
    )

    with (
        httpx.Client(timeout=timeout, headers=headers) as cx,
        open(cp_path, "a") as cp_fh,
        open(done_path, "a") as done_fh,
    ):
        for start in range(0, len(remaining), BATCH_SIZE):
            batch = remaining[start : start + BATCH_SIZE]
            attempt = 0
            while True:
                try:
                    chunk = _query_batch(batch, cx)
                    break
                except httpx.HTTPStatusError as e:
                    if e.response.status_code == 429 and attempt < 5:
                        wait = 10 * (attempt + 1)
                        logger.warning(
                            f"WDQS 429 on batch {start // BATCH_SIZE} "
                            f"— sleeping {wait}s (attempt {attempt + 1}/5)"
                        )
                        time.sleep(wait)
                        attempt += 1
                        continue
                    raise
            for row in chunk:
                cp_fh.write(json.dumps(row) + "\n")
            cp_fh.flush()
            for cid in batch:
                done_fh.write(f"{cid}\n")
            done_fh.flush()
            results.extend(chunk)
            logger.info(
                f"batch {start // BATCH_SIZE + 1}/"
                f"{(len(remaining) + BATCH_SIZE - 1) // BATCH_SIZE}: "
                f"requested {len(batch)}, got {len(chunk)}; "
                f"running total {len(results):,}"
            )
            time.sleep(SLEEP_BETWEEN_BATCHES_S)
    return results


def ingest(db_path: Path | str = DEFAULT_DB_PATH) -> int:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(str(db_path), read_only=True) as con_ro:
        cricinfo_ids = _load_cricinfo_ids(con_ro)
    logger.info(
        f"querying Wikidata for {len(cricinfo_ids):,} Cricinfo IDs in batches of {BATCH_SIZE}"
    )
    rows = fetch_sparql_all(cricinfo_ids)
    if not rows:
        logger.warning("Wikidata returned 0 rows")
        return 0
    df = pl.DataFrame(rows)
    # DOB comes back as `+1989-08-23T00:00:00Z` — strip the leading + so DuckDB
    # parses it as a clean ISO date.
    df = df.with_columns(
        pl.col("dob")
        .str.strip_prefix("+")
        .str.slice(0, 10)
        .str.strptime(pl.Date, format="%Y-%m-%d", strict=False)
        .alias("dob"),
        pl.col("cricinfo_id").cast(pl.Int64).alias("cricinfo_id"),
    )
    con = duckdb.connect(str(db_path))
    try:
        con.execute("DROP TABLE IF EXISTS wikidata_players")
        con.register("df", df)
        con.execute("CREATE TABLE wikidata_players AS SELECT * FROM df")
        n = con.execute("SELECT COUNT(*) FROM wikidata_players").fetchone()[0]
    finally:
        con.close()
    logger.info(f"wrote {n:,} rows → wikidata_players")
    return n
