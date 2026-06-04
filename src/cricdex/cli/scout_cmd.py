"""`cricdex scout look-alikes` — web-identical cross-competition look-alikes.

Pick an active IPL player → similar players across IPL / SMAT / BBL / SA20 /
CPL / T20 Blast, read from the same exported JSON and computed with
`cricdex.web_parity` (locked to the web by `test_web_parity.py`).
"""

from __future__ import annotations

import typer

from cricdex.cli import _copy, _render
from cricdex.cli._shared import console, die, resolve_or_die

app = typer.Typer(add_completion=False, no_args_is_help=True)


@app.command(
    "look-alikes",
    help="3-tier cross-competition look-alikes (IPL/SMAT/BBL) — identical to the web Scout.",
)
def look_alikes(
    name: str = typer.Argument(..., help="active IPL player (fuzzy-matched)"),
    role: str | None = typer.Option(None, "--role", help="override match role"),
    pos: str | None = typer.Option(None, "--pos", help="batting slot filter (opener…tailender)"),
    top_k: int = typer.Option(8, "-k", "--top-k"),
) -> None:
    from cricdex.web_parity import (
        est_value,
        gem_threshold,
        is_gem,
        load_scout_index,
        similar_to,
    )

    try:
        idx = load_scout_index("ipl")
    except FileNotFoundError as e:
        die(str(e), hint="run `uv run python scripts/export_site.py` to cook the indices")

    name = resolve_or_die(name, collection="ipl")
    sel = next((p for p in idx["ipl"] if p["name"] == name), None)
    if sel is None:
        die(f"{name} isn't in the active IPL scout index (too few balls / inactive).")

    use_role = role or sel["role"]
    use_pos = pos or ""
    sel_price = est_value(sel["value"], sel["role"], "ipl")
    gem_med = gem_threshold(idx["smat"])

    _render.header(
        f"Scout — look-alikes for {name}",
        subtitle=f"role: {use_role}  ·  standing: {sel['z']:.2f}  ·  est ≈ {sel_price:.1f} cr",
    )
    _render.intro_panel(_copy.TWINS_INTRO, title="Scout")

    titles = {
        "ipl": "IPL peers",
        "smat": "Uncapped · SMAT",
        "bbl": "Overseas · BBL",
        "sa20": "Overseas · SA20",
        "cpl": "Overseas · CPL",
        "blast": "Overseas · T20 Blast",
    }
    for tier in ("ipl", "smat", "bbl", "sa20", "cpl", "blast"):
        rows = []
        for r in similar_to(sel, idx[tier], use_role, use_pos)[:top_k]:
            price = est_value(r["value"], r["role"], tier)
            saving = sel_price - price if price < sel_price else 0.0
            rows.append(
                {
                    "name": r["name"],
                    "country": r.get("country") or "—",
                    "last": (r.get("last_match_date") or "")[:4],
                    "est_cr": round(price, 1),
                    "save_cr": round(saving, 1) if saving > 0 else "",
                    "sim%": round(r["sim"] * 100),
                    "gem": "💎" if (tier == "smat" and is_gem(r, gem_med)) else "",
                }
            )
        if rows:
            _render.pretty_table(rows, title=titles[tier], column_styles={"name": "bold cyan"})
        else:
            console().print(f"[dim]{titles[tier]}: no close match of this archetype.[/dim]")
    _render.footnote(
        "Same data + logic as the web Scout (locked by test_web_parity.py). est_cr = the "
        "auction's skill→price curve (tier-discounted); 💎 = uncapped gem (high standing, low "
        "exposure)."
    )
