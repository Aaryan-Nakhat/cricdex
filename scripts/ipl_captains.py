"""IPL and international captaincy from Wikipedia, matched to Cricsheet ids.

Reads (CC BY-SA 4.0, each page pinned to the revision read and cached raw in
`data/curated/ipl_captain_pages/`):

- each IPL franchise's article ("Chennai Super Kings", …): its captains table, one row per captain with
  the years he captained it (from / to, or a duration) and his matches as captain;
- "List of Indian Premier League captains": every IPL captain with his first / last year, matches and
  team(s), used for the defunct franchises whose articles have no captains table (Deccan Chargers,
  Kochi Tuskers Kerala, Pune Warriors India, Rising Pune Supergiant, Gujarat Lions);
- each Test nation's "List of <country> national cricket captains": the men's Test, ODI and T20I captains
  with the years they captained (Ireland's page is "List of Ireland cricket captains");
- the season articles of the two-season franchises Rising Pune Supergiant and Gujarat Lions (2016-17):
  the infobox `captain` of each season (all three of their captains also led another franchise, so the
  IPL captains list can't say which years were theirs). `matches` is the team's matches that season in
  our ball-by-ball data (the infobox names the season's captain, not his match count).

and writes the hand-editable `data/curated/ipl_captains.json`: `ipl` and `international` stints
{player, wiki_title, team | country + format, from, to, matches, cricsheet_id}. A stint covers every year
from `from` to `to`, except a sparse one (fewer than STAND_IN_PER_YEAR matches a year on average: a
stand-in), which counts only its first and last years (`years`). The price model reads it
(scripts/ipl_price_model.py: captained the IPL season before the auction, IPL seasons as captain,
captained his country in the two years before), as does the site export (Keep or release, the auction
pool, the player identity block). Hand edits: set `"edited": true` on a row and a re-parse keeps it.

Run:
    uv run python scripts/ipl_captains.py            # parse the cached pages
    uv run python scripts/ipl_captains.py --fetch    # re-download them first
"""

from __future__ import annotations

import json
import re
import time

import typer
from ipl_auction_history import Matcher, page_tables

from cricdesk.config import DATA_DIR
from cricdesk.scout.identity import master, sources
from cricdesk.scout.identity.captains import STAND_IN_PER_YEAR

app = typer.Typer(add_completion=False)

PAGES = DATA_DIR / "curated" / "ipl_captain_pages"
OUT = DATA_DIR / "curated" / "ipl_captains.json"
CURRENT_YEAR = 2026  # "present" in a span

TEAM_PAGES = {
    "CSK": "Chennai Super Kings",
    "MI": "Mumbai Indians",
    "RCB": "Royal Challengers Bengaluru",
    "KKR": "Kolkata Knight Riders",
    "DC": "Delhi Capitals",
    "PBKS": "Punjab Kings",
    "SRH": "Sunrisers Hyderabad",
    "GT": "Gujarat Titans",
    "RR": "Rajasthan Royals",
    "LSG": "Lucknow Super Giants",
    "DCH": "Deccan Chargers",
    "KTK": "Kochi Tuskers Kerala",
    "PWI": "Pune Warriors India",
    "RPS": "Rising Pune Supergiant",
    "GL": "Gujarat Lions",
}
IPL_LIST = "List of Indian Premier League captains"
NATION_PAGES = {
    "IND": "List of India national cricket captains",
    "AUS": "List of Australia national cricket captains",
    "ENG": "List of England cricket captains",
    "PAK": "List of Pakistan national cricket captains",
    "BAN": "List of Bangladesh national cricket captains",
    "LKA": "List of Sri Lanka national cricket captains",
    "ZAF": "List of South Africa national cricket captains",
    "NZL": "List of New Zealand national cricket captains",
    "WIN": "List of West Indies cricket captains",
    "AFG": "List of Afghanistan national cricket captains",
    "ZIM": "List of Zimbabwe national cricket captains",
    "IRL": "List of Ireland cricket captains",
}
# season articles of the franchises with no captains table whose captains led other sides too
SEASON_PAGES = {
    ("RPS", 2016): "2016 Rising Pune Supergiant season",
    ("RPS", 2017): "2017 Rising Pune Supergiant season",
    ("GL", 2016): "2016 Gujarat Lions season",
    ("GL", 2017): "2017 Gujarat Lions season",
}
# their names in Cricsheet's IPL data (for the season's match count)
SEASON_TEAM_NAMES = {
    "RPS": ("Rising Pune Supergiant", "Rising Pune Supergiants"),
    "GL": ("Gujarat Lions",),
}
_CAPTAIN = re.compile(r"\|\s*captain\s*=\s*\[\[([^\]|]+)(?:\|([^\]]+))?\]\]", re.I)
# list-code abbreviations on the IPL captains list ("Team(s)": "CSK RPS")
LIST_CODES = {"DC": "DC", "DD": "DC", "KXIP": "PBKS", "PBKS": "PBKS", "RCB": "RCB", "DCH": "DCH",
              "KTK": "KTK", "PWI": "PWI", "RPS": "RPS", "GL": "GL", "CSK": "CSK", "MI": "MI",
              "KKR": "KKR", "RR": "RR", "SRH": "SRH", "GT": "GT", "LSG": "LSG"}  # fmt: skip
