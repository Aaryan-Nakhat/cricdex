"""Monthly English Wikipedia pageviews of every player article, for the market price's brand feature.

A player's public following is part of what the IPL market pays for (METHODOLOGY §6b): the released
Indian icons and the stars franchises keep are priced by their fame as well as their numbers. The one
dated, public, reproducible measure of that following we have is how often people read his Wikipedia
article. The Wikimedia Pageviews API (https://wikimedia.org/api/rest_v1/, data from July 2015, CC0)
gives the monthly views of an article by human readers ("user" agent, all access), so the views in the
twelve months before any auction since 2017 are known as of that auction (no leakage).

Reads the titles from the player master (`wikipedia_title`) and the auction record (`wiki_title`), and
writes `data/curated/wiki_pageviews.json`: {"_note", "first_month": "2015-07", "last_month",
"views": {title: [monthly views from first_month]}}. A title the API doesn't know (a redirect or a
moved page) gets no entry. Polite: one request per title, about 150 a minute, with a User-Agent that
names the tool and its project page (Wikimedia's User-Agent policy and rate limits).

    uv run python scripts/wiki_pageviews.py            # fetch what's missing
    uv run python scripts/wiki_pageviews.py --refresh  # every title again (new months)
"""

from __future__ import annotations

import datetime as dt
import json
import time
import urllib.error
import urllib.parse
import urllib.request

import typer

from cricdex.config import DATA_DIR
from cricdex.scout.identity import master

app = typer.Typer(add_completion=False)

OUT = DATA_DIR / "curated" / "wiki_pageviews.json"
HISTORY = DATA_DIR / "curated" / "ipl_auction_history.json"
FIRST = "2015-07"
API = (
    "https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/en.wikipedia/all-access/user/"
    "{title}/monthly/2015070100/{end}0100"
)
# Wikimedia's User-Agent policy: a tool name and a way to contact its maintainer (here the project
# page). A compliant agent may make up to 200 requests a minute; one without contact details 10.
UA = "CricDex/1.0 (https://github.com/Aaryan-Nakhat/cricdex; player pageviews for a price model)"
PAUSE = 0.4  # seconds between requests: about 150 a minute, under the limit


def _months(first: str, last: str) -> list[str]:
    y, m = int(first[:4]), int(first[5:7])
    out = []
    while f"{y:04d}-{m:02d}" <= last:
        out.append(f"{y:04d}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def titles() -> list[str]:
    """Every title, the IPL's first (the auction record's players and anyone with an IPL match: the
    price fit and the auction pool need them), then the rest (Scout's other-league rows)."""
    first, rest = set(), set()
    hist = json.loads(HISTORY.read_text(encoding="utf-8"))
    for r in hist["lots"] + hist["retentions"]:
        if r.get("wiki_title"):
            first.add(r["wiki_title"])
    for rec in master.load().values():
        if isinstance(rec, dict) and rec.get("wikipedia_title"):
            ipl = "ipl" in (rec.get("leagues") or {})
            (first if ipl else rest).add(rec["wikipedia_title"])
    return sorted(first) + sorted(rest - first)


def _fetch(title: str, last: str) -> list[int] | None:
    t = urllib.parse.quote(title.replace(" ", "_"), safe="")
    url = API.format(title=t, end=last.replace("-", ""))
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                items = json.loads(resp.read().decode("utf-8")).get("items") or []
            break
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            if e.code == 429:  # over the rate limit: wait as told (or a minute)
                time.sleep(float(e.headers.get("retry-after") or 60))
                continue
            time.sleep(2.0 * (attempt + 1))
        except (urllib.error.URLError, TimeoutError):
            time.sleep(2.0 * (attempt + 1))
    else:
        typer.echo(f"pageviews: {title} failed four times; skipped (rerun to retry)")
        return []
    by = {f"{i['timestamp'][:4]}-{i['timestamp'][4:6]}": int(i["views"]) for i in items}
    return [by.get(m, 0) for m in _months(FIRST, last)]


@app.command()
def main(refresh: bool = typer.Option(False, "--refresh")) -> None:
    today = dt.date.today()
    lm = today.replace(day=1) - dt.timedelta(days=1)  # the last complete month
    last = f"{lm.year:04d}-{lm.month:02d}"
    have = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}
    views: dict = {} if refresh or have.get("last_month") != last else dict(have.get("views") or {})
    missing_before = set(have.get("missing") or []) if not refresh else set()
    todo = [t for t in titles() if t not in views and t not in missing_before]
    missing = sorted(missing_before)
    typer.echo(f"{len(todo)} titles to fetch (through {last})")
    for i, t in enumerate(todo):
        v = _fetch(t, last)
        if v is None:
            missing.append(t)
        elif v:
            views[t] = v
        time.sleep(PAUSE)
        if (i + 1) % 100 == 0 or i + 1 == len(todo):
            _write(views, sorted(set(missing)), last)
            typer.echo(f"{i + 1}/{len(todo)}")
    _write(views, sorted(set(missing)), last)


def _write(views: dict, missing: list[str], last: str) -> None:
    OUT.write_text(
        json.dumps(
            {
                "_note": "Monthly English Wikipedia pageviews (human readers, all access) of each "
                "player article, from the Wikimedia Pageviews API (CC0), by scripts/wiki_pageviews.py. "
                "`views[title][i]` is month first_month + i. `missing`: titles the API does not know.",
                "first_month": FIRST,
                "last_month": last,
                "views": views,
                "missing": missing,
            },
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    app()
