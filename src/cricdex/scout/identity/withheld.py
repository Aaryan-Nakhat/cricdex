"""International appearances Cricsheet withholds: every men's match featuring Afghanistan.

On 14 Nov 2024 Cricsheet removed all matches featuring the Afghanistan men's team (and the
Afghanistan Premier League) from its downloads, and still withholds them (380 matches as of Oct
2026: 14 Tests, 159 ODIs, 163 T20Is; https://cricsheet.org/article/explanation-for-withholding-of-
afghanistani-matches/). Our international caps (the capped flag, `intl_caps` / `intl_caps_2y` in
the market price) are read from Cricsheet's T20I / ODI / Test XIs, so without this module Rashid
Khan, Noor Ahmad or Rahmanullah Gurbaz count as uncapped, and their opponents miss those games.

Two sourced records fill the gap, cached in `data/curated/withheld_internationals.json`:

1. **Cricsheet itself, as archived by the Wayback Machine** before the withholding: the
   `all_json.zip` snapshot of 2023-03-10 (the only full archive the Wayback Machine holds from
   before Nov 2024). Its men's international T20I / ODI / Test XIs of matches featuring Afghanistan
   are read exactly as `sources.read_international_zip` reads today's archives: both teams, real
   dates, Cricsheet identifiers (ODC-By). Covers every withheld match up to 2023-02-19.
2. **Wikipedia's Afghanistan cap lists** ("List of Afghanistan Twenty20 International / ODI /
   Test cricketers", CC BY-SA) for what came after: the full revision history from the snapshot on.
   Each row cites the player's ESPNcricinfo profile, whose id the People Register maps to a
   Cricsheet identifier. A player's count as of date t is the lowest count any revision at or after
   t shows (so a vandal's inflated number, reverted later, never counts); each increase is one
   appearance dated at the revision that published it. Revisions are made after the match, so an
   appearance is dated on or after the day it was played: counts as of an auction can lag by the
   page's editing delay, never lead it (no look-ahead). Opponents' appearances in these later
   matches are not recovered (a few games per opponent; documented in METHODOLOGY).
"""

from __future__ import annotations

import csv
import datetime as _dt
import difflib
import json
import re
import time
import zipfile
from pathlib import Path

from loguru import logger

from cricdex.config import CURATED_DIR, DATA_DIR
from cricdex.scout.identity.sources import _SORTNAME, _sortname_title

WITHHELD_TEAM = "Afghanistan"
WAYBACK_TS = "20230310104925"
WAYBACK_URL = (
    f"https://web.archive.org/web/{WAYBACK_TS}id_/https://cricsheet.org/downloads/all_json.zip"
)
WAYBACK_ZIP = DATA_DIR / "cricsheet" / "raw" / "wayback" / "all_json_20230310.zip"
WITHHELD_CACHE = CURATED_DIR / "withheld_internationals.json"
REGISTER_CSV = DATA_DIR / "register" / "people.csv"

# Cricsheet's match_type in the 2023 archive → our format key (IT20 = non-official, left out, as
# today's t20s_male archive leaves it out; MDM / ODM are not internationals)
SNAPSHOT_FORMATS = {"T20": "t20i", "ODI": "odi", "Test": "test"}

LIST_PAGES = {
    "t20i": "List of Afghanistan Twenty20 International cricketers",
    "odi": "List of Afghanistan ODI cricketers",
    "test": "List of Afghanistan Test cricketers",
}
WIKIPEDIA_API = "https://en.wikipedia.org/w/api.php"
REV_BATCH = 50  # the API's per-request limit when revision content is asked for

_CRICINFO = re.compile(
    r"espncricinfo\.com/(?:[a-z]+/)*(?:content/player/(\d+)\.html|cricketers/[^\s|/]*?-(\d+)\b)",
    re.I,
)


# ---- 1. the Wayback snapshot of Cricsheet --------------------------------------------------------


def read_snapshot(zip_path: Path = WAYBACK_ZIP) -> tuple[list[tuple[str, str, str, str]], str]:
    """(identifier, team, date, format) for both XIs of every men's T20I / ODI / Test featuring
    Afghanistan in the archived Cricsheet `all_json.zip`, and the snapshot's last such date."""
    rows: list[tuple[str, str, str, str]] = []
    last = ""
    with zipfile.ZipFile(zip_path) as zf:
        for member in zf.namelist():
            if not member.endswith(".json"):
                continue
            info = json.loads(zf.read(member)).get("info", {})
            if info.get("gender", "male") != "male" or WITHHELD_TEAM not in (
                info.get("teams") or []
            ):
                continue
            fmt = SNAPSHOT_FORMATS.get(info.get("match_type") or "")
            if fmt is None or info.get("team_type") != "international":
                continue
            dates = info.get("dates") or []
            if not dates:
                continue
            d = str(dates[0])[:10]
            last = max(last, d)
            reg = (info.get("registry") or {}).get("people") or {}
            for team, names in (info.get("players") or {}).items():
                for nm in names:
                    if reg.get(nm):
                        rows.append((reg[nm], team, d, fmt))
    return rows, last


