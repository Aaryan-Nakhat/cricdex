"""Every IPL player auction 2008-2026 (and the retentions around them) from Wikipedia.

Reads the per-season Wikipedia pages ("List of 2008 Indian Premier League auctions and personnel
signings", "List of 2009 ... personnel changes" through 2026; text CC BY-SA 4.0), each pinned to the
revision it was read at, and writes the hand-editable table `data/curated/ipl_auction_history.json`:

- `lots`        one row per auction lot Wikipedia lists: player, his country, base price, final
                price, buying team, his previous team where the page has it, RTM, set, sold / unsold
                (Wikipedia lists sold players only, except the 2008 second auction, so "unsold" is
                rare here: the price model builds its own "not bought" risk set, see
                scripts/ipl_price_model.py)
- `retentions`  retained players with their salary (and, 2018, the purse deduction when it
                differs), the 2008 icon players, the 2016 draft of the two new franchises
- `auctions`    per season: date, mega / mini, currency, purse, and for the US$ years (2008-2013)
                the exchange rate used to convert to rupees: the Federal Reserve H.10 noon buying
                rate on the auction day (or the last business day before it), public-domain US
                government data, cached in `data/curated/ipl_auction_pages/fx_usd_inr_fed_h10.csv`

Every price is stored in crore (₹1 crore = ₹10 million; ₹1 lakh = 0.01 crore); a US$ price keeps
its dollars too (`price_usd`). Players are matched to a Cricsheet id through the player master:
Wikipedia title first, then the page's name against the master's names and aliases (unique hits
only), then first initial + surname among IPL players.

The raw pages (wikitext and the rendered HTML of the pinned revision) are cached in
`data/curated/ipl_auction_pages/`; `--fetch` refreshes them. Hand edits: set `"edited": true` on a
row and a re-parse keeps it as it is (matched by season, kind and Wikipedia title).

Run:
    uv run python scripts/ipl_auction_history.py            # parse the cached pages
    uv run python scripts/ipl_auction_history.py --fetch    # re-download the pages first
"""

from __future__ import annotations

import csv
import datetime as dt
import json
import re
import time

import typer
from bs4 import BeautifulSoup

from cricdex.config import DATA_DIR
from cricdex.scout.identity import master, sources
from cricdex.scout.identity.countries import normalise

app = typer.Typer(add_completion=False)

CURATED = DATA_DIR / "curated"
PAGES = CURATED / "ipl_auction_pages"
OUT = CURATED / "ipl_auction_history.json"
FX_CSV = PAGES / "fx_usd_inr_fed_h10.csv"
FX_SOURCE = (
    "Board of Governors of the Federal Reserve System, H.10 Foreign Exchange Rates, historical "
    "rates for the Indian rupee (noon buying rates in New York, rupees per US$): "
    "https://www.federalreserve.gov/releases/h10/hist/dat00_in.htm"
)
FIRST, LAST = 2008, 2026


def page_title(season: int) -> str:
    if season == 2008:
        return "List of 2008 Indian Premier League auctions and personnel signings"
    return f"List of {season} Indian Premier League personnel changes"


