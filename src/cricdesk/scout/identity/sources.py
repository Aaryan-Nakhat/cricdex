"""Open-data sources for the player master, each fetched in polite batches and cached on disk.

- **Wikidata** (CC0) — one SPARQL query per chunk of ESPNcricinfo ids (property P2697, the id the
  People Register carries as `key_cricinfo`): English label and aliases, date of birth, birth name,
  country for sport / citizenship, playing position and hand, and the English Wikipedia article.
- **Wikipedia** (CC BY-SA) — the `{{Infobox cricketer}}` of each player's article (section 0 only,
  50 articles per request): full name, batting hand, bowling style, role, date of birth. Only the
  parsed facts are cached, never the article text.
- **Wikipedia, IPL personnel page** (CC BY-SA) — the 2026 retained / sold / replacement lists and
  the retirements, from "List of 2026 Indian Premier League personnel changes".
- **Cricsheet** (ODC-By) — men's ODI and Test archives, read only for `info.players` / registry /
  dates to decide who is capped. Never ingested, never exported. Cricsheet withholds every match
  featuring Afghanistan (since Nov 2024); those appearances come from `withheld.py` (an archived
  Cricsheet snapshot + Wikipedia's Afghanistan cap lists).

Every fetcher is resumable: it skips what its cache already holds unless `force=True`.
"""

from __future__ import annotations

import datetime as _dt
import json
import re
import time
import zipfile
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import httpx
from loguru import logger

from cricdesk.config import CURATED_DIR, DATA_DIR

USER_AGENT = (
    "cricdesk-player-master/0.2 (https://github.com/Aaryan-Nakhat/cricdesk; "
    "open cricket analytics; batch identity lookups, cached)"
)
SPARQL_ENDPOINT = "https://query.wikidata.org/sparql"
WIKIPEDIA_API = "https://en.wikipedia.org/w/api.php"

WIKIDATA_CACHE = CURATED_DIR / "wikidata_players.json"
INFOBOX_CACHE = CURATED_DIR / "wikipedia_infobox.json"
CAPS_CACHE = CURATED_DIR / "international_caps.json"
IPL_SQUADS = CURATED_DIR / "ipl_squads_2026.json"

SPARQL_CHUNK = 200  # ids per query: a few hundred rows back, well under WDQS limits
SPARQL_SLEEP_S = 0.5  # between queries (one per field per chunk)
WIKI_CHUNK = 50  # the MediaWiki API's per-request title limit
WIKI_SLEEP_S = 1.0

IPL_PERSONNEL_PAGE = "List of 2026 Indian Premier League personnel changes"
IPL_SEASON = 2026
# the next cycle's page: trades and retirements since the 2026 season (applied to the squads file)
IPL_NEXT_PERSONNEL_PAGE = "List of 2027 Indian Premier League personnel changes"