_SKIP_NATION = re.compile(
    r"women|youth|under-19|under 19|rest of the world|world series|rebel|icc|qualifier|trophy", re.I
)


def _years(text: str) -> tuple[int, int] | None:
    t = (text or "").replace("present", str(CURRENT_YEAR))
    ys = [int(y) for y in re.findall(r"(?<!\d)(19\d\d|20\d\d)(?!\d)", t)]
    return (min(ys), max(ys)) if ys else None


def _int(text: str) -> int | None:
    m = re.search(r"\d+", (text or "").replace(",", ""))
    return int(m.group()) if m else None


def _header(rows: list[list[dict]]) -> tuple[int, list[str]] | None:
    for i, row in enumerate(rows[:3]):
        texts = [c["text"] for c in row]
        if len(set(texts)) >= 3 and any(
            re.search(r"^(player|name|captain)", t, re.I) for t in texts
        ):
            return i, texts
    return None


def parse_team(code: str, html: str) -> list[dict]:
    out = []
    for tb in page_tables(html):
        # only the captains table (other tables carry from / to / matches too: appearances, staff)
        if not re.search(r"captain", " ".join(tb["heads"]) + " " + (tb["caption"] or ""), re.I):
            continue
        h = _header(tb["rows"])
        if not h:
            continue
        i0, hdr = h
        if not any(re.search(r"^(from|duration|span|years?)", x, re.I) for x in hdr):
            continue
        if not any(re.search(r"^matches|^played", x, re.I) for x in hdr):
            continue
        i_name = next(i for i, x in enumerate(hdr) if re.search(r"^(player|name)", x, re.I))
        i_m = next(i for i, x in enumerate(hdr) if re.search(r"^matches|^played", x, re.I))
        i_from = next((i for i, x in enumerate(hdr) if re.search(r"^from", x, re.I)), None)
        i_to = next((i for i, x in enumerate(hdr) if re.search(r"^to$", x, re.I)), None)
        i_dur = next(
            (i for i, x in enumerate(hdr) if re.search(r"^(duration|span|years?)", x, re.I)), None
        )
        for row in tb["rows"][i0 + 1 :]:
            if len(row) <= max(i_name, i_m):
                continue
            nm = row[i_name]
            text = " ".join(
                row[i]["text"] for i in (i_from, i_to, i_dur) if i is not None and i < len(row)
            )
            ys = _years(text)
            if not ys or not nm["text"] or re.search(r"total|updated", nm["text"], re.I):
                continue
            out.append(
                {"player": re.sub(r"\[.*?\]|[*†‡]", "", nm["text"]).strip(), "wiki_title": nm["link"],
                 "team": code, "from": ys[0], "to": ys[1], "matches": _int(row[i_m]["text"]),
                 "source": f"team_{code}"}
            )  # fmt: skip
    return out