# Per season: the (first) auction day, mega or mini, the money unit and each team's total purse
# (salary cap) in that unit. `purse_src` quotes the page (or says it's assumed).
AUCTIONS: dict[int, dict] = {
    2008: {"date": "2008-02-20", "kind": "mega", "currency": "USD", "purse": 5.0,
           "purse_src": "2008 page: 'The total salary cap was set at US$5 million'"},
    2009: {"date": "2009-02-06", "kind": "mini", "currency": "USD", "purse": 5.0,
           "purse_src": "assumed: the 2008 US$5 million cap, unchanged (the page states none)"},
    2010: {"date": "2010-01-19", "kind": "mini", "currency": "USD", "purse": 5.0,
           "purse_src": "assumed: the 2008 US$5 million cap, unchanged (the page states none)"},
    2011: {"date": "2011-01-08", "kind": "mega", "currency": "USD", "purse": 9.0,
           "purse_src": "2011 page: 'the salary cap being $9 million'"},
    2012: {"date": "2012-02-04", "kind": "mini", "currency": "USD", "purse": 11.0,
           "purse_src": "2012 page: 'increased the salary cap by $2 million' (from US$9 million)"},
    2013: {"date": "2013-02-03", "kind": "mini", "currency": "USD", "purse": 12.5,
           "purse_src": "assumed: US$12.5 million (widely reported; the page states none)"},
    2014: {"date": "2014-02-12", "kind": "mega", "currency": "INR", "purse": 60.0,
           "purse_src": "2014 page, team summary: salary-cap deduction + purse left = ₹60 crore"},
    2015: {"date": "2015-02-16", "kind": "mini", "currency": "INR", "purse": 63.0,
           "purse_src": "2015 page: 'increased to Rs. 63 crores for the 2015 edition'"},
    2016: {"date": "2016-02-06", "kind": "mini", "currency": "INR", "purse": 66.0,
           "purse_src": "2016 page: 'increased to Rs. 66 crores for the 2016 edition'"},
    2017: {"date": "2017-02-20", "kind": "mini", "currency": "INR", "purse": 66.0,
           "purse_src": "2017 page: 'the salary purse of ₹66 crore'"},
    2018: {"date": "2018-01-27", "kind": "mega", "currency": "INR", "purse": 80.0,
           "purse_src": "2018 page: 'The salary cap for the season was increased from ₹66 crore to ₹80 crore'"},
    2019: {"date": "2018-12-18", "kind": "mini", "currency": "INR", "purse": 82.0,
           "purse_src": "2019 page, pre-auction summary: retained amount + funds remaining = ₹82 crore"},
    2020: {"date": "2019-12-19", "kind": "mini", "currency": "INR", "purse": 85.0,
           "purse_src": "2020 page: 'their original Rs. 85 crores'"},
    2021: {"date": "2021-02-18", "kind": "mini", "currency": "INR", "purse": 85.0,
           "purse_src": "2021 page, pre-auction summary: retained amount + funds remaining = ₹85 crore"},
    2022: {"date": "2022-02-12", "kind": "mega", "currency": "INR", "purse": 90.0,
           "purse_src": "2022 page: 'a total salary cap of INR 90 crore available at the mega auction'"},
    2023: {"date": "2022-12-23", "kind": "mini", "currency": "INR", "purse": 95.0,
           "purse_src": "assumed: ₹95 crore (widely reported; the page states none)"},
    2024: {"date": "2023-12-19", "kind": "mini", "currency": "INR", "purse": 100.0,
           "purse_src": "assumed: ₹100 crore (widely reported; the page lists purses left only)"},
    2025: {"date": "2024-11-24", "kind": "mega", "currency": "INR", "purse": 120.0,
           "purse_src": "2025 page: 'the auction purse for each franchise set at ₹120 crore'"},
    2026: {"date": "2025-12-16", "kind": "mini", "currency": "INR", "purse": 125.0,
           "purse_src": "2026 page: 'the auction purse for each franchise set at ₹125 crore'"},
}  # fmt: skip

# Every franchise name a page uses → one code per franchise (renames keep the code).
TEAM_CODES = {
    "Chennai Super Kings": "CSK",
    "Mumbai Indians": "MI",
    "Royal Challengers Bengaluru": "RCB",
    "Royal Challengers Bangalore": "RCB",
    "Kolkata Knight Riders": "KKR",
    "Delhi Capitals": "DC",
    "Delhi Daredevils": "DC",
    "Delhi Dardevils": "DC",  # a typo on the 2014 page
    "Punjab Kings": "PBKS",
    "Kings XI Punjab": "PBKS",
    "Sunrisers Hyderabad": "SRH",
    "Gujarat Titans": "GT",
    "Rajasthan Royals": "RR",
    "Lucknow Super Giants": "LSG",
    "Deccan Chargers": "DCH",
    "Kochi Tuskers Kerala": "KTK",
    "Pune Warriors India": "PWI",
    "Pune Warriors": "PWI",
    "Rising Pune Supergiants": "RPS",
    "Rising Pune Supergiant": "RPS",
    "Gujarat Lions": "GL",
}


def team_code(text: str | None) -> str | None:
    if not text:
        return None
    for name, code in sorted(TEAM_CODES.items(), key=lambda kv: -len(kv[0])):
        if name.lower() in text.lower():
            return code
    return None


# ---- HTML tables ----------------------------------------------------------------------------------


