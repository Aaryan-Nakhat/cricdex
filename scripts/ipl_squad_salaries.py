"""Add each IPL player's salary to the current squads file, and his Cricsheet id.

Reads Wikipedia's "List of 2026 Indian Premier League personnel changes" (CC BY-SA 4.0): the
retained lists carry each player's contract (2025 auction / retention price, or the price a trade
moved with him), the sold tables the 2026 auction price, the withdrawn table each replacement's fee,
and the traded table who arrived by trade. Every row of `data/curated/ipl_squads_2026.json` gets:

- `salary_cr`  his salary in crore (₹30 lakh = 0.3)
- `acquired`   retained | trade | auction | replacement
- `country`    nationality code from the page's flag (else the player master's)
- `overseas`   country isn't India
- `cricsheet_id` matched through the player master (team + Wikipedia title, then the names)

Then the next cycle's page ("List of 2027 Indian Premier League personnel changes") is read for
moves since the 2026 season: a traded player moves to his new squad at the fee the trade set
(`acquired = "trade"`, `trade` = {from, salary_before_cr}), and a retired player is marked
`retired` (he leaves the retention list). Both are recorded in `changes_since_season`.

Hand edits win: a field already in the file is kept unless `--force`. Unmatched players are listed
at the end and in the file's `_unmatched`, so they can be settled by hand (add `cricsheet_id`).

Run:
    uv run python scripts/ipl_squad_salaries.py            # fetch the page, fill what's missing
    uv run python scripts/ipl_squad_salaries.py --force    # refill every salary field
    uv run python scripts/ipl_squad_salaries.py --wikitext page.wiki   # parse a saved copy
"""

from __future__ import annotations

import json
from pathlib import Path

import typer

from cricdex.scout.identity import master, sources
from cricdex.scout.identity.countries import normalise

app = typer.Typer(add_completion=False)

FIELDS = ("salary_cr", "acquired", "country", "overseas")


def _match_cid(code: str, row: dict, by_team: dict[str, list[tuple[str, dict]]]) -> str | None:
    """Player master record in the same squad: Wikipedia title first, then any known name."""
    title = (row.get("wiki_title") or "").lower()
    name = (row.get("name") or "").lower()
    cands = by_team.get(code, [])
    for cid, rec in cands:
        if (rec.get("wikipedia_title") or "").lower() == title and title:
            return cid
    for cid, rec in cands:
        names = {
            (rec.get(k) or "").lower() for k in ("display_name", "full_name", "scorecard_name")
        } | {a.lower() for a in rec.get("aliases") or []}
        if name and name in names:
            return cid
    return None