def download_snapshot(force: bool = False) -> Path:
    import httpx

    if WAYBACK_ZIP.exists() and not force:
        return WAYBACK_ZIP
    WAYBACK_ZIP.parent.mkdir(parents=True, exist_ok=True)
    logger.info(f"withheld: downloading {WAYBACK_URL}")
    with httpx.stream("GET", WAYBACK_URL, timeout=600.0, follow_redirects=True) as r:
        r.raise_for_status()
        with WAYBACK_ZIP.open("wb") as f:
            for chunk in r.iter_bytes():
                f.write(chunk)
    return WAYBACK_ZIP


# ---- 2. Wikipedia's cap lists, revision by revision ----------------------------------------------


def parse_list_counts(text: str) -> dict[str, tuple[int, str]]:
    """{cricinfo id: (matches, name)} from a cap-list wikitable. A row is `! scope="row" | name`
    followed by `| first || last || Mat || ...` and a reference to the ESPNcricinfo profile."""
    out: dict[str, tuple[int, str]] = {}
    for block in re.split(r"\n\|-", text):
        m = re.search(r'!\s*scope\s*=\s*"?row"?\s*\|(.*)', block)
        if not m:
            continue
        ids = _CRICINFO.search(block)
        if not ids:
            continue
        cid = ids.group(1) or ids.group(2)
        after = block[m.end() :]
        cells = None
        for line in after.split("\n"):
            s = line.strip()
            if s.startswith("|") and "||" in s:
                cells = [c.strip() for c in s.lstrip("|").split("||")]
                break
        if not cells or len(cells) < 3:
            continue
        mat = re.sub(r"\{\{sort\|[^|}]*\|([^}]*)\}\}", r"\1", cells[2])
        mat = re.sub(r"<[^>]+>", "", mat).replace(",", "").strip()
        if not mat.isdigit():
            continue
        name = _SORTNAME.sub(lambda x: _sortname_title(x.group(1))[0], m.group(1))
        name = re.sub(r"\{\{#tag:ref\|.*", "", name)
        name = re.sub(r"\[\[(?:[^\]|]*\|)?([^\]]*)\]\]", r"\1", name)
        name = re.sub(r"\{\{[^}]*\}\}|&nbsp;|'''|''", "", name).strip()
        out[cid] = (int(mat), name)
    return out


def fetch_revisions(title: str, since: str) -> list[tuple[str, str]]:
    """[(timestamp, wikitext)] of every revision of `title` from `since` (ISO date) on, oldest
    first, plus the last revision before `since` (the baseline)."""
    from cricdex.scout.identity.sources import _client, _get_with_retry

    out: list[tuple[str, str]] = []
    with _client() as cx:
        base = _get_with_retry(
            cx,
            WIKIPEDIA_API,
            {
                "action": "query",
                "prop": "revisions",
                "titles": title,
                "rvlimit": 1,
                "rvprop": "timestamp|content",
                "rvslots": "main",
                "rvdir": "older",
                "rvstart": f"{since}T00:00:00Z",
                "format": "json",
                "formatversion": 2,
            },
            f"withheld {title} baseline",
        ).json()["query"]["pages"][0]
        for rv in base.get("revisions", []):
            out.append((rv["timestamp"], rv["slots"]["main"].get("content", "")))
        params = {
            "action": "query",
            "prop": "revisions",
            "titles": title,
            "rvlimit": REV_BATCH,
            "rvprop": "timestamp|content",
            "rvslots": "main",
            "rvdir": "newer",
            "rvstart": f"{since}T00:00:00Z",
            "format": "json",
            "formatversion": 2,
        }
        while True:
            js = _get_with_retry(cx, WIKIPEDIA_API, params, f"withheld {title}").json()
            for rv in js["query"]["pages"][0].get("revisions", []):
                out.append((rv["timestamp"], rv["slots"]["main"].get("content", "")))
            if "continue" not in js:
                break
            params.update(js["continue"])
            time.sleep(1.0)
    logger.info(f"withheld: {title}: {len(out)} revisions since {since} (+ baseline)")
    return out


