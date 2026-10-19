"""One name per ground.

Cricsheet spells a ground several ways — with or without the city ("Wankhede Stadium" / "Wankhede Stadium,
Mumbai"), with punctuation ("M.Chinnaswamy Stadium"), with a suburb ("MA Chidambaram Stadium, Chepauk"), under a
former name ("Feroz Shah Kotla"), or with the city missing. Every venue becomes ``"<ground>, <city>"`` (the city
keeps the eight different English "County Ground"s apart); renamed grounds take their current name; every other
spelling is kept as an alias so a search for any of them still finds the ground.

``normalize_venues(con)`` rewrites ``venue`` in every ``matches_*`` / ``balls_*`` table (the original stays in
``matches_*.venue_raw``) and rebuilds the ``venue_aliases`` table. It's idempotent and runs after every ingest.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict

import duckdb

from cricdex.common.sql import is_window

# Grounds renamed over the years → (current name, city). Keys are normalised first segments (see _key).
RENAMES: dict[str, tuple[str, str]] = {
    "feroz shah kotla": ("Arun Jaitley Stadium", "Delhi"),
    "arun jaitley stadium": ("Arun Jaitley Stadium", "Delhi"),
    "sardar patel stadium": ("Narendra Modi Stadium", "Ahmedabad"),
    "narendra modi stadium": ("Narendra Modi Stadium", "Ahmedabad"),
    "punjab cricket association stadium": (
        "Punjab Cricket Association IS Bindra Stadium",
        "Mohali",
    ),
    "punjab cricket association is bindra stadium": (
        "Punjab Cricket Association IS Bindra Stadium",
        "Mohali",
    ),
    "maharaja yadavindra singh international cricket stadium": (
        "Maharaja Yadavindra Singh International Cricket Stadium",
        "Mullanpur",
    ),
    "ma chidambaram stadium": ("MA Chidambaram Stadium", "Chennai"),
}

# City spellings → one spelling.
CITY_ALIASES: dict[str, str] = {
    "Bangalore": "Bengaluru",
    "Bombay": "Mumbai",
    "Madras": "Chennai",
    "Calcutta": "Kolkata",
}


# A ground whose city Cricsheet records two ways: (ground key, recorded city) → city to use.
GROUND_CITY: dict[tuple[str, str], str] = {
    ("county ground", "Brighton"): "Hove",
}


def _clean(s: str) -> str:
    s = re.sub(r"\.(?=\S)", ". ", s)  # "M.Chinnaswamy" → "M. Chinnaswamy"
    s = re.sub(r"\.\s", " ", s)  # then drop the dot: "M Chinnaswamy"
    return re.sub(r"\s+", " ", s).strip(" ,")


def _key(name: str) -> str:
    return _clean(name).lower()


def _parts(raw: str) -> list[str]:
    return [_clean(p) for p in raw.split(",") if _clean(p)]


def canonical_names(rows: list[tuple[str, str | None]]) -> dict[tuple[str, str | None], str]:
    """(raw venue, city) pairs → canonical "<ground>, <city>". A missing city is filled from the same ground's
    other matches, else from the raw name's second part."""
    known_city: dict[str, Counter] = defaultdict(Counter)
    for raw, city in rows:
        if raw and city:
            known_city[_key(_parts(raw)[0])][CITY_ALIASES.get(city, city)] += 1

    out: dict[tuple[str, str | None], str] = {}
    for raw, city in rows:
        if not raw:
            continue
        parts = _parts(raw)
        name, key = parts[0], _key(parts[0])
        if key in RENAMES:
            name, fixed_city = RENAMES[key]
            out[(raw, city)] = f"{name}, {fixed_city}"
            continue
        c = CITY_ALIASES.get(city, city) if city else None
        c = GROUND_CITY.get((key, c), c) if c else c
        if not c and known_city.get(key):
            c = known_city[key].most_common(1)[0][0]
        if not c and len(parts) > 1:
            c = parts[-1]
        out[(raw, city)] = f"{name}, {c}" if c and c.lower() not in name.lower() else name
    return out


def _tables(con: duckdb.DuckDBPyConnection) -> list[str]:
    """Collections with both tables (the time-window copies are rebuilt from these by the exporter)."""
    names = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
    return sorted(
        n[len("matches_") :]
        for n in names
        if n.startswith("matches_")
        and f"balls_{n[len('matches_') :]}" in names
        and not is_window(n)
    )


def normalize_venues(con: duckdb.DuckDBPyConnection) -> int:
    """Canonicalise venue names in every collection and rebuild ``venue_aliases``. Returns the number of grounds."""
    cols = _tables(con)
    for c in cols:
        have = {r[0] for r in con.execute(f"DESCRIBE matches_{c}").fetchall()}
        if "venue_raw" not in have:
            con.execute(f"ALTER TABLE matches_{c} ADD COLUMN venue_raw VARCHAR")
            con.execute(f"UPDATE matches_{c} SET venue_raw = venue")

    rows: list[tuple[str, str | None]] = []
    for c in cols:
        rows += con.execute(
            f"SELECT DISTINCT venue_raw, city FROM matches_{c} WHERE venue_raw IS NOT NULL"
        ).fetchall()
    rows = sorted(set(rows), key=lambda r: (r[0], r[1] or ""))
    mapping = canonical_names(rows)

    con.execute(
        "CREATE OR REPLACE TEMP TABLE _venue_map (venue_raw VARCHAR, city VARCHAR, venue VARCHAR)"
    )
    con.executemany(
        "INSERT INTO _venue_map VALUES (?, ?, ?)", [(r, c, v) for (r, c), v in mapping.items()]
    )
    for c in cols:
        con.execute(
            f"""UPDATE matches_{c} m SET venue = v.venue FROM _venue_map v
                WHERE v.venue_raw = m.venue_raw AND v.city IS NOT DISTINCT FROM m.city"""
        )
        con.execute(
            f"UPDATE balls_{c} b SET venue = m.venue FROM matches_{c} m WHERE m.match_id = b.match_id"
        )

    # every other name a ground has had: raw spellings, the bare ground name, former names
    aliases: dict[str, set[str]] = defaultdict(set)
    for (raw, _city), venue in mapping.items():
        aliases[venue].add(raw)
        aliases[venue].add(_parts(raw)[0])
    # (former names come in through the raw spellings, e.g. "Feroz Shah Kotla")
    con.execute("CREATE OR REPLACE TABLE venue_aliases (venue VARCHAR, alias VARCHAR)")
    pairs = sorted({(v, a) for v, names in aliases.items() for a in names if a and a != v})
    if pairs:
        con.executemany("INSERT INTO venue_aliases VALUES (?, ?)", pairs)
    return len(set(mapping.values()))


def aliases_for(con: duckdb.DuckDBPyConnection) -> dict[str, list[str]]:
    """venue → its other names (empty if the table hasn't been built)."""
    if "venue_aliases" not in {r[0] for r in con.execute("SHOW TABLES").fetchall()}:
        return {}
    out: dict[str, list[str]] = defaultdict(list)
    for v, a in con.execute(
        "SELECT venue, alias FROM venue_aliases ORDER BY venue, alias"
    ).fetchall():
        if a not in out[v]:
            out[v].append(a)
    return dict(out)