def _cell(td) -> dict:
    links = [a.get("title") for a in td.find_all("a") if a.get("title")]
    flag = None
    for t in links:
        if t.endswith(" national cricket team"):
            flag = t.removesuffix(" national cricket team")
            break
    if flag is None:
        img = td.find("img")
        if img is not None and img.get("alt"):
            flag = img.get("alt")
    name_link = next(
        (
            t
            for t in links
            if not t.endswith("national cricket team") and not t.startswith("Template:")
        ),
        None,
    )
    for sup in td.find_all("sup"):
        sup.decompose()
    return {
        "text": re.sub(r"\s+", " ", td.get_text(" ", strip=True)).strip(),
        "link": name_link,
        "flag": flag,
        "th": td.name == "th",
    }


def page_tables(html: str) -> list[dict]:
    """Every wikitable on a rendered page: {heads (section path), caption, rows} with rowspan /
    colspan expanded, each cell {text, link (first non-flag link title), flag, th}."""
    soup = BeautifulSoup(html, "lxml")
    out: list[dict] = []
    heads: list[tuple[int, str]] = []
    for el in soup.find_all(["h2", "h3", "h4", "table"]):
        if el.name != "table":
            lvl = int(el.name[1])
            heads = [h for h in heads if h[0] < lvl] + [(lvl, el.get_text(" ", strip=True))]
            continue
        if "wikitable" not in (el.get("class") or []):
            continue
        if any("wikitable" in (p.get("class") or []) for p in el.find_parents("table")):
            continue
        cap = el.find("caption")
        rows: list[list[dict]] = []
        pending: dict[int, tuple[int, dict]] = {}
        for tr in el.find_all("tr"):
            if tr.find_parent("table") is not el:
                continue
            tds = iter(tr.find_all(["td", "th"], recursive=False))
            row: list[dict] = []
            col = 0
            while True:
                if col in pending and pending[col][0] > 0:
                    n, c = pending[col]
                    row.append(c)
                    pending[col] = (n - 1, c)
                    col += 1
                    continue
                td = next(tds, None)
                if td is None:
                    break
                rs = int(re.sub(r"\D", "", td.get("rowspan") or "1") or 1)
                cs = int(re.sub(r"\D", "", td.get("colspan") or "1") or 1)
                c = _cell(td)
                for _ in range(cs):
                    row.append(c)
                    if rs > 1:
                        pending[col] = (rs - 1, c)
                    col += 1
            while col in pending and pending[col][0] > 0:
                n, c = pending[col]
                row.append(c)
                pending[col] = (n - 1, c)
                col += 1
            if row:
                rows.append(row)
        out.append(
            {
                "heads": [h[1] for h in heads],
                "caption": cap.get_text(" ", strip=True) if cap else None,
                "rows": rows,
            }
        )
    return out


# ---- money ----------------------------------------------------------------------------------------

_NUM = r"(\d[\d,]*(?:\.\d+)?)"


def money(text: str | None, header: str = "") -> tuple[float, str] | None:
    """A price cell → (amount, unit) with unit "cr" (₹ crore) or "usd" (US$). Bare numbers take
    their unit from the column header (₹ lakhs, US$ thousands, USD)."""
    if not text:
        return None
    t = text.replace("\xa0", " ")
    t = re.sub(r"\[[^\]]*\]", "", t)
    h = header.lower()
    m = re.search(r"₹\s*" + _NUM + r"\s*(crore|lakh|million)", t, re.I) or re.search(
        _NUM + r"\s*(crore|lakh)", t, re.I
    )
    if m:
        v = float(m.group(1).replace(",", ""))
        u = m.group(2).lower()
        return ({"crore": v, "lakh": v / 100.0, "million": v / 10.0}[u], "cr")
    m = re.search(r"(?:US)?\$\s*" + _NUM + r"\s*(million)?", t)
    if m:
        v = float(m.group(1).replace(",", ""))
        if m.group(2):
            v *= 1e6
        return (v, "usd")
    m = re.match(r"^\s*" + _NUM + r"\s*$", t)
    if not m:
        return None
    v = float(m.group(1).replace(",", ""))
    if "lakh" in h or "lacs" in h or "lac" in h:
        return (v / 100.0, "cr")
    if "crore" in h:
        return (v, "cr")
    if "thousand" in h and ("us" in h or "$" in h):
        return (v * 1000.0, "usd")
    if "usd" in h or "$" in h:
        return (v, "usd")
    return None