def ipl_list_rows(html: str) -> list[dict]:
    """The IPL captains list: {player, wiki_title, first, last, matches, teams} per captain."""
    out = []
    for tb in page_tables(html):
        h = _header(tb["rows"])
        if not h or "Team(s)" not in h[1]:
            continue
        i0, hdr = h
        ix = {k: hdr.index(k) for k in ("Player", "First", "Last", "Matches", "Team(s)")}
        for row in tb["rows"][i0 + 1 :]:
            if len(row) <= max(ix.values()):
                continue
            codes = {LIST_CODES.get(c) for c in re.split(r"[\s,/]+", row[ix["Team(s)"]]["text"])}
            codes.discard(None)
            ys = _years(row[ix["First"]]["text"] + " " + row[ix["Last"]]["text"])
            if not ys or not codes:
                continue
            out.append(
                {"player": row[ix["Player"]]["text"], "wiki_title": row[ix["Player"]]["link"],
                 "first": ys[0], "last": ys[1], "matches": _int(row[ix["Matches"]]["text"]),
                 "teams": sorted(codes)}
            )  # fmt: skip
    return out


def reconcile(stints: list[dict], listed: list[dict]) -> list[dict]:
    """Fill the team tables from the IPL captains list, which is kept more current: a one-team
    captain with no stint for that team gets one from the list (the defunct franchises have no
    captains table); and a captain whose latest stint ends before the list's last year has it
    extended to that year (a franchise article that lags the newest season)."""

    def same(s: dict, r: dict) -> bool:
        return (s.get("wiki_title") or s["player"]) == (r.get("wiki_title") or r["player"])

    out = list(stints)
    for r in listed:
        mine = [s for s in out if same(s, r)]
        if len(r["teams"]) == 1 and not any(s["team"] == r["teams"][0] for s in mine):
            out.append(
                {"player": r["player"], "wiki_title": r["wiki_title"], "team": r["teams"][0],
                 "from": r["first"], "to": r["last"], "matches": r["matches"], "source": "ipl_list"}
            )  # fmt: skip
            continue
        latest = max(
            (s for s in mine if s["team"] in r["teams"]), key=lambda s: s["to"], default=None
        )
        if latest is not None and latest["to"] < r["last"]:
            latest["to_listed"] = latest["to"]
            latest["to"] = r["last"]
            latest["source"] = latest.get("source", "") + "+ipl_list"
            if latest.get("matches") is not None and r.get("matches"):
                # the extra seasons' matches: the list's total less his other stints
                other = sum(s.get("matches") or 0 for s in mine if s is not latest)
                latest["matches"] = max(latest["matches"], r["matches"] - other)
    return out


def parse_nation(country: str, html: str) -> list[dict]:
    out = []
    for tb in page_tables(html):
        heads = " > ".join(tb["heads"]) + " " + (tb["caption"] or "")
        if _SKIP_NATION.search(heads):
            continue
        if re.search(r"twenty20|t20", heads, re.I):
            fmt = "t20i"
        elif re.search(r"one.day|odi", heads, re.I):
            fmt = "odi"
        elif re.search(r"test", heads, re.I):
            fmt = "test"
        else:
            continue
        h = _header(tb["rows"])
        if not h:
            continue
        i0, hdr = h
        i_name = next(
            (i for i, x in enumerate(hdr) if re.search(r"^(player|name|captain)", x, re.I)), None
        )
        i_yr = next(
            (
                i
                for i, x in enumerate(hdr)
                if re.search(r"year|period|span|season|duration", x, re.I)
            ),
            None,
        )
        i_m = next(
            (i for i, x in enumerate(hdr) if re.search(r"^(matches|played|mat)", x, re.I)), None
        )
        if i_name is None or i_yr is None:
            continue
        for row in tb["rows"][i0 + 1 :]:
            if len(row) <= max(i_name, i_yr):
                continue
            nm = row[i_name]
            if not nm["text"] or re.search(r"total|statistics|stats", nm["text"], re.I):
                continue
            ys = _years(row[i_yr]["text"])
            if not ys or ys[1] < 2000:
                continue  # only captaincy this century can matter for an IPL auction
            out.append(
                {"player": re.sub(r"\[.*?\]|[*†‡]", "", nm["text"]).strip(), "wiki_title": nm["link"],
                 "country": country, "format": fmt, "from": ys[0], "to": ys[1],
                 "matches": _int(row[i_m]["text"]) if i_m is not None and i_m < len(row) else None}
            )  # fmt: skip
    return out