@app.command()
def run(
    force: bool = typer.Option(
        False, "--force", help="Overwrite salary fields already in the file."
    ),
    wikitext: Path | None = typer.Option(None, "--wikitext", help="Parse this saved page instead."),
    next_wikitext: Path | None = typer.Option(
        None, "--next-wikitext", help="Parse this saved copy of the next cycle's page instead."
    ),
) -> None:
    squads = sources.read_json(sources.IPL_SQUADS, {})
    if not squads.get("squads"):
        raise typer.BadParameter("no squads file yet: run scripts/build_player_master.py first")
    if wikitext:
        text, rev = wikitext.read_text(encoding="utf-8"), {"revid": None, "ts": None}
    else:
        text, rev = sources.fetch_ipl_personnel_text()
    parsed = sources.parse_ipl_salaries(text)
    pm = master.load()
    by_team: dict[str, list[tuple[str, dict]]] = {}
    for cid, rec in pm.items():
        if rec.get("team"):
            by_team.setdefault(rec["team"], []).append((cid, rec))

    unmatched: list[dict] = []
    no_salary: list[str] = []
    for code, rows in squads["squads"].items():
        page = parsed["players"].get(code, {})
        for row in rows:
            got = page.get(row.get("wiki_title") or "", {})
            if not row.get("cricsheet_id"):
                cid = _match_cid(code, row, by_team)
                if cid:
                    row["cricsheet_id"] = cid
            rec = pm.get(row.get("cricsheet_id") or "", {})
            country = got.get("country") or normalise(rec.get("country"))
            vals = {
                "salary_cr": got.get("salary_cr"),
                "acquired": got.get("acquired")
                or {"bought": "auction", "replacement": "replacement"}.get(row.get("status"), None),
                "country": country,
                "overseas": (country != "IND") if country else None,
            }
            for k in FIELDS:
                # a salary corrected by hand against another source carries `salary_note`: it
                # stays even with --force (e.g. Vipraj Nigam, 0.5 not Wikipedia's 0.3; issue I6)
                if k == "salary_cr" and row.get("salary_note") and row.get(k) is not None:
                    continue
                if vals[k] is not None and (force or row.get(k) is None):
                    row[k] = vals[k]
            if row.get("salary_cr") is None:
                no_salary.append(f"{code}: {row.get('name')}")
            if not row.get("cricsheet_id"):
                unmatched.append({"team": code, "name": row.get("name")})
    # (`purse_check_2026` — the published purses, retention-slab charges and post-auction figures —
    # is hand-kept in the file and left as it is)
    squads["trades"] = parsed["trades"]

    # ---- moves since the season: the next cycle's trades and retirements
    if next_wikitext:
        ntext, nrev = next_wikitext.read_text(encoding="utf-8"), {"revid": None, "ts": None}
    else:
        ntext, nrev = sources.fetch_ipl_personnel_text(sources.IPL_NEXT_PERSONNEL_PAGE)
    moves = sources.parse_ipl_salaries(ntext)["trades"]
    retired = sources.parse_ipl_personnel(ntext)["retired"]
    applied: list[dict] = []
    for t in moves:
        src, dst = t.get("from"), t.get("to")
        if not src or not dst:
            continue
        rows = squads["squads"].get(src, [])
        row = next((r for r in rows if r.get("wiki_title") == t["wiki_title"]), None)
        if row is None:  # already applied (he's in the new squad) or not on our list
            continue
        rows.remove(row)
        row["trade"] = {"from": src, "salary_before_cr": row.get("salary_cr")}
        if t.get("salary_cr") is not None:
            row["salary_cr"] = t["salary_cr"]
        row["acquired"] = "trade"
        squads["squads"].setdefault(dst, []).append(row)
        applied.append({"kind": "trade", **t})
    for r in retired:
        for row in squads["squads"].get(r.get("team") or "", []):
            if row.get("wiki_title") == r.get("wiki_title") and not row.get("retired"):
                row["retired"] = r.get("date") or True
                applied.append({"kind": "retired", **r})
    prev = squads.get("changes_since_season") or {}
    squads["changes_since_season"] = {
        "_source": (
            f"Wikipedia, '{sources.IPL_NEXT_PERSONNEL_PAGE}' (CC BY-SA 4.0)"
            + (f", revision {nrev['revid']} of {nrev['ts']}" if nrev.get("revid") else "")
            + ": https://en.wikipedia.org/wiki/"
            + sources.IPL_NEXT_PERSONNEL_PAGE.replace(" ", "_")
        ),
        "applied": (prev.get("applied") or []) + applied,
    }
    squads["_salary_source"] = (
        f"Wikipedia, '{sources.IPL_PERSONNEL_PAGE}' (CC BY-SA 4.0)"
        + (f", revision {rev['revid']} of {rev['ts']}" if rev.get("revid") else "")
        + ": retained-list salaries, auction prices (lakhs / 100), replacement fees and the traded "
        "table. https://en.wikipedia.org/wiki/" + sources.IPL_PERSONNEL_PAGE.replace(" ", "_")
    )
    squads["_unmatched"] = unmatched
    sources.write_json(sources.IPL_SQUADS, squads)
    n = sum(len(r) for r in squads["squads"].values())
    print(
        json.dumps(
            {
                "players": n,
                "with_salary": n - len(no_salary),
                "matched": n - len(unmatched),
                "unmatched": unmatched,
                "no_salary": no_salary,
            },
            indent=1,
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    app()