# ---- one page --------------------------------------------------------------------------------------

_PRICE_H = re.compile(r"auctioned price|winning bid|sold price|auctioned/retention|^salary", re.I)


def _clean_name(text: str) -> str:
    t = re.sub(r"\[[^\]]*\]", "", text)
    t = re.sub(r"[†‡*^#§]+", "", t)
    t = re.sub(r"\b(REP|REC(-[\d&]+)?|RTM)\b", "", t)
    return re.sub(r"\s+", " ", t).strip(" ,")


def _col(header: list[str], *pats: str, exclude: str | None = None) -> int | None:
    for p in pats:
        for i, h in enumerate(header):
            if re.search(p, h, re.I) and not (exclude and re.search(exclude, h, re.I)):
                return i
    return None


def _is_header(row: list[dict]) -> bool:
    return all(c["th"] for c in row) and len({c["text"] for c in row}) > 1


def _group_label(row: list[dict]) -> str | None:
    texts = {c["text"] for c in row}
    if len(texts) == 1 and len(row) > 1:
        return next(iter(texts))
    return None


def parse_page(season: int, html: str) -> dict:
    """One season's page → {"lots": [...], "retentions": [...]} (prices in crore or US$)."""
    a = AUCTIONS[season]
    lots: list[dict] = []
    rets: list[dict] = []
    for t in page_tables(html):
        heads = " > ".join(t["heads"])
        cap = t["caption"] or ""
        header: list[str] = []
        team_group: str | None = team_code(cap)
        set_label: str | None = None
        hl = heads.lower()
        is_auction = (
            ("auction" in hl or "sold" in hl)
            and "summary" not in hl
            and "support" not in hl
            and "withdrawn" not in hl
            and "team auction" not in hl
            and "retain" not in hl
            and "retention" not in hl
        )
        is_ret = (
            ("retain" in hl or "retention" in hl or "icon players" in hl or "draft" in hl)
            and "summary" not in cap.lower()
            and "salary cap" not in cap.lower()
        )
        if "under-19" in hl:
            is_ret, is_auction = True, False
        if not (is_auction or is_ret):
            continue
        for row in t["rows"]:
            if _is_header(row):
                header = [c["text"] for c in row]
                continue
            g = _group_label(row)
            if g is not None:
                if team_code(g):
                    team_group = team_code(g)
                else:
                    set_label = g
                continue
            if not header:
                continue
            cells = row + [{"text": "", "link": None, "flag": None, "th": False}] * max(
                0, len(header) - len(row)
            )
            i_name = _col(header, r"^name$", r"^player$", r"^players?\b")
            if i_name is None:
                break
            nm = cells[i_name]
            name = _clean_name(nm["text"])
            if not name or name.isdigit():
                continue
            i_nat = _col(header, r"^country$", r"^nationality$", r"^nat$")
            flag = (cells[i_nat]["flag"] or cells[i_nat]["text"]) if i_nat is not None else None
            flag = flag or nm["flag"]
            country = normalise(flag) if flag else None
            if is_auction:
                i_team = _col(
                    header, rf"{season}.*team", r"^team$", r"^franchise$", r"^ipl \d{4} team"
                )
                i_prev = _col(header, rf"{season - 1}.*team")
                i_price = _col(header, r"auctioned price", r"winning bid", r"sold price")
                i_base = _col(header, r"base price", r"reserve price")
                if i_team is None or i_price is None:
                    break
                tcell = cells[i_team]["text"]
                team = team_code(tcell)
                price = money(cells[i_price]["text"], header[i_price])
                base = money(cells[i_base]["text"], header[i_base]) if i_base is not None else None
                sold = bool(team) and price is not None
                i_role = _col(header, r"playing role", r"speciality", r"^role$")
                i_cap = _col(header, r"capped")
                if i_cap is None and season >= 2014:
                    i_cap = _col(header, r"^category$")
                i_set = _col(header, r"^set$")
                i_m = _col(header, r"ipl matches")
                lots.append(
                    {
                        "season": season,
                        "name": name,
                        "wiki_title": nm["link"],
                        "country": country,
                        "role_text": cells[i_role]["text"] if i_role is not None else None,
                        "capped_text": cells[i_cap]["text"] if i_cap is not None else None,
                        "ipl_matches_text": cells[i_m]["text"] if i_m is not None else None,
                        "set": (cells[i_set]["text"] if i_set is not None else None) or set_label,
                        "team": team,
                        "prev_team": team_code(cells[i_prev]["text"])
                        if i_prev is not None
                        else None,
                        "rtm": "RTM" in tcell,
                        "sold": sold,
                        "_price": price,
                        "_base": base,
                        "table": heads,
                    }
                )
            else:
                i_sal = _col(
                    header,
                    r"^salary",
                    r"^price",
                    r"highest bid",
                    exclude=r"before",
                )
                if "icon" in hl:
                    i_sal = _col(header, r"^salary")
                i_ded = _col(header, r"purse deduction")
                i_team = _col(header, r"^team$")
                team = team_code(cells[i_team]["text"]) if i_team is not None else team_group
                sal = money(cells[i_sal]["text"], header[i_sal]) if i_sal is not None else None
                ded = money(cells[i_ded]["text"], header[i_ded]) if i_ded is not None else None
                kind = (
                    "icon"
                    if "icon" in hl
                    else "u19_draft"
                    if "under-19" in hl
                    else "draft"
                    if "draft" in hl
                    else "retained"
                )
                rets.append(
                    {
                        "season": season,
                        "kind": kind,
                        "team": team,
                        "name": name,
                        "wiki_title": nm["link"],
                        "country": country,
                        "_salary": sal,
                        "_deduction": ded,
                        "table": heads,
                    }
                )
    del a
    return {"lots": lots, "retentions": rets}