# ---- small helpers ------------------------------------------------------------------------------


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(obj, indent=1, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def _chunks(xs: list, n: int) -> Iterable[list]:
    for i in range(0, len(xs), n):
        yield xs[i : i + n]


def _client() -> httpx.Client:
    return httpx.Client(timeout=120.0, headers={"User-Agent": USER_AGENT}, follow_redirects=True)


def _get_with_retry(cx: httpx.Client, url: str, params: dict, what: str) -> httpx.Response:
    """GET with backoff on 429 / 5xx / timeouts (WDQS and the MediaWiki API both throttle)."""
    for attempt in range(6):
        try:
            r = cx.get(url, params=params)
        except httpx.HTTPError as e:
            wait = 5 * (attempt + 1)
            logger.warning(f"{what}: {e!r}; retry in {wait}s")
            time.sleep(wait)
            continue
        if r.status_code == 200:
            return r
        if r.status_code in (429, 500, 502, 503, 504):
            wait = int(r.headers.get("retry-after") or 10 * (attempt + 1))
            logger.warning(f"{what}: HTTP {r.status_code}; retry in {wait}s")
            time.sleep(wait)
            continue
        r.raise_for_status()
    raise RuntimeError(f"{what}: gave up after retries")


# ---- Wikidata ------------------------------------------------------------------------------------

# One small query per field: WDQS times a single UNION-of-everything query out, while each of
# these answers a chunk of a few hundred ids in about a second.
_FIELD_QUERIES = {
    "qid": 'BIND(STRAFTER(STR(?item), "entity/") AS ?v)',
    "label": '?item rdfs:label ?v FILTER(LANG(?v) = "en")',
    "alias": '?item skos:altLabel ?v FILTER(LANG(?v) = "en")',
    # every non-deprecated birth date with its precision ("time|precision"): `wdt:` drops the
    # precision, so a year-only date (precision 9, stored as 1 January) read as a full date
    "dob": "?item p:P569 ?st . ?st psv:P569 ?n . ?n wikibase:timeValue ?t ; "
    "wikibase:timePrecision ?pr . ?st wikibase:rank ?rk "
    "FILTER(?rk != wikibase:DeprecatedRank) "
    'BIND(CONCAT(STR(?t), "|", STR(?pr)) AS ?v)',
    "birth_name": "?item wdt:P1477 ?v",
    "sport_country": '?item wdt:P1532 ?c . ?c rdfs:label ?v FILTER(LANG(?v) = "en")',
    "citizenship_iso": "?item wdt:P27 ?c . ?c wdt:P298 ?v",
    "position": '?item wdt:P413 ?x . ?x rdfs:label ?v FILTER(LANG(?v) = "en")',
    "hand": '?item wdt:P741 ?x . ?x rdfs:label ?v FILTER(LANG(?v) = "en")',
    "enwiki": "?a schema:about ?item ; schema:isPartOf <https://en.wikipedia.org/> ; schema:name ?v",
}


def _field_query(key: str, ids: list[str]) -> str:
    values = " ".join(f'"{i}"' for i in ids)
    return (
        f'SELECT ?id ?v (STR("{key}") AS ?k) WHERE {{ VALUES ?id {{ {values} }} '
        f"?item wdt:P2697 ?id . {_FIELD_QUERIES[key]} }}"
    )


_MULTI = {"alias", "sport_country", "citizenship_iso", "position", "hand"}

DOB_SCHEMA = 2  # birth dates carry their precision (`_dob_v`); a record without it is re-queried
DAY_PRECISION = 11  # Wikidata time precision: 9 = year, 10 = month, 11 = day


def _fold_dob(rec: dict, v: str) -> None:
    """One P569 binding ("+1996-07-06T00:00:00Z|11") into `rec`: day-precision dates go to
    `dob_all`; `dob` is set only when exactly one distinct day-precision date is listed (two
    different ones are a conflict, `dob_conflict`, settled by the other sources). A year- or
    month-only date is kept as `dob_year` and never used as a birth date. An old cache row (no
    precision) folds as before."""
    t, _, pr = v.partition("|")
    d = t.lstrip("+")[:10]
    rec["_dob_v"] = DOB_SCHEMA
    if pr and int(pr) < DAY_PRECISION:
        rec.setdefault("dob_year", d[:4])
        return
    vals = rec.setdefault("dob_all", [])
    if d not in vals:
        vals.append(d)
    vals.sort()
    if len(vals) == 1:
        rec["dob"] = vals[0]
    else:
        rec.pop("dob", None)
        rec["dob_conflict"] = True


def _fold_bindings(bindings: list[dict]) -> dict[str, dict]:
    """SPARQL rows (id, key, value) → {cricinfo_id: {key: value | [values]}}."""
    out: dict[str, dict] = {}
    for b in bindings:
        cid = b["id"]["value"]
        k = b["k"]["value"]
        v = b["v"]["value"]
        rec = out.setdefault(cid, {})
        if k in _MULTI:
            vals = rec.setdefault(k, [])
            if v not in vals:
                vals.append(v)
        elif k == "dob":
            _fold_dob(rec, v)
        elif k == "qid" and "qid" in rec and rec["qid"] != v:
            # two items claim the same cricinfo id (a duplicate on Wikidata): keep both, flag it
            rec.setdefault("qid_conflict", [rec["qid"]]).append(v)
        else:
            rec.setdefault(k, v)
    return out


def fetch_wikidata(players: dict[str, list[str]], force: bool = False) -> dict[str, dict]:
    """`players` = {cricsheet_id: [cricinfo ids]}. Returns (and caches) {cricsheet_id: record}.

    A player is looked up by every cricinfo id the register carries for him; the first id that
    resolves wins. Players with no Wikidata item are cached as `{"_status": "not_found"}` so a rerun
    doesn't ask again (pass `force` to retry everything)."""
    cache: dict[str, dict] = read_json(WIKIDATA_CACHE, {})
    todo = {cid: ids for cid, ids in players.items() if ids and (force or cid not in cache)}
    by_cricinfo: dict[str, str] = {}
    for cid, ids in todo.items():
        for i in ids:
            by_cricinfo.setdefault(str(i), cid)
    logger.info(
        f"wikidata: {len(players)} players, {len(cache)} cached, {len(todo)} to fetch "
        f"({len(by_cricinfo)} cricinfo ids)"
    )
    keys = sorted(by_cricinfo)
    fetched_at = _dt.date.today().isoformat()
    with _client() as cx:
        for n, chunk in enumerate(_chunks(keys, SPARQL_CHUNK), 1):
            bindings: list[dict] = []
            for key in _FIELD_QUERIES:
                r = _get_with_retry(
                    cx,
                    SPARQL_ENDPOINT,
                    {"query": _field_query(key, chunk), "format": "json"},
                    f"wikidata chunk {n} {key}",
                )
                bindings += r.json()["results"]["bindings"]
                time.sleep(SPARQL_SLEEP_S)
            got = _fold_bindings(bindings)
            for ci, rec in got.items():
                cid = by_cricinfo[ci]
                prev = cache.get(cid, {})
                if prev.get("_status") == "ok" and prev.get("_fetched") == fetched_at:
                    continue  # a second cricinfo id of a player already resolved in this run
                cache[cid] = {"_status": "ok", "_fetched": fetched_at, "cricinfo_id": ci, **rec}
            if n % 10 == 0:
                write_json(WIKIDATA_CACHE, cache)
                logger.info(f"  wikidata chunk {n}/{(len(keys) - 1) // SPARQL_CHUNK + 1}")
    for cid in todo:
        if cache.get(cid, {}).get("_fetched") != fetched_at:
            cache[cid] = {"_status": "not_found", "_fetched": fetched_at}
    write_json(WIKIDATA_CACHE, cache)
    ok = sum(1 for v in cache.values() if v.get("_status") == "ok")
    logger.info(f"wikidata: cache {len(cache)} players, {ok} resolved")
    return refresh_wikidata_dob(cache)


_DOB_KEYS = ("dob", "dob_all", "dob_year", "dob_conflict", "_dob_v")


def refresh_wikidata_dob(cache: dict[str, dict] | None = None, force: bool = False) -> dict:
    """Re-query the birth dates (with their precision, `_fold_dob`) of every resolved record cached
    before DOB_SCHEMA (or all of them with `force`), by its cricinfo id. Until 2026-10-26 the date
    was read without its precision, so a year-only Wikidata date became 1 January of that year."""
    cache = read_json(WIKIDATA_CACHE, {}) if cache is None else cache
    todo = {str(r["cricinfo_id"]): cid for cid, r in cache.items()
            if r.get("_status") == "ok" and r.get("cricinfo_id")
            and (force or r.get("_dob_v") != DOB_SCHEMA)}  # fmt: skip
    if not todo:
        return cache
    logger.info(f"wikidata: refreshing {len(todo)} birth dates with their precision")
    keys = sorted(todo)
    with _client() as cx:
        for n, chunk in enumerate(_chunks(keys, SPARQL_CHUNK), 1):
            r = _get_with_retry(cx, SPARQL_ENDPOINT,
                                {"query": _field_query("dob", chunk), "format": "json"},
                                f"wikidata dob chunk {n}")  # fmt: skip
            got = _fold_bindings(r.json()["results"]["bindings"])
            for ci in chunk:
                rec = cache[todo[ci]]
                for k in _DOB_KEYS:
                    rec.pop(k, None)
                rec.update({k: v for k, v in (got.get(ci) or {}).items() if k in _DOB_KEYS})
                rec["_dob_v"] = DOB_SCHEMA
            time.sleep(SPARQL_SLEEP_S)
    write_json(WIKIDATA_CACHE, cache)
    return cache


# ---- Wikipedia infobox ---------------------------------------------------------------------------

_REF = re.compile(r"<ref[^>/]*/>|<ref[^>]*>.*?</ref>", re.S | re.I)
_COMMENT = re.compile(r"<!--.*?-->", re.S)
_LINK = re.compile(r"\[\[(?:[^\]|]*\|)?([^\]]*)\]\]")
_TAG = re.compile(r"<[^>]+>")


def _strip_markup(v: str) -> str:
    v = _COMMENT.sub("", _REF.sub("", v))
    v = re.sub(r"<br\s*/?>", "; ", v, flags=re.I)
    # simple wrapper templates keep their text: {{nowrap|x}}, {{nobr|x}}, {{small|x}}
    for _ in range(3):
        v = re.sub(
            r"\{\{(?:nowrap|nobr|small|nbsp|ubl|plainlist|flatlist)\|([^{}]*)\}\}",
            r"\1",
            v,
            flags=re.I,
        )
    v = re.sub(r"\{\{[^{}]*\}\}", "", v)
    v = _LINK.sub(r"\1", v)
    v = _TAG.sub("", v).replace("'''", "").replace("''", "")
    return re.sub(r"\s+", " ", v).strip(" ;,")


def _infobox_fields(text: str) -> dict[str, str]:
    """`| key = value` pairs of the first {{Infobox cricketer}} (raw values, markup kept)."""
    m = re.search(r"\{\{\s*Infobox cricketer", text, re.I)
    if not m:
        return {}
    # walk to the matching close of the infobox template
    depth, i, start = 0, m.start(), m.start()
    while i < len(text):
        if text.startswith("{{", i):
            depth += 1
            i += 2
            continue
        if text.startswith("}}", i):
            depth -= 1
            i += 2
            if depth == 0:
                break
            continue
        i += 1
    body = text[start:i]
    fields: dict[str, str] = {}
    # split on top-level pipes that start a "key =" line
    for part in re.split(r"\n\s*\|", body):
        if "=" not in part:
            continue
        k, _, v = part.partition("=")
        k = k.strip().lower().replace(" ", "_")
        if k and re.fullmatch(r"[a-z_0-9]+", k):
            fields[k] = v.strip()
    return fields


def _birth_date(raw: str | None) -> str | None:
    if not raw:
        return None
    m = re.search(r"\{\{\s*(?:birth date(?: and age)?|bda|dob)\s*\|([^}]*)\}\}", raw, re.I)
    if m:
        nums = [p.strip() for p in m.group(1).split("|") if p.strip() and "=" not in p]
        if len(nums) >= 3 and all(x.isdigit() for x in nums[:3]):
            y, mo, d = (int(x) for x in nums[:3])
            try:
                return _dt.date(y, mo, d).isoformat()
            except ValueError:
                return None
    return None


def parse_infobox(text: str) -> dict[str, Any] | None:
    """The facts CricDesk keeps from an article's infobox (None when it has none)."""
    f = _infobox_fields(text)
    if not f:
        return None
    out: dict[str, Any] = {}
    for key, src in (
        ("full_name", ("full_name", "fullname", "birth_name")),
        ("batting", ("batting",)),
        ("bowling", ("bowling",)),
        ("role", ("role",)),
        ("country", ("country",)),
        ("name", ("name",)),
    ):
        for s in src:
            if f.get(s):
                val = _strip_markup(f[s])
                if val:
                    out[key] = val
                    break
    dob = _birth_date(f.get("birth_date"))
    if dob:
        out["dob"] = dob
    return out


def fetch_infoboxes(titles: dict[str, str], force: bool = False) -> dict[str, dict]:
    """`titles` = {cricsheet_id: enwiki article title}. Returns (and caches) {cricsheet_id: facts}."""
    cache: dict[str, dict] = read_json(INFOBOX_CACHE, {})
    todo = {
        cid: t
        for cid, t in titles.items()
        if force or cid not in cache or cache[cid].get("_title") != t
    }
    logger.info(f"wikipedia: {len(titles)} articles, {len(cache)} cached, {len(todo)} to fetch")
    by_title: dict[str, list[str]] = {}
    for cid, t in todo.items():
        by_title.setdefault(t, []).append(cid)
    keys = sorted(by_title)
    with _client() as cx:
        for n, chunk in enumerate(_chunks(keys, WIKI_CHUNK), 1):
            r = _get_with_retry(
                cx,
                WIKIPEDIA_API,
                {
                    "action": "query",
                    "prop": "revisions",
                    "rvprop": "content",
                    "rvslots": "main",
                    "rvsection": "0",
                    "redirects": "1",
                    "format": "json",
                    "formatversion": "2",
                    "titles": "|".join(chunk),
                },
                f"wikipedia chunk {n}",
            )
            data = r.json().get("query", {})
            alias: dict[str, str] = {}
            for m in data.get("normalized", []) + data.get("redirects", []):
                alias[m["to"]] = m["from"]
            for page in data.get("pages", []):
                title = page.get("title", "")
                orig = title
                while orig in alias and orig not in by_title:
                    orig = alias[orig]
                cids = by_title.get(orig) or by_title.get(title) or []
                revs = page.get("revisions") or []
                text = revs[0]["slots"]["main"].get("content", "") if revs else ""
                facts = parse_infobox(text) if text else None
                for cid in cids:
                    cache[cid] = {
                        "_title": orig,
                        "_page": title,
                        **(facts or {"_status": "no_infobox"}),
                    }
            for t in chunk:
                for cid in by_title[t]:
                    cache.setdefault(cid, {"_title": t, "_status": "missing"})
            if n % 10 == 0:
                write_json(INFOBOX_CACHE, cache)
                logger.info(f"  wikipedia chunk {n}/{(len(keys) - 1) // WIKI_CHUNK + 1}")
            time.sleep(WIKI_SLEEP_S)
    write_json(INFOBOX_CACHE, cache)
    return cache


# ---- bowling style / role / hand text → CricDesk vocabulary ---------------------------------------

STYLE_CATEGORY = {
    "right-arm-fast": "seam",
    "right-arm-fast-medium": "seam",
    "right-arm-medium": "seam",
    "left-arm-fast": "seam",
    "left-arm-medium": "seam",
    "off-spin": "spin",
    "leg-spin": "spin",
    "left-arm-orthodox": "spin",
    "left-arm-wrist-spin": "spin",
}
STYLE_ARM = {
    "right-arm-fast": "right",
    "right-arm-fast-medium": "right",
    "right-arm-medium": "right",
    "off-spin": "right",
    "leg-spin": "right",
    "left-arm-fast": "left",
    "left-arm-medium": "left",
    "left-arm-orthodox": "left",
    "left-arm-wrist-spin": "left",
}


def parse_bowling_style(text: str | None) -> str | None:
    """Infobox / free-text bowling style ("Right-arm medium-fast", "Slow left-arm orthodox",
    "Leg break googly") → one CricDesk style key, from the first style listed. None if unparseable."""
    if not text:
        return None
    t = text.lower().replace("–", "-").replace("_", " ")
    t = re.split(r";|/|\||\bor\b|,|\band\b", t)[0].strip()
    if not t or t in {"none", "-", "n/a"}:
        return None
    left = "left" in t
    if "wrist" in t or "chinaman" in t or "unorthodox" in t:
        return "left-arm-wrist-spin"
    if "orthodox" in t or ("slow" in t and left and "medium" not in t):
        return "left-arm-orthodox"
    if "leg" in t and ("break" in t or "spin" in t) or "googly" in t:
        return "left-arm-wrist-spin" if left else "leg-spin"
    if "off" in t and ("break" in t or "spin" in t):
        return "off-spin"
    if "fast" in t or "medium" in t or "pace" in t or "seam" in t:
        if left:
            return (
                "left-arm-medium"
                if ("medium" in t and "fast" not in t) or "slow" in t
                else "left-arm-fast"
            )
        if "slow" in t and "medium" in t:
            return "right-arm-medium"
        if "fast" in t and "medium" in t:
            return "right-arm-fast-medium"
        if "fast" in t:
            return "right-arm-fast"
        return "right-arm-medium"
    return None


def parse_batting_hand(text: str | None) -> str | None:
    if not text:
        return None
    t = text.lower()
    if t.startswith("left") or "left-hand" in t or "left hand" in t:
        return "left"
    if t.startswith("right") or "right-hand" in t or "right hand" in t:
        return "right"
    return None


# "Batsman, Occasionally Wicket Keeper" / "Batter, Occasional wicket-keeper" / "part-time keeper":
# a batter who has kept now and then is not a keeper (Ruturaj Gaikwad's infobox made CSK look
# like it had five keepers)
_PART_KEEPER = re.compile(
    r"\b(?:occasional(?:ly)?|part[- ]?time|sometimes)\s+(?:wicket[- ]?)?keep\w*(?:[- ]bat\w*)?",
    re.I,
)


def parse_role(text: str | None) -> str | None:
    if not text:
        return None
    t = _PART_KEEPER.sub("", text.lower())
    if "keep" in t:
        return "wk_batter"
    if "all" in t and "round" in t:
        return "allrounder"
    if "bowl" in t:
        return "bowler"
    if "bat" in t or "opening" in t:
        return "batter"
    return None


# ---- Cricsheet internationals (capped) ----------------------------------------------------------

INTL_ZIPS = {"odi": "odis_male_json.zip", "test": "tests_male_json.zip"}


def read_international_zip(zip_path: Path, fmt: str) -> list[tuple[str, str, str, str]]:
    """(identifier, team, date, format) for every player in every XI of a Cricsheet archive.

    Reads only `info.players` (team → names), `info.registry.people` (name → id) and `info.dates`;
    officials appear in the registry but not in `info.players`, so they are never counted."""
    rows: list[tuple[str, str, str, str]] = []
    with zipfile.ZipFile(zip_path) as zf:
        for member in zf.namelist():
            if not member.endswith(".json"):
                continue
            info = json.loads(zf.read(member)).get("info", {})
            if info.get("gender", "male") != "male":
                continue
            reg = (info.get("registry") or {}).get("people") or {}
            dates = info.get("dates") or []
            d = str(dates[0])[:10] if dates else None
            if not d:
                continue
            for team, names in (info.get("players") or {}).items():
                for nm in names:
                    pid = reg.get(nm)
                    if pid:
                        rows.append((pid, team, d, fmt))
    return rows


def build_caps(
    con, wanted: set[str], raw_dir: Path | None = None, force: bool = False
) -> dict[str, dict]:
    """{cricsheet_id: {first, last, formats: {t20i|odi|test: matches}, team}} for every `wanted`
    player who played a men's international, from Cricsheet: T20Is from the ingested `t20s_male`
    collection (read-only), ODIs and Tests from their archives (downloaded, read, never ingested)."""
    from cricdesk.scout.ingest.cricsheet import download_zip

    raw_dir = raw_dir or (DATA_DIR / "cricsheet" / "raw")
    rows: list[tuple[str, str, str, str]] = []
    tables = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
    if "match_players_t20s_male" in tables and "matches_t20s_male" in tables:
        rows += [
            (r[0], r[1], str(r[2])[:10], "t20i")
            for r in con.execute(
                "SELECT p.identifier, p.team, m.match_date FROM match_players_t20s_male p "
                "JOIN matches_t20s_male m USING (match_id) WHERE p.identifier IS NOT NULL"
            ).fetchall()
        ]
    else:
        logger.warning("caps: t20s_male isn't ingested — T20I caps are missing")
    for fmt, z in INTL_ZIPS.items():
        path = download_zip(z, raw_dir, force=force)
        got = read_international_zip(path, fmt)
        logger.info(f"caps: {fmt} — {len(got)} player-matches from {path.name}")
        rows += got
    # matches Cricsheet withholds (featuring Afghanistan): identity/withheld.py
    from cricdesk.scout.identity import withheld

    got = withheld.load_rows()
    logger.info(f"caps: withheld (Afghanistan) — {len(got)} player-matches")
    rows += got
    out: dict[str, dict] = {}
    for pid, team, d, fmt in rows:
        if pid not in wanted:
            continue
        rec = out.setdefault(
            pid, {"first": d, "last": d, "formats": {}, "team": team, "_team_d": d}
        )
        rec["formats"][fmt] = rec["formats"].get(fmt, 0) + 1
        if d < rec["first"]:
            rec["first"] = d
        if d > rec["last"]:
            rec["last"] = d
        if d >= rec["_team_d"] and team != "ICC World XI":
            rec["team"], rec["_team_d"] = team, d
    for rec in out.values():
        rec.pop("_team_d", None)
    write_json(
        CAPS_CACHE,
        {
            "_source": (
                "Cricsheet men's T20I / ODI / Test XIs (info.players); matches Cricsheet withholds "
                "(featuring Afghanistan) from data/curated/withheld_internationals.json"
            ),
            **out,
        },
    )
    return out


def load_caps() -> dict[str, dict]:
    return {k: v for k, v in read_json(CAPS_CACHE, {}).items() if not k.startswith("_")}


# ---- IPL squads (Wikipedia personnel page) ------------------------------------------------------

IPL_TEAM_CODES = {
    "Chennai Super Kings": "CSK",
    "Mumbai Indians": "MI",
    "Royal Challengers Bengaluru": "RCB",
    "Royal Challengers Bangalore": "RCB",
    "Kolkata Knight Riders": "KKR",
    "Delhi Capitals": "DC",
    "Punjab Kings": "PBKS",
    "Sunrisers Hyderabad": "SRH",
    "Gujarat Titans": "GT",
    "Rajasthan Royals": "RR",
    "Lucknow Super Giants": "LSG",
}

# Every name an IPL franchise has played under on Cricsheet → today's code (renamed sides keep theirs;
# defunct sides get their own: GL, RPS, DEC, PWI, KTK)
IPL_TEAM_CODES_ALL = {
    **IPL_TEAM_CODES,
    "Delhi Daredevils": "DC",
    "Kings XI Punjab": "PBKS",
    "Gujarat Lions": "GL",
    "Rising Pune Supergiant": "RPS",
    "Rising Pune Supergiants": "RPS",
    "Deccan Chargers": "DEC",
    "Pune Warriors": "PWI",
    "Kochi Tuskers Kerala": "KTK",
}


def ipl_team_seasons(con) -> dict[str, list[tuple[int, str]]]:
    """cricsheet_id → [(IPL season, franchise code)] he played for, in order (from the ingested IPL
    XIs): the franchise ties of Keep or release (seasons with this side, home-grown = his first
    side; web_parity/keep.py `keep_features`)."""
    rows = con.execute(
        "SELECT DISTINCT CAST(SUBSTR(CAST(m.match_date AS VARCHAR), 1, 4) AS INT), p.team, "
        "p.identifier FROM match_players_ipl p JOIN matches_ipl m USING (match_id) "
        "WHERE p.identifier IS NOT NULL"
    ).fetchall()
    out: dict[str, list[tuple[int, str]]] = {}
    for y, t, cid in rows:
        out.setdefault(cid, []).append((int(y), IPL_TEAM_CODES_ALL.get(t, t)))
    for v in out.values():
        v.sort()
    return out


_SORTNAME = re.compile(r"\{\{\s*sortname\s*\|([^{}]*)\}\}", re.I)


def _sortname_title(params: str) -> tuple[str, str]:
    """{{sortname|First|Last|link|sort|dab=x}} → (display name, article title)."""
    pos, named = [], {}
    for p in params.split("|"):
        if "=" in p:
            k, _, v = p.partition("=")
            named[k.strip()] = v.strip()
        else:
            pos.append(p.strip())
    first = pos[0] if pos else ""
    last = pos[1] if len(pos) > 1 else ""
    shown = f"{first} {last}".strip()
    link = pos[2] if len(pos) > 2 and pos[2] else ""
    if link:
        title = link
    elif named.get("dab"):
        title = f"{shown} ({named['dab']})"
    else:
        title = shown
    return shown, title


def _team_in(text: str) -> str | None:
    for name, code in IPL_TEAM_CODES.items():
        if name in text:
            return code
    return None


def parse_ipl_personnel(text: str) -> dict[str, Any]:
    """The 2026 personnel page wikitext → {retired: [...], squads: {code: [player...]}}.

    Squad = retained (incl. traded in) + bought at the auction + in-season replacements; a player
    withdrawn from the season stays listed with his withdrawal reason."""
    sections = re.split(r"\n(==+)[ \t]*([^=\n]+?)[ \t]*\1[ \t]*(?=\n)", text)
    # sections = [pre, "==", title, body, "==", title, body, ...]
    by_title: dict[str, str] = {}
    for i in range(1, len(sections) - 2, 3):
        by_title[sections[i + 1].strip()] = (
            by_title.get(sections[i + 1].strip(), "") + sections[i + 2]
        )
    squads: dict[str, list[dict]] = {code: [] for code in sorted(set(IPL_TEAM_CODES.values()))}
    seen: dict[str, str] = {}

    def add(code: str, shown: str, title: str, status: str, **extra) -> None:
        if title in seen and seen[title] == code and status != "replacement":
            return
        squads[code].append({"name": shown, "wiki_title": title, "status": status, **extra})
        seen[title] = code

    retired: list[dict] = []
    pre = by_title.get("Pre-auction", "")
    for table in pre.split("{|")[1:]:
        if "Retired players" in table.split("\n", 2)[0] + table[:200]:
            for row in table.split("|-")[1:]:
                m = _SORTNAME.search(row)
                if not m:
                    continue
                shown, title = _sortname_title(m.group(1))
                dm = re.search(r"\|\s*(\d{1,2} \w+ \d{4})", row)
                ref = re.search(r"url=\s*([^\s|}]+)", row)
                retired.append(
                    {
                        "name": shown,
                        "wiki_title": title,
                        "date": dm.group(1) if dm else None,
                        "team": _team_in(row),
                        "evidence": ref.group(1) if ref else None,
                    }
                )
    retained = by_title.get("Retained players", "")
    for table in retained.split("{|")[1:]:
        caption = table.split("\n|-", 1)[0]
        code = _team_in(caption)
        if not code:
            continue
        for m in _SORTNAME.finditer(table):
            shown, title = _sortname_title(m.group(1))
            add(code, shown, title, "retained")
    sold = by_title.get("Sold players", "")
    for table in sold.split("{|")[1:]:
        for row in table.split("|-")[1:]:
            m = _SORTNAME.search(row)
            if not m:
                continue
            cells = re.split(r"\|\||\n\|", row[m.end() :])
            # columns after the name: country, matches, base price, 2026 team, price, 2025 team
            code = None
            for c in cells:
                code = _team_in(c)
                if code:
                    break
            if code:
                shown, title = _sortname_title(m.group(1))
                add(code, shown, title, "bought")
    withdrawn = by_title.get("Withdrawn players", "")
    for row in withdrawn.split("|-")[1:]:
        names = list(_SORTNAME.finditer(row))
        code = _team_in(row)
        if not names or not code:
            continue
        shown, title = _sortname_title(names[0].group(1))
        # cells after the team link: price || reason || date || replacement || ...
        after = row[row.find("]]", names[0].end()) + 2 :]
        cells = [_strip_markup(c) for c in after.split("||")]
        reason = cells[2] if len(cells) > 2 and cells[2] else None
        for p in squads[code]:
            if p["wiki_title"] == title:
                p["withdrawn"] = reason or True
        if len(names) > 1:
            rshown, rtitle = _sortname_title(names[1].group(1))
            add(code, rshown, rtitle, "replacement", replaced=shown)
    return {"retired": retired, "squads": squads}


CRICINFO_TITLES_CACHE = CURATED_DIR / "wikipedia_by_cricinfo.json"


def find_titles_by_cricinfo(
    players: dict[str, list[str]], fetch: bool = True, force: bool = False
) -> dict[str, dict]:
    """{cricsheet_id: {title} | {_status: not_found}} for players Wikidata can't find by their
    ESPNcricinfo id (an item without P2697, or none yet): Wikipedia's search for a cricketer article
    whose source carries the id, accepted only when that article links his ESPNcricinfo profile
    (`/cricketers/<slug>-<id>`) and only one article does. Cached in `CRICINFO_TITLES_CACHE` (a
    player is asked once; `force` asks again). `fetch=False` reads the cache only."""
    cache: dict[str, dict] = read_json(CRICINFO_TITLES_CACHE, {})
    if not fetch:
        return cache
    todo = {c: ids for c, ids in players.items() if ids and (force or c not in cache)}
    logger.info(f"wikipedia by cricinfo id: {len(players)} players, {len(todo)} to search")
    today = _dt.date.today().isoformat()
    with _client() as cx:
        for n, (cid, ids) in enumerate(sorted(todo.items()), 1):
            found: set[str] = set()
            for ci in ids:
                r = _get_with_retry(
                    cx,
                    WIKIPEDIA_API,
                    {
                        "action": "query",
                        "list": "search",
                        "srsearch": f'hastemplate:"Infobox cricketer" insource:"{ci}" '
                        f"insource:/[^0-9]{ci}[^0-9]/",
                        "srnamespace": 0,
                        "srlimit": 10,
                        "format": "json",
                        "formatversion": "2",
                    },
                    f"cricinfo search {ci}",
                )
                for hit in r.json().get("query", {}).get("search", []):
                    e = _get_with_retry(
                        cx,
                        WIKIPEDIA_API,
                        {
                            "action": "query",
                            "prop": "extlinks",
                            "titles": hit["title"],
                            "ellimit": "max",
                            "elquery": "www.espncricinfo.com/cricketers/",
                            "elprotocol": "https",
                            "format": "json",
                            "formatversion": "2",
                        },
                        f"extlinks {hit['title']}",
                    )
                    urls = [
                        x["url"] for p in e.json()["query"]["pages"] for x in p.get("extlinks", [])
                    ]
                    if any(re.search(rf"[/-]{ci}(?:[/?#.]|$)", u) for u in urls):
                        found.add(hit["title"])
                    time.sleep(WIKI_SLEEP_S)
            cache[cid] = (
                {"title": found.pop(), "_fetched": today}
                if len(found) == 1
                else {"_status": "ambiguous" if found else "not_found", "_fetched": today,
                      **({"titles": sorted(found)} if found else {})}
            )  # fmt: skip
            if n % 50 == 0:
                write_json(CRICINFO_TITLES_CACHE, cache)
                logger.info(f"  cricinfo search {n}/{len(todo)}")
    write_json(CRICINFO_TITLES_CACHE, cache)
    return cache


def squad_titles(squads: dict[str, Any]) -> dict[str, str]:
    """{cricsheet_id or `wiki:<title>`: Wikipedia title} for every row of the IPL squads file that
    links an article (a row with no Cricsheet id has no match data yet)."""
    out: dict[str, str] = {}
    for rows in (squads.get("squads") or {}).values():
        for r in rows:
            t = r.get("wiki_title")
            if t:
                out.setdefault(r.get("cricsheet_id") or f"wiki:{t}", t)
    return out


def fetch_ipl_personnel(force: bool = False) -> dict[str, Any]:
    """Fetch + parse the personnel page into data/curated/ipl_squads_2026.json (hand edits to that
    file are kept: a rerun only refreshes it with `force`)."""
    if IPL_SQUADS.exists() and not force:
        return read_json(IPL_SQUADS, {})
    with _client() as cx:
        r = _get_with_retry(
            cx,
            WIKIPEDIA_API,
            {
                "action": "query",
                "prop": "revisions",
                "rvprop": "content|ids|timestamp",
                "rvslots": "main",
                "format": "json",
                "formatversion": "2",
                "titles": IPL_PERSONNEL_PAGE,
            },
            "ipl personnel",
        )
    page = r.json()["query"]["pages"][0]
    rev = page["revisions"][0]
    parsed = parse_ipl_personnel(rev["slots"]["main"]["content"])
    out = {
        "_source": (
            f"Wikipedia, '{IPL_PERSONNEL_PAGE}' (CC BY-SA 4.0), revision {rev.get('revid')} "
            f"of {rev.get('timestamp')}: https://en.wikipedia.org/wiki/"
            + IPL_PERSONNEL_PAGE.replace(" ", "_")
        ),
        "_note": (
            "Parsed automatically; edit by hand if a row is wrong (a rerun keeps this file unless "
            "--force). `cricsheet_id` is filled by the player-master build."
        ),
        "season": IPL_SEASON,
        **parsed,
    }
    write_json(IPL_SQUADS, out)
    return out


# ---- IPL salaries (same Wikipedia personnel page) -------------------------------------------------

# {{INRConvert|18|c|lk=on}} = ₹18 crore, {{INRConvert|30|l}} = ₹30 lakh; "INR convert" is the
# same template under another name.
_INR = re.compile(r"\{\{\s*INR\s*Convert\s*\|\s*([\d.]+)\s*\|\s*([clCL])", re.I)
_FLAG = re.compile(r"\{\{\s*cr\s*\|\s*([A-Za-z]+)\s*\}\}", re.I)


def _crore(text: str) -> float | None:
    """The first {{INRConvert}} amount in a cell, in crore (lakh / 100)."""
    m = _INR.search(text or "")
    if not m:
        return None
    v = float(m.group(1))
    return round(v if m.group(2).lower() == "c" else v / 100.0, 4)


def _flag(text: str) -> str | None:
    from cricdesk.scout.identity.countries import normalise

    m = _FLAG.search(text or "")
    return normalise(m.group(1)) if m else None


def parse_ipl_salaries(text: str) -> dict[str, Any]:
    """The personnel page wikitext → each squad player's salary and how he was acquired.

    {"players": {code: {wiki_title: {salary_cr, acquired, country}}}, "trades": [...]}:
    - **retained** table: the contract carried into the season (2025 auction / retention price, or
      the price a trade moved with him), with his nationality flag;
    - **traded** table: a retained-list player who arrived by trade is `acquired = "trade"`;
    - **sold** tables: the auction price (lakhs on the page), `acquired = "auction"`;
    - **withdrawn** table: a replacement's fee, `acquired = "replacement"`.
    Salaries are in crore."""
    sections = re.split(r"\n(==+)[ \t]*([^=\n]+?)[ \t]*\1[ \t]*(?=\n)", text)
    by_title: dict[str, str] = {}
    for i in range(1, len(sections) - 2, 3):
        t = sections[i + 1].strip()
        by_title[t] = by_title.get(t, "") + sections[i + 2]
    players: dict[str, dict[str, dict]] = {
        code: {} for code in sorted(set(IPL_TEAM_CODES.values()))
    }
    trades: list[dict] = []

    # traded table (in Pre-auction): Date | Name | Salary | From | To — From / To cells may span
    # several rows (rowspan), so the last seen value carries down.
    pre = by_title.get("Pre-auction", "")
    for table in pre.split("{|")[1:]:
        if "Traded players" not in table[:300]:
            continue
        cur = {"from": None, "to": None}
        span = {"from": 0, "to": 0}  # rows still covered by a rowspan'd From / To cell
        for row in table.split("|-")[1:]:
            m = _SORTNAME.search(row)
            if not m:
                continue
            shown, title = _sortname_title(m.group(1))
            after = row[m.end() :]
            need = []
            for col in ("from", "to"):
                if span[col] > 0:
                    span[col] -= 1  # carried down from the row above
                else:
                    need.append(col)
            for cell in re.split(r"\|\||\n\|", after):
                code = _team_in(cell)
                if not code or not need:
                    continue
                col = need.pop(0)
                cur[col] = code
                rs = re.search(r'rowspan\s*=\s*"?(\d+)', cell)
                span[col] = int(rs.group(1)) - 1 if rs else 0
            trades.append(
                {
                    "name": shown,
                    "wiki_title": title,
                    "salary_cr": _crore(after),
                    "from": cur["from"],
                    "to": cur["to"],
                }
            )

    retained = by_title.get("Retained players", "")
    traded_to = {(t["to"], t["wiki_title"]) for t in trades}
    for table in retained.split("{|")[1:]:
        caption = table.split("\n|-", 1)[0]
        code = _team_in(caption)
        if not code:
            continue
        for row in table.split("|-")[1:]:
            m = _SORTNAME.search(row)
            if not m:
                continue
            _shown, title = _sortname_title(m.group(1))
            after = row[m.end() :]
            players[code][title] = {
                "salary_cr": _crore(after),
                "acquired": "trade" if (code, title) in traded_to else "retained",
                "country": _flag(after),
            }

    sold = by_title.get("Sold players", "")
    for table in sold.split("{|")[1:]:
        for row in table.split("|-")[1:]:
            m = _SORTNAME.search(row)
            if not m:
                continue
            _shown, title = _sortname_title(m.group(1))
            after = row[m.end() :]
            cells = [c.strip() for c in re.split(r"\|\||\n\|", after)]
            code, price = None, None
            for i, c in enumerate(cells):
                code = _team_in(c)
                if code:
                    nxt = cells[i + 1] if i + 1 < len(cells) else ""
                    num = re.match(r"^\s*([\d.]+)", _strip_markup(nxt))
                    price = round(float(num.group(1)) / 100.0, 4) if num else None
                    break
            if code:
                players[code][title] = {
                    "salary_cr": price,
                    "acquired": "auction",
                    "country": _flag(after),
                }

    withdrawn = by_title.get("Withdrawn players", "")
    for row in withdrawn.split("|-")[1:]:
        names = list(_SORTNAME.finditer(row))
        code = _team_in(row)
        if len(names) < 2 or not code:
            continue
        _rshown, rtitle = _sortname_title(names[1].group(1))
        after = row[names[1].end() :]
        players[code].setdefault(
            rtitle,
            {"salary_cr": _crore(after), "acquired": "replacement", "country": None},
        )
    return {"players": players, "trades": trades}


def fetch_ipl_personnel_text(title: str = IPL_PERSONNEL_PAGE) -> tuple[str, dict]:
    """A personnel page's current wikitext and its revision {revid, ts}."""
    with _client() as cx:
        r = _get_with_retry(
            cx,
            WIKIPEDIA_API,
            {
                "action": "query",
                "prop": "revisions",
                "rvprop": "content|ids|timestamp",
                "rvslots": "main",
                "format": "json",
                "formatversion": "2",
                "titles": title,
            },
            "ipl personnel",
        )
    rev = r.json()["query"]["pages"][0]["revisions"][0]
    return rev["slots"]["main"]["content"], {"revid": rev.get("revid"), "ts": rev.get("timestamp")}


def international_dates(con, raw_dir: Path | None = None) -> dict[str, list[str]]:
    """cricsheet_id → sorted dates of every men's international XI he played (T20Is from the
    ingested `t20s_male` collection, ODIs and Tests from Cricsheet's archives, read and never
    ingested), so caps can be counted before any date (the market price's `intl_caps` /
    `intl_caps_2y`; scripts/ipl_price_model.py and the site export count them the same way)."""
    from cricdesk.scout.ingest.cricsheet import download_zip

    raw_dir = raw_dir or (DATA_DIR / "cricsheet" / "raw")
    seen: set[tuple[str, str]] = set()
    tables = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
    if "match_players_t20s_male" in tables and "matches_t20s_male" in tables:
        for a, b in con.execute(
            "SELECT p.identifier, m.match_date FROM match_players_t20s_male p "
            "JOIN matches_t20s_male m USING (match_id) WHERE p.identifier IS NOT NULL"
        ).fetchall():
            seen.add((a, str(b)[:10]))
    for fmt, z in INTL_ZIPS.items():
        path = raw_dir / z
        if not path.exists():
            path = download_zip(z, raw_dir)
        for pid, _team, d, _f in read_international_zip(path, fmt):
            seen.add((pid, d))
    # matches Cricsheet withholds (featuring Afghanistan): identity/withheld.py
    from cricdesk.scout.identity import withheld

    extra: list[tuple[str, str]] = []
    for pid, _team, d, _f, src in withheld.load_rows(with_source=True):
        if src == withheld.SNAPSHOT_SOURCE:
            seen.add((pid, d))  # a real match date, like the archives above
        else:
            # dated at the Wikipedia revision that published it: several appearances can share
            # a date, so they are kept one by one rather than de-duplicated by date
            extra.append((pid, d))
    out: dict[str, list[str]] = {}
    for pid, d in sorted([*seen, *extra], key=lambda x: x[1]):
        out.setdefault(pid, []).append(d)
    return out
