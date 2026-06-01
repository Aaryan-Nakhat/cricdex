"""Rich rendering helpers — Panels, headers, metric blocks, Wikidata
chip row, etc. Used by every CLI subcommand to keep the terminal UI
at parity with the Streamlit dashboard.

The plain `_shared.render_table` / `_shared.render_kv` are kept for
back-compat; new code should prefer the helpers in this module.
"""

from __future__ import annotations

import datetime as _dt
from typing import Any

from cricdex.cli._shared import console

# ---------- panels ------------------------------------------------------


def header(title: str, subtitle: str | None = None) -> None:
    """Big bold page title + optional dim subtitle, with a rule under it."""
    c = console()
    c.print()
    c.print(f"[bold bright_cyan]{title}[/bold bright_cyan]")
    if subtitle:
        c.print(f"[dim]{subtitle}[/dim]")
    c.rule(style="cyan")


def intro_panel(text: str, title: str | None = "About") -> None:
    """Dim explainer block at the top of a command output."""
    from rich.panel import Panel

    console().print(
        Panel(
            text,
            title=f"[dim]{title}[/dim]" if title else None,
            title_align="left",
            border_style="dim",
            padding=(0, 1),
        )
    )


def section(title: str) -> None:
    """Bold inline section heading."""
    console().print(f"\n[bold]{title}[/bold]")


def footnote(text: str) -> None:
    """Dim italic note printed after a block — used for thresholds /
    refresh hints / methodology pointers."""
    console().print(f"[dim italic]{text}[/dim italic]")


def hint(text: str) -> None:
    """Dim 'tip:' line — used by render_table footers."""
    console().print(f"[dim]tip: {text}[/dim]")


# ---------- progress + sparklines --------------------------------------


def spinner(message: str):
    """Context manager: shows an animated dot-clock while a slow operation
    runs, then clears on exit. Use for compute / network steps that block
    for >1s — e.g. `with spinner("loading metrics"): ...`."""
    return console().status(f"[cyan]{message}[/cyan]", spinner="dots")


_SPARK_BARS = "▁▂▃▄▅▆▇█"


def sparkline(values: list[float]) -> str:
    """8-glyph Unicode sparkline. Maps len(values) numbers into the 8
    block characters proportionally; clamps to min/max so a flat line
    renders as the lowest glyph."""
    nums = [v for v in values if isinstance(v, int | float)]
    if not nums:
        return ""
    lo = min(nums)
    hi = max(nums)
    span = (hi - lo) or 1.0
    out: list[str] = []
    for v in values:
        if not isinstance(v, int | float):
            out.append(" ")
            continue
        idx = int((v - lo) / span * (len(_SPARK_BARS) - 1))
        out.append(_SPARK_BARS[idx])
    return "".join(out)


# ---------- tables ------------------------------------------------------


def pretty_table(
    rows: list[dict],
    title: str | None = None,
    columns: list[str] | None = None,
    column_styles: dict[str, str] | None = None,
    formatters: dict[str, Any] | None = None,
    empty_msg: str = "(no rows)",
) -> None:
    """Rich table with column-specific styles + formatters.

    Args:
        rows: list of dicts to render
        title: optional bold title above the table
        columns: column order (defaults to keys of rows[0])
        column_styles: per-column style, e.g. {"name": "cyan", "ngi": "bold"}
        formatters: per-column callable for value formatting
        empty_msg: shown when rows is empty
    """
    from rich import box
    from rich.table import Table

    if not rows:
        console().print(f"[dim]{empty_msg}[/dim]")
        return
    cols = columns or list(rows[0].keys())
    styles = column_styles or {}
    fmts = formatters or {}
    table = Table(
        title=title,
        title_style="bold",
        show_lines=False,
        header_style="bold cyan",
        box=box.ROUNDED,
        expand=True,
        pad_edge=False,
    )
    for col in cols:
        table.add_column(col, overflow="fold", style=styles.get(col, ""), no_wrap=False)
    for r in rows:
        cells: list[str] = []
        for c in cols:
            val = r.get(c)
            fmt = fmts.get(c)
            if fmt is not None and val is not None:
                cells.append(str(fmt(val)))
            elif val is None:
                cells.append("[dim]—[/dim]")
            elif isinstance(val, float):
                # Auto-trim floats so tables don't blow out on raw repr.
                cells.append(f"{val:.3f}" if abs(val) < 100 else f"{val:.1f}")
            else:
                cells.append(str(val))
        table.add_row(*cells)
    console().print(table)


def kv_grid(items: dict[str, Any], title: str | None = None, cols: int = 4) -> None:
    """Grid of small KPI tiles — mirrors `st.columns(N).metric(...)`."""
    from rich.table import Table

    if not items:
        return
    if title:
        section(title)
    table = Table.grid(padding=(0, 2))
    for _ in range(cols):
        table.add_column()
    row: list[str] = []
    for k, v in items.items():
        cell = f"[dim]{k}[/dim]\n[bold]{_fmt_val(v)}[/bold]"
        row.append(cell)
        if len(row) == cols:
            table.add_row(*row)
            row = []
    if row:
        while len(row) < cols:
            row.append("")
        table.add_row(*row)
    console().print(table)