# ---- exchange rates ---------------------------------------------------------------------------------


def load_fx() -> dict[str, float]:
    with FX_CSV.open(encoding="utf-8") as f:
        return {r["date"]: float(r["inr_per_usd"]) for r in csv.DictReader(f)}


def fx_on(fx: dict[str, float], date: str) -> tuple[float, str]:
    """The H.10 rate on `date`, or the last business day before it."""
    d = dt.date.fromisoformat(date)
    for _ in range(10):
        if d.isoformat() in fx:
            return fx[d.isoformat()], d.isoformat()
        d -= dt.timedelta(days=1)
    raise KeyError(date)


def _to_cr(m: tuple[float, str] | None, rate: float | None) -> tuple[float | None, float | None]:
    """(crore, US$) from a parsed amount."""
    if m is None:
        return None, None
    v, u = m
    if u == "cr":
        return round(v, 4), None
    if rate is None:
        return None, v
    return round(v * rate / 1e7, 4), v


# ---- matching ----------------------------------------------------------------------------------------


FUZZY_MIN = 88  # rapidfuzz token-sort score (0-100) for a spelling variant
FUZZY_GAP = 4  # ... and no other IPL player within this many points of it


class Matcher:
    """Wikipedia title → Cricsheet id, then a unique name, then initial + surname (IPL players)."""

    def __init__(self, pm: dict[str, dict]):
        self.title: dict[str, str] = {}
        self.names: dict[str, set[str]] = {}
        self.initials: dict[str, set[str]] = {}
        for cid, r in pm.items():
            if not isinstance(r, dict):
                continue
            if r.get("wikipedia_title"):
                self.title[r["wikipedia_title"].lower()] = cid
            ns = {r.get(k) for k in ("display_name", "full_name", "scorecard_name")} | set(
                r.get("aliases") or []
            )
            for n in ns:
                if n:
                    self.names.setdefault(_fold(n), set()).add(cid)
            if "ipl" in (r.get("leagues") or {}):
                for n in ns:
                    k = master.initial_key(n or "")
                    if k:
                        self.initials.setdefault(k, set()).add(cid)
        self.pm = pm
        self._ipl_names: dict[str, set[str]] | None = None

    def __call__(self, name: str, title: str | None) -> tuple[str | None, str | None]:
        if title and title.lower() in self.title:
            return self.title[title.lower()], "wikipedia_title"
        for key in (title, name):
            if not key:
                continue
            c = self.names.get(_fold(re.sub(r"\s*\(.*\)$", "", key)), set())
            if len(c) == 1:
                return next(iter(c)), "name"
            ipl = {x for x in c if "ipl" in (self.pm[x].get("leagues") or {})}
            if len(ipl) == 1:
                return next(iter(ipl)), "name_ipl"
        k = master.initial_key(name)
        c = self.initials.get(k or "", set())
        if len(c) == 1:
            return next(iter(c)), "initial_surname_ipl"
        # a spelling variant (Chakaravarthy / Chakravarthy, Prab Simran / Prabhsimran): the closest
        # IPL player's name, only when it is close and clearly closer than the next one
        from rapidfuzz import fuzz, process

        if self._ipl_names is None:
            self._ipl_names = {
                n: cids
                for n, cids in self.names.items()
                if any("ipl" in (self.pm[x].get("leagues") or {}) for x in cids)
            }
        hits = process.extract(
            _fold(name), list(self._ipl_names), scorer=fuzz.token_sort_ratio, limit=5
        )
        if hits and hits[0][1] >= FUZZY_MIN:
            best = self._ipl_names[hits[0][0]]
            others = {
                x for h in hits[1:] if h[1] >= hits[0][1] - FUZZY_GAP for x in self._ipl_names[h[0]]
            }
            ipl = {x for x in best if "ipl" in (self.pm[x].get("leagues") or {})}
            if len(ipl) == 1 and not (others - ipl):
                return next(iter(ipl)), "fuzzy_ipl"
        return None, None


