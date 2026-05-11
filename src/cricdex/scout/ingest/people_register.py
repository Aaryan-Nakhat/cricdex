"""Cricsheet People Register downloader.

Cricsheet publishes a canonical cross-ID register that maps each player
to their identifier on Cricsheet + ESPNcricinfo + Cricbuzz + CricHeroes
+ 8 other sources. This is the cheapest identity-resolution bootstrap
available — instead of fuzzy-matching names ourselves we lean on a
register that's already curated by the Cricsheet maintainers.

Two files:
    https://cricsheet.org/register/people.csv  — one row per player
    https://cricsheet.org/register/names.csv   — name variants

The downloader stores both as DuckDB tables (`people`, `people_names`)
in the same `cricsheet.duckdb` file the ball-by-ball pipeline uses, so
scouting joins (balls.batter → people.identifier → key_cricinfo) work
out of the box.
"""

from __future__ import annotations

from pathlib import Path

import duckdb
import httpx
from loguru import logger

from cricdex.config import DATA_DIR

CRICSHEET_REGISTER_BASE = "https://cricsheet.org/register"
BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "text/csv,*/*;q=0.8",
}

DEFAULT_DB_PATH = DATA_DIR / "cricsheet" / "cricsheet.duckdb"


def download(out_dir: Path, force: bool = False) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    targets: list[tuple[str, Path]] = [
        ("people.csv", out_dir / "people.csv"),
        ("names.csv", out_dir / "people_names.csv"),
    ]
    for name, dest in targets:
        if dest.exists() and not force:
            logger.info(f"cached: {dest}")
            continue
        url = f"{CRICSHEET_REGISTER_BASE}/{name}"
        logger.info(f"downloading {url}")
        with httpx.stream(
            "GET", url, timeout=60.0, follow_redirects=True, headers=BROWSER_HEADERS
        ) as r:
            r.raise_for_status()
            with open(dest, "wb") as f:
                for chunk in r.iter_bytes(chunk_size=1 << 16):
                    f.write(chunk)
    return targets[0][1], targets[1][1]


def load(
    people_csv: Path,
    names_csv: Path,
    db_path: Path | str = DEFAULT_DB_PATH,
) -> tuple[int, int]:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(db_path))
    try:
        con.execute(
            f"CREATE OR REPLACE TABLE people AS SELECT * FROM read_csv_auto('{people_csv}', header=true)"
        )
        con.execute(
            f"CREATE OR REPLACE TABLE people_names AS SELECT * FROM read_csv_auto('{names_csv}', header=true)"
        )
        n_people = con.execute("SELECT COUNT(*) FROM people").fetchone()[0]
        n_names = con.execute("SELECT COUNT(*) FROM people_names").fetchone()[0]
    finally:
        con.close()
    logger.info(f"loaded people={n_people} people_names={n_names} → {db_path}")
    return n_people, n_names


def ingest(
    out_dir: Path | None = None, db_path: Path | str = DEFAULT_DB_PATH, force: bool = False
) -> tuple[int, int]:
    out_dir = out_dir or (DATA_DIR / "register")
    people_csv, names_csv = download(out_dir, force=force)
    return load(people_csv, names_csv, db_path=db_path)