def appearances_from_revisions(
    revs: list[tuple[str, dict[str, tuple[int, str]]]], after: str
) -> dict[str, list[str]]:
    """{cricinfo id: [dates]} of the appearances the revisions add after date `after`.

    The count as of revision i is min over revisions j ≥ i (a lower envelope, so a transient
    inflation that is later reverted never counts). A revision whose table lost over half the
    players of the one before (a blanking or a parse failure) is skipped, and a player missing
    from a revision (a broken row) leaves his count unknown there rather than zero."""
    good: list[tuple[str, dict[str, int]]] = []
    prev_n = 0
    for ts, counts in revs:
        n = len(counts)
        if prev_n and n < 0.5 * prev_n:
            continue
        good.append((ts[:10], {k: v[0] for k, v in counts.items()}))
        prev_n = max(prev_n, n)
    if not good:
        return {}
    ids = set().union(*(c.keys() for _, c in good))
    # lower envelope, scanned from the newest revision back
    env: list[dict[str, int]] = [{} for _ in good]
    run: dict[str, int] = {}
    for i in range(len(good) - 1, -1, -1):
        c = good[i][1]
        for k in ids:
            if k in c:
                run[k] = min(run[k], c[k]) if k in run else c[k]
        env[i] = dict(run)
    # the baseline: the last revision dated on or before `after` (else zero)
    base: dict[str, int] = {}
    start = 0
    for i, (d, _c) in enumerate(good):
        if d <= after:
            base, start = env[i], i + 1
    out: dict[str, list[str]] = {}
    cur = dict(base)
    for i in range(start, len(good)):
        d = good[i][0]
        for k, v in env[i].items():
            add = v - cur.get(k, 0)
            if add > 0:
                out.setdefault(k, []).extend([d] * add)
                cur[k] = v
    return out


def cricinfo_to_cricsheet(path: Path = REGISTER_CSV) -> dict[str, str]:
    out: dict[str, str] = {}
    with path.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            for k in ("key_cricinfo", "key_cricinfo_2", "key_cricinfo_3"):
                v = (row.get(k) or "").strip().removesuffix(".0")
                if v:
                    out.setdefault(v, row["identifier"])
    return out


def _norm(name: str) -> str:
    return " ".join(re.sub(r"[^a-z ]", " ", name.lower().replace("-", " ")).split())


def register_names(path: Path = REGISTER_CSV) -> dict[str, set[str]]:
    """identifier → normalised names (register name, unique name without its "(2)", variants)."""
    out: dict[str, set[str]] = {}
    with path.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            out.setdefault(row["identifier"], set()).update(
                {_norm(row["name"]), _norm(re.sub(r"\(\d+\)", "", row["unique_name"] or ""))}
            )
    pn = path.with_name("people_names.csv")
    if pn.exists():
        with pn.open(encoding="utf-8") as f:
            for row in csv.DictReader(f):
                out.setdefault(row["identifier"], set()).add(_norm(row["name"]))
    return out


def _same_person(list_name: str, names: set[str]) -> bool:
    """The cap list's name agrees with a register identity: equal, or sharing the surname-like
    last token and the first token (Wikipedia lists sometimes cite another player's profile, e.g.
    the T20I row of Rashid Khan citing Farid Malik's, so the cited id is checked by name)."""
    a = _norm(list_name).split()
    if not a:
        return False
    for n in names:
        b = n.split()
        if not b:
            continue
        if a == b or (a[-1] == b[-1] and (a[0] == b[0] or a[0][0] == b[0][0])):
            return True
        if set(a) <= set(b) or set(b) <= set(a):
            return True
        if len(a) == len(b) and difflib.SequenceMatcher(None, " ".join(a), n).ratio() >= 0.9:
            return True  # a spelling slip on the list ("Shaidi" for "Shahidi")
    return False


def resolver(snapshot_afg: set[str]):
    """(cricinfo id, list name) → Cricsheet identifier or None. The cited profile's id wins when
    its register name agrees; otherwise the name is looked up among Afghanistan's players (the
    snapshot's XIs) and must match exactly one."""
    to_cs = cricinfo_to_cricsheet()
    names = register_names()
    by_name: dict[str, set[str]] = {}
    for pid in snapshot_afg:
        for n in names.get(pid, ()):
            by_name.setdefault(n, set()).add(pid)

    everyone: dict[str, set[str]] = {}
    for pid, ns in names.items():
        for n in ns:
            everyone.setdefault(n, set()).add(pid)

    def resolve(ci: str, list_name: str) -> str | None:
        pid = to_cs.get(ci)
        if pid and (
            _same_person(list_name, names.get(pid, set()))
            # the cited id is evidence too: a transliteration ("Nangialai Kharoti" for the
            # register's "Nangeyalia Kharote") is accepted when the id agrees
            or max(
                (difflib.SequenceMatcher(None, _norm(list_name), n).ratio() for n in names[pid]),
                default=0.0,
            )
            >= 0.7
        ):
            return pid
        hits = by_name.get(_norm(list_name), set())
        if len(hits) == 1:
            return next(iter(hits))
        cand = [p for p in snapshot_afg if _same_person(list_name, names.get(p, set()))]
        if len(cand) == 1:
            return cand[0]
        # a debut after the snapshot whose row cites someone else's profile: a unique exact name
        # anywhere in the register
        hits = everyone.get(_norm(list_name), set())
        return next(iter(hits)) if len(hits) == 1 else None

    return resolve