def _fmt_val(v: Any) -> str:
    if v is None or v == "":
        return "[dim]—[/dim]"
    if isinstance(v, float):
        return f"{v:.3f}" if abs(v) < 100 else f"{v:.1f}"
    return str(v)


# ---------- domain blocks ----------------------------------------------


def chips(items: dict[str, Any]) -> None:
    """One-line `key=value · key=value` chip row for IDs / metadata."""
    parts = [f"[dim]{k}=[/dim][cyan]{v}[/cyan]" for k, v in items.items() if v]
    if parts:
        console().print(" · ".join(parts))


def wikidata_block(wd: dict) -> None:
    """Render the Wikidata enrichment block — image URL, DOB, age, country
    Q-id, social links — mirroring the dashboard Profile card.

    `wd` is a record from data/curated/wikidata_enrichment.json. None-safe.
    """
    from cricdex.cli._copy import WIKIDATA_FOOTER, WIKIDATA_NOT_FOUND, WIKIDATA_NOT_PULLED

    section("Wikidata")
    if not wd:
        footnote(WIKIDATA_NOT_PULLED)
        return
    status = wd.get("_status")
    if status == "not_found":
        footnote(WIKIDATA_NOT_FOUND)
        return
    if status and status != "ok":
        footnote(f"Wikidata: status={status}")
        return

    age = _compute_age(wd.get("dob"))
    kv_grid(
        {
            "DOB": wd.get("dob") or "—",
            "Age": age or "—",
            "Country (Q-id)": wd.get("country_qid") or "—",
            "Birthplace (Q-id)": wd.get("birthplace_qid") or "—",
        },
        cols=4,
    )

    c = console()
    if wd.get("image_url"):
        c.print(f"[dim]Photo:[/dim] [link={wd['image_url']}]{wd['image_url']}[/link]")

    social: list[str] = []
    if wd.get("twitter"):
        social.append(f"[link=https://twitter.com/{wd['twitter']}]𝕏 @{wd['twitter']}[/link]")
    if wd.get("instagram"):
        social.append(
            f"[link=https://instagram.com/{wd['instagram']}]Instagram @{wd['instagram']}[/link]"
        )
    if wd.get("espn_id"):
        social.append(
            f"[link=https://www.espncricinfo.com/cricketers/{wd['espn_id']}]ESPNcricinfo[/link]"
        )
    if wd.get("cricbuzz_id"):
        social.append(
            f"[link=https://www.cricbuzz.com/profiles/{wd['cricbuzz_id']}]Cricbuzz[/link]"
        )
    if wd.get("wikidata_qid"):
        social.append(f"[link=https://www.wikidata.org/wiki/{wd['wikidata_qid']}]Wikidata[/link]")
    if social:
        c.print(" · ".join(social))
    footnote(WIKIDATA_FOOTER)


def _compute_age(dob: str | None) -> int | None:
    if not dob:
        return None
    try:
        d = _dt.date.fromisoformat(dob[:10])
        today = _dt.date.today()
        return today.year - d.year - ((today.month, today.day) < (d.month, d.day))
    except Exception:
        return None


def bayes_sentence(bayes: dict, role_key: str, label: str) -> str:
    """Mirror dashboard `_bayes_sentence` — '+0.12 (medium confidence; σ=0.08 on 6499 balls)'."""
    rec = (bayes or {}).get(f"bayes_{role_key}") or {}
    skill = rec.get("skill")
    sd = rec.get("skill_sd")
    balls = rec.get("balls")
    if skill is None:
        return f"{label}: [dim]not enough data.[/dim]"
    sd_val = sd if sd is not None else 1.0
    if sd_val < 0.05:
        conf = "high"
    elif sd_val < 0.10:
        conf = "medium"
    else:
        conf = "low"
    return (
        f"{label}: [bold]{skill:+.3f}[/bold] "
        f"([dim]{conf} confidence; σ={sd_val:.3f} on {balls or '?'} balls[/dim])"
    )


def bayes_extra(bayes: dict, role_key: str, skill_key: str, label: str) -> str:
    """Render a dismissal-aware secondary axis (survival_skill /
    strike_skill) the same way as `bayes_sentence`. Returns a dim
    'n/a' line when the joint model hasn't been fit (legacy ratings)."""
    rec = (bayes or {}).get(f"bayes_{role_key}") or {}
    skill = rec.get(skill_key)
    if skill is None:
        return f"{label}: [dim]n/a (run dismissal-aware ratings fit)[/dim]"
    sd = rec.get(f"{skill_key}_sd")
    sd_val = sd if sd is not None else 1.0
    conf = "high" if sd_val < 0.05 else ("medium" if sd_val < 0.10 else "low")
    return f"{label}: [bold]{skill:+.3f}[/bold] ([dim]{conf} confidence; σ={sd_val:.3f}[/dim])"


def load_wikidata(cricsheet_id: str | None) -> dict:
    """Load the per-player Wikidata record. None-safe; returns {} on miss."""
    import json as _json

    from cricdex.config import ROOT

    if not cricsheet_id:
        return {}
    path = ROOT / "data" / "curated" / "wikidata_enrichment.json"
    if not path.exists():
        return {}
    try:
        data = _json.loads(path.read_text())
    except Exception:
        return {}
    return data.get(cricsheet_id) or {}