def _fold(s: str) -> str:
    import unicodedata

    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z ]", "", s.lower().replace(".", " ")).strip()


# ---- fetch -----------------------------------------------------------------------------------------


def fetch_pages() -> None:
    PAGES.mkdir(parents=True, exist_ok=True)
    with sources._client() as cx:
        for y in range(FIRST, LAST + 1):
            title = page_title(y)
            text, rev = sources.fetch_ipl_personnel_text(title)
            (PAGES / f"{y}.wiki").write_text(text, encoding="utf-8")
            r = sources._get_with_retry(
                cx,
                sources.WIKIPEDIA_API,
                {
                    "action": "parse",
                    "oldid": rev["revid"],
                    "prop": "text",
                    "format": "json",
                    "formatversion": "2",
                    "disablelimitreport": 1,
                },
                "parse",
            )
            (PAGES / f"{y}.html").write_text(r.json()["parse"]["text"], encoding="utf-8")
            meta = {
                "title": title,
                "revid": rev["revid"],
                "ts": rev["ts"],
                "url": "https://en.wikipedia.org/wiki/" + title.replace(" ", "_"),
            }
            (PAGES / f"{y}.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
            time.sleep(1)


@app.command()
def run(
    fetch: bool = typer.Option(False, "--fetch", help="Re-download the Wikipedia pages first."),
) -> None:
    if fetch:
        fetch_pages()
    fx = load_fx()
    pm = master.load()
    match = Matcher(pm)
    old = sources.read_json(OUT, {})
    kept = {
        (r["season"], r.get("kind", "auction"), r.get("wiki_title") or r["name"]): r
        for r in (old.get("lots") or []) + (old.get("retentions") or [])
        if r.get("edited")
    }
    auctions: dict[str, dict] = {}
    lots: list[dict] = []
    rets: list[dict] = []
    for y in range(FIRST, LAST + 1):
        meta = json.loads((PAGES / f"{y}.json").read_text(encoding="utf-8"))
        a = dict(AUCTIONS[y])
        rate = None
        if a["currency"] == "USD":
            rate, on = fx_on(fx, a["date"])
            a["fx_inr_per_usd"] = rate
            a["fx_date"] = on
            a["purse_cr"] = round(a["purse"] * 1e6 * rate / 1e7, 3)
        else:
            a["purse_cr"] = a["purse"]
        a["page"] = {k: meta[k] for k in ("title", "revid", "ts", "url")}
        auctions[str(y)] = a
        got = parse_page(y, (PAGES / f"{y}.html").read_text(encoding="utf-8"))
        seen: set[tuple] = set()
        for r in got["lots"]:
            price_cr, price_usd = _to_cr(r.pop("_price"), rate)
            base_cr, base_usd = _to_cr(r.pop("_base"), rate)
            key = (y, r["wiki_title"] or r["name"], r["team"], price_cr)
            if key in seen:  # the same lot listed twice (e.g. a set table and a summary)
                continue
            seen.add(key)
            cid, how = match(r["name"], r["wiki_title"])
            if not r["country"] and cid:  # the page has no nationality column that year
                r["country"] = normalise((pm.get(cid) or {}).get("country"))
                r["country_from"] = "player_master"
            row = {
                **r,
                "kind": "auction",
                "base_price_cr": base_cr,
                "price_cr": price_cr if r["sold"] else None,
                "base_usd": base_usd,
                "price_usd": price_usd if r["sold"] else None,
                "cricsheet_id": cid,
                "match": how,
            }
            k = (y, "auction", r["wiki_title"] or r["name"])
            lots.append(kept.pop(k, row))
        for r in got["retentions"]:
            sal_cr, sal_usd = _to_cr(r.pop("_salary"), rate)
            ded_cr, _ = _to_cr(r.pop("_deduction"), rate)
            cid, how = match(r["name"], r["wiki_title"])
            if not r["country"] and cid:
                r["country"] = normalise((pm.get(cid) or {}).get("country"))
                r["country_from"] = "player_master"
            row = {
                **r,
                "salary_cr": sal_cr,
                "salary_usd": sal_usd,
                "purse_deduction_cr": ded_cr if ded_cr != sal_cr else None,
                "cricsheet_id": cid,
                "match": how,
            }
            k = (y, r["kind"], r["wiki_title"] or r["name"])
            rets.append(kept.pop(k, row))
    # hand-added rows that no longer come from a page
    for k, r in kept.items():
        (lots if k[1] == "auction" else rets).append(r)

    cov: dict[str, dict] = {}
    for y in range(FIRST, LAST + 1):
        ls = [r for r in lots if r["season"] == y]
        rs = [r for r in rets if r["season"] == y]
        cov[str(y)] = {
            "lots": len(ls),
            "sold": sum(1 for r in ls if r["sold"]),
            "sold_matched": sum(1 for r in ls if r["sold"] and r["cricsheet_id"]),
            "sold_with_base": sum(1 for r in ls if r["sold"] and r["base_price_cr"] is not None),
            "retentions": len(rs),
            "retentions_with_salary": sum(1 for r in rs if r["salary_cr"] is not None),
            "retentions_matched": sum(1 for r in rs if r["cricsheet_id"]),
        }
    out = {
        "_source": (
            "Wikipedia, the per-season 'List of <year> Indian Premier League personnel changes' "
            "pages (2008: '... auctions and personnel signings'), CC BY-SA 4.0, each read at the "
            "revision in `auctions.<year>.page`. US$ prices (2008-2013) converted at the auction "
            "day's rate: " + FX_SOURCE
        ),
        "_licence": "CC BY-SA 4.0 (derived from Wikipedia); share-alike applies to this file",
        "_note": (
            'Parsed by scripts/ipl_auction_history.py. Edit a row by hand and set "edited": true '
            "to keep it through a re-parse. Prices in crore (₹10 million); 'sold' lists come from "
            "the pages' sold-player tables, so unsold lots are mostly absent."
        ),
        "auctions": auctions,
        "coverage": cov,
        "lots": lots,
        "retentions": rets,
        "unmatched": sorted(
            {
                f"{r['season']}: {r['name']}"
                for r in lots + rets
                if not r.get("cricsheet_id") and (r.get("sold") or r.get("kind") != "auction")
            }
        ),
    }
    sources.write_json(OUT, out)
    tot_sold = sum(c["sold"] for c in cov.values())
    tot_m = sum(c["sold_matched"] for c in cov.values())
    tot_r = sum(c["retentions"] for c in cov.values())
    tot_rm = sum(c["retentions_matched"] for c in cov.values())
    print(json.dumps(cov, indent=1))
    print(f"sold lots {tot_sold}, matched {tot_m} ({100 * tot_m / max(tot_sold, 1):.1f}%)")
    print(f"retentions {tot_r}, matched {tot_rm} ({100 * tot_rm / max(tot_r, 1):.1f}%)")


if __name__ == "__main__":
    app()