def resolve_revisions(
    revs: list[tuple[str, str]], resolve
) -> tuple[list[tuple[str, dict[str, tuple[int, str]]]], dict[str, str]]:
    """Parse each revision and key its counts by Cricsheet identifier (unresolved rows → returned
    as {cricinfo id: name})."""
    parsed: list[tuple[str, dict[str, tuple[int, str]]]] = []
    unmapped: dict[str, str] = {}
    for ts, txt in revs:
        by_pid: dict[str, tuple[int, str]] = {}
        for ci, (mat, nm) in parse_list_counts(txt).items():
            pid = resolve(ci, nm)
            if pid is None:
                unmapped[ci] = nm
                continue
            by_pid[pid] = (mat, nm)
        parsed.append((ts, by_pid))
    return parsed, unmapped


# ---- build / load --------------------------------------------------------------------------------


def build(force: bool = False) -> dict:
    """Fetch both records and write the cache. Returns the cache dict."""
    zp = download_snapshot(force=force)
    snap_rows, snap_last = read_snapshot(zp)
    logger.info(f"withheld: snapshot {len(snap_rows)} player-matches up to {snap_last}")
    resolve = resolver({pid for pid, team, _d, _f in snap_rows if team == WITHHELD_TEAM})
    appear: list[list[str]] = [
        [pid, team, d, fmt, SNAPSHOT_SOURCE] for pid, team, d, fmt in snap_rows
    ]
    unmapped: dict[str, str] = {}
    pages: dict[str, dict] = {}
    for fmt, title in LIST_PAGES.items():
        revs = fetch_revisions(title, snap_last)
        parsed, miss = resolve_revisions(revs, resolve)
        unmapped.update(miss)
        got = appearances_from_revisions(parsed, snap_last)
        n = 0
        for pid, ds in got.items():
            for d in ds:
                appear.append([pid, WITHHELD_TEAM, d, fmt, LIST_SOURCE])
                n += 1
        pages[fmt] = {
            "title": title,
            "revisions": len(revs),
            "last_revision": revs[-1][0] if revs else None,
            "appearances_added": n,
        }
    out = {
        "_source": (
            "Matches Cricsheet withholds (featuring Afghanistan): Cricsheet all_json.zip as archived "
            f"by the Wayback Machine ({WAYBACK_TS}, ODC-By) up to {snap_last}; after it, the "
            "revision history of Wikipedia's Afghanistan T20I / ODI / Test cap lists (CC BY-SA), "
            "each increase dated at the revision that published it."
        ),
        "_built": _dt.date.today().isoformat(),
        "_snapshot_last_match": snap_last,
        "_pages": pages,
        "_unmapped_cricinfo_ids": unmapped,
        "appearances": sorted(appear, key=lambda r: (r[2], r[0])),
    }
    CURATED_DIR.mkdir(parents=True, exist_ok=True)
    WITHHELD_CACHE.write_text(
        json.dumps(out, indent=0, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    logger.info(
        f"withheld: {len(appear)} appearances cached ({len(unmapped)} unmapped cricinfo ids)"
    )
    return out


SNAPSHOT_SOURCE = "cricsheet_wayback"
LIST_SOURCE = "wikipedia_list"


def load_rows(with_source: bool = False) -> list[tuple]:
    """(identifier, team, date, format[, source]) rows from the cache ([] when it hasn't been
    built). `source` is SNAPSHOT_SOURCE (a real match date) or LIST_SOURCE (the date of the
    Wikipedia revision that published the appearance)."""
    if not WITHHELD_CACHE.exists():
        logger.warning(
            "withheld internationals cache missing: Afghanistan caps are not counted "
            "(run `python -m cricdex.scout.identity.withheld`)"
        )
        return []
    js = json.loads(WITHHELD_CACHE.read_text(encoding="utf-8"))
    if with_source:
        return [(r[0], r[1], r[2], r[3], r[4]) for r in js.get("appearances", [])]
    return [(r[0], r[1], r[2], r[3]) for r in js.get("appearances", [])]


if __name__ == "__main__":
    import sys

    build(force="--force" in sys.argv)
