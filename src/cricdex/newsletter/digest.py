"""Daily newsletter digest.

Compiles a Markdown digest pulling from:
  - records.queries (top-of-record headline + on-this-day)
  - reports.match_report (latest match in the collection)
  - records.queries.career_run_leaders / career_wicket_leaders for
    headline leaderboards

Output: `data/newsletters/<date>_<collection>.md`. Email send is wired
through Resend in the future — for now the digest is a flat file the
user can preview, copy, or pipe into any delivery channel.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import duckdb
import httpx
import polars as pl
from loguru import logger

from cricdex.config import DATA_DIR, settings
from cricdex.records import queries
from cricdex.reports import match_report

DUCKDB_PATH = DATA_DIR / "cricsheet" / "cricsheet.duckdb"
RESEND_URL = "https://api.resend.com/emails"


def _latest_match_id(collection: str) -> str | None:
    safe = collection.replace("-", "_")
    if not DUCKDB_PATH.exists():
        return None
    con = duckdb.connect(str(DUCKDB_PATH), read_only=True)
    try:
        tables = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
        if f"matches_{safe}" not in tables:
            return None
        row = con.execute(
            f"""
            SELECT match_id
            FROM matches_{safe}
            WHERE match_date IS NOT NULL
            ORDER BY TRY_CAST(match_date AS DATE) DESC NULLS LAST
            LIMIT 1
            """
        ).fetchone()
        return row[0] if row else None
    finally:
        con.close()


def _render_df_md(df: pl.DataFrame, head: int = 5) -> str:
    if df.is_empty():
        return "_(no rows)_"
    pdf = df.head(head).to_pandas()
    return pdf.to_markdown(index=False)


def compile(
    collection: str = "ipl",
    as_of: dt.date | None = None,
    out_dir: Path | None = None,
    include_match_report: bool = True,
) -> Path:
    as_of = as_of or dt.date.today()
    out_dir = out_dir or (DATA_DIR / "newsletters")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{as_of.isoformat()}_{collection}.md"

    parts: list[str] = []
    parts.append(f"# CricDex Digest — {collection} — {as_of.isoformat()}\n")
    parts.append(
        "_Auto-compiled from Cricsheet ball-by-ball + the metrics + records "
        "pipelines. Every number is reproducible from the public corpus._\n"
    )

    # On-this-day
    parts.append(f"## 🗓️ On this day ({as_of.strftime('%d %b')})\n")
    otd = queries.on_this_day(month=as_of.month, day=as_of.day, collection=collection, top_n=10)
    parts.append(_render_df_md(otd, head=10))
    parts.append("")

    # Headline records
    parts.append("## 🏆 Headlines\n")
    sections = [
        ("Highest individual innings", queries.highest_individual_innings),
        ("Fastest fifty (balls)", queries.fastest_fifty),
        ("Most sixes in an innings", queries.most_sixes_innings),
        ("Best bowling figures", queries.best_bowling_innings),
        ("Career run leaders", queries.career_run_leaders),
        ("Career wicket leaders", queries.career_wicket_leaders),
    ]
    for title, fn in sections:
        parts.append(f"### {title}\n")
        try:
            parts.append(_render_df_md(fn(collection, top_n=5)))
        except Exception as e:
            parts.append(f"_(query failed: {e})_")
        parts.append("")

    # Latest match report
    if include_match_report:
        latest = _latest_match_id(collection)
        if latest:
            parts.append(f"## 📰 Latest match — {latest}\n")
            try:
                report_path = match_report.generate(match_id=latest, collection=collection)
                parts.append(report_path.read_text())
            except Exception as e:
                parts.append(f"_(report generation failed: {e})_")
        else:
            parts.append("## 📰 Latest match\n_(no matches ingested)_")

    out_path.write_text("\n".join(parts))
    return out_path


def _markdown_to_html(md: str) -> str:
    """Lean Markdown → HTML for the Resend payload. Covers the digest's
    surface: headers, paragraphs, table-shaped rows from to_markdown."""
    out: list[str] = []
    for line in md.splitlines():
        if line.startswith("# "):
            out.append(f"<h1>{line[2:]}</h1>")
        elif line.startswith("## "):
            out.append(f"<h2>{line[3:]}</h2>")
        elif line.startswith("### "):
            out.append(f"<h3>{line[4:]}</h3>")
        elif line.startswith("|") and line.endswith("|"):
            out.append(f"<pre>{line}</pre>")
        elif line.strip() == "":
            out.append("<br/>")
        else:
            out.append(f"<p>{line}</p>")
    return "\n".join(out)


def send_via_resend(
    markdown_path: Path,
    to: list[str],
    subject: str,
    api_key: str | None = None,
    from_addr: str | None = None,
    timeout: float = 30.0,
) -> dict:
    """POST the rendered digest to the Resend API."""
    api_key = api_key or settings.resend_api_key
    from_addr = from_addr or settings.resend_from
    if not api_key:
        raise RuntimeError(
            "RESEND_API_KEY is empty — drop a personal Resend key into "
            "`.env` (free tier 3,000/month) and retry."
        )
    md_text = markdown_path.read_text()
    payload = {
        "from": from_addr,
        "to": to,
        "subject": subject,
        "text": md_text,
        "html": _markdown_to_html(md_text),
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    with httpx.Client(timeout=timeout) as cx:
        r = cx.post(RESEND_URL, headers=headers, json=payload)
    r.raise_for_status()
    body = r.json()
    logger.info(f"resend accepted digest (id={body.get('id')})")
    return body