def parse_season(code: str, year: int, wikitext: str) -> dict | None:
    """The season's captain from a season article's infobox (`| captain = [[Title|Name]]`)."""
    m = _CAPTAIN.search(wikitext)
    if not m:
        return None
    title = m.group(1).strip()
    return {"player": (m.group(2) or re.sub(r"\s*\(.*\)$", "", title)).strip(),
            "wiki_title": title, "team": code, "from": year, "to": year, "matches": None,
            "source": f"season_{code}_{year}"}  # fmt: skip


def _season_matches(code: str, year: int) -> int | None:
    """The team's matches that season in our IPL ball-by-ball data (None without the database)."""
    import duckdb

    try:
        with duckdb.connect(
            str(DATA_DIR / "cricsheet" / "cricsheet.duckdb"), read_only=True
        ) as con:
            names = SEASON_TEAM_NAMES[code]
            q = (
                "SELECT COUNT(DISTINCT match_id) FROM balls_ipl WHERE match_date LIKE ? AND "
                f"(batting_team IN ({','.join('?' * len(names))}) OR "
                f"bowling_team IN ({','.join('?' * len(names))}))"
            )
            n = con.execute(q, [f"{year}-%", *names, *names]).fetchone()[0]
            return int(n) or None
    except duckdb.Error:
        return None


