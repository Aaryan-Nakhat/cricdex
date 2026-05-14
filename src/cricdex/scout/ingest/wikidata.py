"""Wikidata enrichment for the People Register.

Two paths are wired:

1. **Entity API (preferred, works from any IP)** — for each cricketer
   in the register we resolve a Q-id via `wbsearchentities` then fetch
   the full entity JSON. The Entity API sits on a different rate-
   limit pool than WDQS / SPARQL so it doesn't 429 from datacenter
   IPs. Throttle with `SLEEP_BETWEEN_REQUESTS_S` to stay polite.

2. **Legacy SPARQL bulk** — kept around as `fetch_sparql_all` for
   when this VM moves to residential IPs and WDQS un-throttles.

Fields fetched (most cricketers won't have all):

    P569    date of birth
    P27     country of citizenship       (Q-id, resolved to label later)
    P19     place of birth               (Q-id, resolved to label later)
    P21     sex / gender                 (Q-id)
    P18     image (Commons file name)    → Commons URL via thumb endpoint
    P3526   ESPNcricinfo player ID       (e.g. "Jasprit-Bumrah/51719")
    P2697   ESPNcricinfo Statsguru ID    — our join key vs `people.csv`
    P2698   Cricbuzz player ID
    P2002   Twitter handle
    P2003   Instagram username
    P166    awards (Q-ids — labels resolved on demand)

Output: a JSON cache at `data/curated/wikidata_enrichment.json` keyed
on `cricsheet_id`. Cricsheet → Statsguru bridge via `people.csv`.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import duckdb
import httpx
from loguru import logger

from cricdex.config import DATA_DIR, ROOT

DEFAULT_DB_PATH = DATA_DIR / "cricsheet" / "cricsheet.duckdb"

WD_SEARCH_URL = "https://www.wikidata.org/w/api.php"
WD_ENTITY_URL = "https://www.wikidata.org/wiki/Special:EntityData/{qid}.json"
USER_AGENT = "cricdex/0.1 (https://github.com/Aaryan-Nakhat/cricdex)"

ENRICHMENT_PATH = ROOT / "data" / "curated" / "wikidata_enrichment.json"
SLEEP_BETWEEN_REQUESTS_S = 0.6  # ~100 req/min; well under MediaWiki API soft cap.

# Wikidata properties we care about, mapped to flat output keys.
PROPS = {
    "P569": "dob",
    "P27": "country_qid",
    "P19": "birthplace_qid",
    "P21": "gender_qid",
    "P18": "image_filename",
    "P3526": "espn_id",  # "Jasprit-Bumrah/51719"
    "P2697": "statsguru_id",  # "625383" — bridges to people.csv `key_cricinfo`
    "P2698": "cricbuzz_id",
    "P2002": "twitter",
    "P2003": "instagram",
}


# ---- legacy SPARQL bulk (kept for residential-IP runs) --------------------

BATCH_SIZE = 30
SLEEP_BETWEEN_BATCHES_S = 3.0
CHECKPOINT_FILENAME = "wikidata_checkpoint.jsonl"
SPARQL_ENDPOINT = "https://query.wikidata.org/sparql"


def _sparql_template(values_block: str) -> str:
    return f"""
    SELECT
        ?cricinfo_id ?player ?dob
        ?countryLabel ?genderLabel ?birthplaceLabel
        ?image ?espn_id ?cricbuzz_id ?twitter ?instagram
    WHERE {{
        VALUES ?cricinfo_id {{ {values_block} }}
        ?player wdt:P2697 ?cricinfo_id .
        OPTIONAL {{ ?player wdt:P569 ?dob }}
        OPTIONAL {{ ?player wdt:P27 ?country }}
        OPTIONAL {{ ?player wdt:P21 ?gender }}
        OPTIONAL {{ ?player wdt:P19 ?birthplace }}
        OPTIONAL {{ ?player wdt:P18 ?image }}
        OPTIONAL {{ ?player wdt:P3526 ?espn_id }}
        OPTIONAL {{ ?player wdt:P2698 ?cricbuzz_id }}
        OPTIONAL {{ ?player wdt:P2002 ?twitter }}
        OPTIONAL {{ ?player wdt:P2003 ?instagram }}
        SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }}
    }}
    """


# ---- Entity-API path ------------------------------------------------------


def _claim_value(claims: dict, prop: str) -> Any:
    v = claims.get(prop, [])
    if not v:
        return None
    mv = v[0].get("mainsnak", {}).get("datavalue", {}).get("value")
    if isinstance(mv, dict):
        return mv.get("id") or mv.get("time") or mv
    return mv


def _qid_via_statsguru(statsguru_id: str, cx: httpx.Client) -> str | None:
    """Bridge from Cricsheet's `key_cricinfo` (Statsguru numeric ID) to
    a Wikidata Q-id via the action API's `haswbstatement` search.

    Bypasses SPARQL/WDQS entirely — sits on the action API rate-limit
    pool which is generous from any IP class. Statsguru IDs match
    Wikidata's P2697 property 1:1, so this is the cleanest bridge.
    """
    if not statsguru_id:
        return None
    r = cx.get(
        WD_SEARCH_URL,
        params={
            "action": "query",
            "format": "json",
            "list": "search",
            "srsearch": f"haswbstatement:P2697={statsguru_id}",
            "srlimit": 1,
        },
    )
    if r.status_code != 200:
        return None
    hits = r.json().get("query", {}).get("search", [])
    return hits[0]["title"] if hits else None


def search_qid(name: str, cx: httpx.Client) -> str | None:
    """Fall-back resolver: free-text name search via `wbsearchentities`.

    Only used when the statsguru bridge can't resolve. Wikidata search
    is poor at matching cricket-style initials ("Z Khan" → "Zaheer
    Khan"), so this catches ~15-20% of players the bridge misses.
    """
    r = cx.get(
        WD_SEARCH_URL,
        params={
            "action": "wbsearchentities",
            "search": name,
            "language": "en",
            "format": "json",
            "limit": 5,
            "type": "item",
        },
    )
    if r.status_code != 200:
        return None
    for hit in r.json().get("search", []):
        desc = (hit.get("description") or "").lower()
        if any(kw in desc for kw in ("cricket", "batsman", "bowler", "wicket")):
            return hit["id"]
    return None


def resolve_qid(player: dict, cx: httpx.Client) -> str | None:
    """Try statsguru-bridge first, then fall back to name search."""
    qid = _qid_via_statsguru(player.get("statsguru_id"), cx)
    if qid:
        return qid
    return search_qid(player["unique_name"], cx)


def fetch_entity(qid: str, cx: httpx.Client) -> dict[str, Any] | None:
    r = cx.get(WD_ENTITY_URL.format(qid=qid))
    if r.status_code != 200:
        return None
    ent = r.json().get("entities", {}).get(qid)
    if not ent:
        return None
    claims = ent.get("claims", {})
    out = {
        "wikidata_qid": qid,
        "label": (ent.get("labels", {}).get("en") or {}).get("value"),
    }
    for prop, key in PROPS.items():
        out[key] = _claim_value(claims, prop)
    # DOB normalisation: "+1993-12-06T00:00:00Z" → "1993-12-06"
    if isinstance(out.get("dob"), str) and out["dob"].startswith("+"):
        out["dob"] = out["dob"][1:11]
    # Commons image → direct thumbnail URL
    if out.get("image_filename"):
        fname = out["image_filename"].replace(" ", "_")
        out["image_url"] = f"https://commons.wikimedia.org/wiki/Special:FilePath/{fname}?width=400"
    return out


def _load_register_players(
    db_path: Path | str,
    only_active: bool = True,
    top_n_by_balls: int | None = 300,
) -> list[dict]:
    """Players we want to enrich: name + cricsheet_id + cricinfo statsguru id.

    `only_active=True` filters to players who actually appear in any
    ingested `balls_<collection>` table. The full `people` register has
    >17k entries — most are obscure names with no Wikidata page.
    Restricting to ingested-collection players keeps enrichment fast +
    actually useful.
    """
    with duckdb.connect(str(db_path), read_only=True) as con:
        tables = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
        if "people" not in tables:
            raise RuntimeError("`people` table missing — run cricdex data ingest people")

        if not only_active:
            rows = con.execute(
                "SELECT unique_name, identifier AS cricsheet_id, "
                "CAST(key_cricinfo AS VARCHAR) AS statsguru_id "
                "FROM people WHERE identifier IS NOT NULL"
            ).fetchall()
            return [{"unique_name": r[0], "cricsheet_id": r[1], "statsguru_id": r[2]} for r in rows]

        ball_tables = [t for t in tables if t.startswith("balls_")]
        if not ball_tables:
            raise RuntimeError("no balls_<collection> tables yet — ingest cricsheet first")
        # Per-name ball volume across every ingested collection — both
        # batting and bowling — so we can rank.
        unions = []
        for t in ball_tables:
            unions.append(f"SELECT batter AS name, 1 AS n FROM {t} WHERE batter IS NOT NULL")
            unions.append(f"SELECT bowler, 1 FROM {t} WHERE bowler IS NOT NULL")
            unions.append(f"SELECT non_striker, 1 FROM {t} WHERE non_striker IS NOT NULL")
        active_sql = " UNION ALL ".join(unions)
        limit_clause = f" LIMIT {top_n_by_balls}" if top_n_by_balls else ""
        rows = con.execute(
            f"""
            WITH all_apps AS ({active_sql}),
                 ranked AS (
                     SELECT name, COUNT(*) AS appearances
                     FROM all_apps GROUP BY name
                 )
            SELECT p.unique_name,
                   p.identifier AS cricsheet_id,
                   CAST(p.key_cricinfo AS VARCHAR) AS statsguru_id,
                   r.appearances
            FROM people p
            JOIN ranked r ON r.name = p.unique_name
            WHERE p.identifier IS NOT NULL
            ORDER BY r.appearances DESC{limit_clause}
            """
        ).fetchall()
    return [{"unique_name": r[0], "cricsheet_id": r[1], "statsguru_id": r[2]} for r in rows]


def _load_existing_cache() -> dict:
    if ENRICHMENT_PATH.exists():
        return json.loads(ENRICHMENT_PATH.read_text())
    return {}


def _save_cache(cache: dict) -> None:
    ENRICHMENT_PATH.parent.mkdir(parents=True, exist_ok=True)
    ENRICHMENT_PATH.write_text(json.dumps(cache, indent=2, sort_keys=True))


def enrich_via_entity_api(
    limit: int | None = None,
    force: bool = False,
    db_path: Path | str = DEFAULT_DB_PATH,
) -> dict:
    """Walk the people register, search Wikidata by name, fetch the
    entity, persist to ~/.cricdex/data/curated/wikidata_enrichment.json.

    Skips players already in the cache unless `force=True`.
    Throttles between requests so we stay under MediaWiki's
    polite-use limit.
    """
    cache = _load_existing_cache()
    players = _load_register_players(db_path)
    if limit:
        players = players[:limit]

    todo = [p for p in players if force or p["cricsheet_id"] not in cache]
    logger.info(
        f"wikidata enrichment — register={len(players)}  cached={len(cache)}  todo={len(todo)}"
    )

    fetched = 0
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    with httpx.Client(timeout=30.0, headers=headers) as cx:
        for i, p in enumerate(todo, 1):
            try:
                qid = resolve_qid(p, cx)
                time.sleep(SLEEP_BETWEEN_REQUESTS_S)
                if not qid:
                    cache[p["cricsheet_id"]] = {"_status": "not_found", **p}
                    continue
                ent = fetch_entity(qid, cx)
                time.sleep(SLEEP_BETWEEN_REQUESTS_S)
                if not ent:
                    cache[p["cricsheet_id"]] = {"_status": "fetch_failed", "wikidata_qid": qid, **p}
                    continue
                cache[p["cricsheet_id"]] = {"_status": "ok", **p, **ent}
                fetched += 1
            except Exception as e:
                logger.warning(f"wikidata fail for {p['unique_name']!r}: {e}")
                cache[p["cricsheet_id"]] = {"_status": "error", "error": str(e), **p}
            if i % 25 == 0:
                _save_cache(cache)
                logger.info(f"  checkpoint @ {i}/{len(todo)}  (fetched ok: {fetched})")

    _save_cache(cache)
    logger.info(f"wikidata enrichment done — cache size now {len(cache)}, ok={fetched}")
    return cache


# ---- legacy SPARQL ingest (unchanged interface) ---------------------------


def _query_batch(ids: list[str], cx: httpx.Client) -> list[dict]:
    values_block = " ".join(f'"{i}"' for i in ids)
    r = cx.get(
        SPARQL_ENDPOINT,
        params={"query": _sparql_template(values_block), "format": "json"},
    )
    r.raise_for_status()
    raw = r.json()["results"]["bindings"]
    out: dict[str, dict] = {}
    fields = [
        ("dob", "dob"),
        ("country", "countryLabel"),
        ("gender", "genderLabel"),
        ("birthplace", "birthplaceLabel"),
        ("image", "image"),
        ("espn_id", "espn_id"),
        ("cricbuzz_id", "cricbuzz_id"),
        ("twitter", "twitter"),
        ("instagram", "instagram"),
    ]
    for b in raw:
        cid = b["cricinfo_id"]["value"]
        row = out.setdefault(
            cid,
            {
                "cricinfo_id": cid,
                "wikidata_id": b["player"]["value"].rsplit("/", 1)[-1],
                **{k: None for k, _ in fields},
            },
        )
        for key, sparql_key in fields:
            if row[key] is None and sparql_key in b:
                row[key] = b[sparql_key]["value"]
    return list(out.values())


def fetch_sparql_all(
    cricinfo_ids: list[str],
    timeout: float = 120.0,
    checkpoint_dir: Path | None = None,
) -> list[dict]:
    """Bulk SPARQL path — kept around for residential-IP runs only.

    From this VM (GCP datacenter) the public WDQS endpoint 429s
    immediately. Use `enrich_via_entity_api` from datacenter networks.
    """
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
    """Default ingest = Entity API path (works from datacenter IPs).

    Set `CRICDEX_WIKIDATA_SPARQL=1` env var to force the legacy SPARQL
    bulk path when running from residential.
    """
    import os

    if os.environ.get("CRICDEX_WIKIDATA_SPARQL"):
        return _sparql_ingest(db_path=db_path)
    cache = enrich_via_entity_api(db_path=db_path)
    return sum(1 for v in cache.values() if v.get("_status") == "ok")


def _sparql_ingest(db_path: Path | str = DEFAULT_DB_PATH) -> int:
    import polars as pl

    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(str(db_path), read_only=True) as con_ro:
        tables = {r[0] for r in con_ro.execute("SHOW TABLES").fetchall()}
        if "people" not in tables:
            raise RuntimeError("`people` table missing — run cricdex data ingest people")
        cricinfo_ids = [
            r[0]
            for r in con_ro.execute(
                "SELECT DISTINCT CAST(key_cricinfo AS VARCHAR) AS k FROM people "
                "WHERE key_cricinfo IS NOT NULL"
            ).fetchall()
        ]
    logger.info(
        f"querying Wikidata SPARQL for {len(cricinfo_ids):,} Cricinfo IDs in batches of {BATCH_SIZE}"
    )
    rows = fetch_sparql_all(cricinfo_ids)
    if not rows:
        logger.warning("Wikidata returned 0 rows")
        return 0
    df = pl.DataFrame(rows)
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
