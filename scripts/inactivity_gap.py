"""How often a player comes back after N years without a T20 match: the evidence for the auction
pool's activity rule (scripts/export_site.py AUCTION_RECENCY_DAYS, METHODOLOGY §7).

Every spell between two matches of a player in the pool leagues (the playing-time usage table:
every XI of every covered league), and the open spell after his last match, that began by
`--last-start` (so a 4-year gap is observable before the data ends). For N = 1 … 4 years: of the spells
that lasted at least N years, the share in which he played again anywhere, and the share in which he
played an IPL match again (counted from N years after the spell began), for every player and for
players who had played the IPL before the spell. Returns after the Indian domestic T20 data stops
(Dec 2024) are invisible, so "anywhere" is a floor; the IPL share is exact.

    uv run python scripts/inactivity_gap.py                 # prints the table, writes the report
"""

from __future__ import annotations

import bisect
import datetime as dt
import json

import polars as pl
import typer

from cricdex.config import DATA_DIR

app = typer.Typer(add_completion=False)
USAGE = DATA_DIR / "metrics" / ".playing_time" / "usage.parquet"
OUT = DATA_DIR / "metrics" / "inactivity_gap_ipl.json"
GAPS = (1.0, 1.5, 2.0, 2.5, 3.0, 4.0)


@app.command()
def run(
    last_start: str = typer.Option("2021-09-30", help="Spells beginning on or before this date."),
) -> None:
    if not USAGE.exists():
        raise typer.BadParameter(f"{USAGE} missing: run scripts/playing_time_fit.py first")
    u = pl.read_parquet(USAGE)
    end = max(u["date"].to_list())
    d = (
        u.select("cid", pl.col("date").str.to_date().alias("d"))
        .unique()
        .sort(["cid", "d"])
        .with_columns(pl.col("d").shift(-1).over("cid").alias("next"))
    )
    end_d = dt.date.fromisoformat(end[:10])
    d = d.with_columns(
        pl.col("next").is_not_null().alias("back"),
        ((pl.col("next").fill_null(end_d) - pl.col("d")).dt.total_days() / 365.25).alias("gap"),
    ).filter(pl.col("d") <= dt.date.fromisoformat(last_start))
    ipl: dict[str, list] = {
        cid: sorted(ds)
        for cid, ds in u.filter(pl.col("league") == "ipl")
        .select("cid", pl.col("date").str.to_date())
        .group_by("cid")
        .agg(pl.col("date"))
        .iter_rows()
    }
    rows = []
    for n in GAPS:
        s = d.filter(pl.col("gap") >= n)
        tot = {"all": [0, 0, 0], "ipl_before": [0, 0, 0]}
        for cid, d0, back in s.select("cid", "d", "back").iter_rows():
            ds = ipl.get(cid) or []
            k = bisect.bisect_left(ds, d0 + dt.timedelta(days=round(n * 365.25)))
            again = k < len(ds)
            for key in ("all", "ipl_before") if ds and ds[0] <= d0 else ("all",):
                t = tot[key]
                t[0] += 1
                t[1] += int(back)
                t[2] += int(again)
        row = {"years": n}
        for key, (m, b, a) in tot.items():
            row[key] = {"spells": m, "played_again": round(b / m, 4) if m else None,
                        "ipl_again": round(a / m, 4) if m else None}  # fmt: skip
        rows.append(row)
        print(f"N={n}: all {tot['all'][0]} spells, again {row['all']['played_again']:.1%}, IPL again "
              f"{row['all']['ipl_again']:.2%} | former IPL players {tot['ipl_before'][0]}, again "
              f"{row['ipl_before']['played_again']:.1%}, IPL again {row['ipl_before']['ipl_again']:.2%}")  # fmt: skip
    OUT.write_text(json.dumps({"data_to": end[:10], "spells_from_before": last_start, "rows": rows},
                              indent=1), encoding="utf-8")  # fmt: skip
    print(f"wrote {OUT}")


if __name__ == "__main__":
    app()