def _fetch_wikitext(key: str, title: str) -> None:
    """Cache a page's wikitext (pinned: the revision id is kept next to it)."""
    text, rev = sources.fetch_ipl_personnel_text(title)
    (PAGES / f"{key}.wiki").write_text(text, encoding="utf-8")
    meta = {"title": title, "revid": rev["revid"], "ts": rev["ts"],
            "url": "https://en.wikipedia.org/wiki/" + title.replace(" ", "_")}  # fmt: skip
    (PAGES / f"{key}.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    time.sleep(1)


def _fetch(key: str, title: str) -> None:
    text, rev = sources.fetch_ipl_personnel_text(title)
    with sources._client() as cx:
        r = sources._get_with_retry(
            cx,
            sources.WIKIPEDIA_API,
            {"action": "parse", "oldid": rev["revid"], "prop": "text", "format": "json",
             "formatversion": "2", "disablelimitreport": 1},
            "parse",
        )  # fmt: skip
    (PAGES / f"{key}.html").write_text(r.json()["parse"]["text"], encoding="utf-8")
    meta = {"title": title, "revid": rev["revid"], "ts": rev["ts"],
            "url": "https://en.wikipedia.org/wiki/" + title.replace(" ", "_")}  # fmt: skip
    (PAGES / f"{key}.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    time.sleep(1)


def _meta(key: str) -> dict:
    return json.loads((PAGES / f"{key}.json").read_text(encoding="utf-8"))


@app.command()
def run(
    fetch: bool = typer.Option(False, "--fetch", help="Re-download the Wikipedia pages."),
    fetch_missing: bool = typer.Option(
        False, "--fetch-missing", help="Download only the pages not cached yet."
    ),
) -> None:
    PAGES.mkdir(parents=True, exist_ok=True)
    if fetch or fetch_missing:
        for code, title in TEAM_PAGES.items():
            if fetch or not (PAGES / f"team_{code}.html").exists():
                _fetch(f"team_{code}", title)
        if fetch or not (PAGES / "ipl.html").exists():
            _fetch("ipl", IPL_LIST)
        for c, title in NATION_PAGES.items():
            if fetch or not (PAGES / f"{c}.html").exists():
                _fetch(c, title)
        for (code, year), title in SEASON_PAGES.items():
            if fetch or not (PAGES / f"season_{code}_{year}.wiki").exists():
                _fetch_wikitext(f"season_{code}_{year}", title)
    match = Matcher(master.load())
    old = sources.read_json(OUT, {})
    kept = [r for r in (old.get("ipl") or []) + (old.get("international") or []) if r.get("edited")]
    # a hand-edited row replaces the parsed row with the same key, or with `replaces_from` as its
    # first year (a page error fixed by hand, e.g. Porterfield's T20I years on Ireland's list)
    keys = {
        (r.get("team") or r.get("country"), r.get("format"), r.get("player"), y)
        for r in kept
        for y in {r["from"], r.get("replaces_from", r["from"])}
    }

    ipl: list[dict] = []
    for code in TEAM_PAGES:
        p = PAGES / f"team_{code}.html"
        if p.exists():
            ipl += parse_team(code, p.read_text(encoding="utf-8"))
    ipl = reconcile(ipl, ipl_list_rows((PAGES / "ipl.html").read_text(encoding="utf-8")))
    # RPS / GL: one stint per season from the season articles (their captains led other sides too)
    for code, year in SEASON_PAGES:
        p = PAGES / f"season_{code}_{year}.wiki"
        row = parse_season(code, year, p.read_text(encoding="utf-8")) if p.exists() else None
        if row and not any(r["team"] == code and r["from"] <= year <= r["to"] for r in ipl):
            row["matches"] = _season_matches(code, year)
            ipl.append(row)
    intl: list[dict] = []
    for c in NATION_PAGES:
        p = PAGES / f"{c}.html"
        if p.exists():
            intl += parse_nation(c, p.read_text(encoding="utf-8"))
    for r in ipl + intl:
        r["cricsheet_id"], r["match"] = match(r["player"], r.get("wiki_title"))
    ipl = [r for r in ipl if (r["team"], None, r["player"], r["from"]) not in keys]
    intl = [r for r in intl if (r["country"], r["format"], r["player"], r["from"]) not in keys]
    ipl += [r for r in kept if "team" in r]
    intl += [r for r in kept if "country" in r]

    sources_meta = {"teams": {c: _meta(f"team_{c}") for c in TEAM_PAGES if (PAGES / f"team_{c}.json").exists()},
                    "ipl_list": _meta("ipl"),
                    "nations": {c: _meta(c) for c in NATION_PAGES if (PAGES / f"{c}.json").exists()},
                    "seasons": {f"{c} {y}": _meta(f"season_{c}_{y}") for (c, y) in SEASON_PAGES
                                if (PAGES / f"season_{c}_{y}.json").exists()}}  # fmt: skip
    out = {
        "_source": (
            "Wikipedia (CC BY-SA 4.0): each IPL franchise's article (captains table), 'List of Indian "
            "Premier League captains', each Test nation's list of national cricket captains, and the "
            "2016-17 season articles of Rising Pune Supergiant and Gujarat Lions (infobox captain); "
            "revisions in `sources`. Parsed by scripts/ipl_captains.py."
        ),
        "_licence": "CC BY-SA 4.0 (derived from Wikipedia); share-alike applies to this file",
        "_note": (
            "A stint covers every year from..to, except one with fewer than "
            f"{STAND_IN_PER_YEAR} matches a year (a stand-in: first and last years only). Set "
            '"edited": true on a row to keep a hand edit through a re-parse ("replaces_from": the '
            "parsed row's first year, when the edit corrects a page's years)."
        ),
        "sources": sources_meta,
        "ipl": sorted(ipl, key=lambda r: (r["team"], r["from"], r["player"])),
        "international": sorted(
            intl, key=lambda r: (r["country"], r["format"], r["from"], r["player"])
        ),
    }
    sources.write_json(OUT, out)
    for k in ("ipl", "international"):
        rows = out[k]
        n = sum(1 for r in rows if r.get("cricsheet_id"))
        print(f"{k}: {len(rows)} stints, {n} matched ({100 * n / max(len(rows), 1):.0f}%)")
    print("IPL teams:", sorted({r["team"] for r in ipl}))
    print("unmatched IPL:", sorted({r["player"] for r in ipl if not r.get("cricsheet_id")}))


if __name__ == "__main__":
    app()
