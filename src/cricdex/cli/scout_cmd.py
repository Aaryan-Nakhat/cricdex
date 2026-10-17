"""`cricdex scout look-alikes` — web-identical cross-competition look-alikes.

Pick an active IPL player → similar players across every Scout pool in the league
registry (config/leagues.toml: IPL peers, uncapped SMAT, then each overseas league), read
from the same exported JSON and computed with `cricdex.web_parity` (locked to the web
by `test_web_parity.py`).
"""

from __future__ import annotations

import typer

from cricdex.cli import _copy, _render
from cricdex.cli._shared import console, die, resolve_or_die
from cricdex.common.display import display_name, profile_collection, stale_marker

app = typer.Typer(add_completion=False, no_args_is_help=True)


@app.command(
    "look-alikes",
    help="Cross-competition look-alikes across every Scout pool (IPL peers, SMAT, overseas leagues) — identical to the web Scout.",
)
def look_alikes(
    name: str = typer.Argument(..., help="active IPL player (fuzzy-matched)"),
    role: str | None = typer.Option(None, "--role", help="override match role"),
    pos: str | None = typer.Option(
        None,
        "--pos",
        help="batting slot: same (the pick's band — default), any, or one slot (opener…tailender)",
    ),
    country: str = typer.Option(
        "same",
        "--country",
        help="same (the pick's country — default), overseas (every other country) or all",
    ),
    top_k: int = typer.Option(8, "-k", "--top-k"),
) -> None:
    from cricdex import leagues
    from cricdex.web_parity import (
        est_value,
        gem_threshold,
        is_gem,
        load_scout_index,
        similar_to,
    )
    from cricdex.web_parity.scout import BAND_LABEL, COUNTRY_MODES, SAME_SLOT, slot_band

    try:
        idx = load_scout_index("ipl")
    except FileNotFoundError as e:
        die(str(e), hint="run `uv run python scripts/export_site.py` to cook the indices")

    name = resolve_or_die(name, collection="ipl")
    sel = next((p for p in idx["ipl"] if p["name"] == name), None)
    if sel is None:
        die(f"{name} isn't in the active IPL scout index (too few balls / inactive).")

    country = country.lower()
    if country not in COUNTRY_MODES:
        die(f"--country must be one of {list(COUNTRY_MODES)}")
    use_role = role or sel["role"]
    # Same type by default: the pick's batting band, unless matching as a bowler (slot means nothing there).
    if pos is None:
        use_pos = "" if use_role == "bowler" else SAME_SLOT
    else:
        use_pos = "" if pos.lower() in ("any", "") else pos.lower()
    if use_role == "bowler":
        use_pos = ""
    slot_txt = (
        BAND_LABEL.get(slot_band(sel.get("batting_position")), "any")
        if use_pos == SAME_SLOT
        else (use_pos or "any")
    )
    country_txt = {
        "same": sel.get("country") or "any (pick's country unknown)",
        "overseas": f"not {sel.get('country') or '?'}",
        "all": "all",
    }[country]
    sel_price = est_value(sel["value"], sel["role"], "ipl")
    gem_lg = leagues.gem_pool()
    gem_tier = gem_lg.tier if gem_lg else None
    gem_med = gem_threshold(idx.get(gem_tier, [])) if gem_tier else None

    _render.header(
        f"Scout — look-alikes for {display_name(sel) or name}",
        subtitle=(
            f"role: {use_role}"
            + (f" ({sel['bowling_category']})" if sel.get("bowling_category") else "")
            + f"  ·  slot: {slot_txt}  ·  country: {country_txt}"
            + f"  ·  standing: {sel['z']:.2f}  ·  est ≈ {sel_price:.1f} cr"
        ),
    )
    _render.intro_panel(_copy.TWINS_INTRO, title="Scout")

    empty: list[str] = []
    first_hit: dict | None = None
    for lg in leagues.scout_pools():
        tier, title = lg.tier, lg.scout_title or lg.short
        if tier not in idx:
            continue  # a pool added to the registry since the last export
        rows = []
        fb = sel.get("country") if tier == gem_tier else None
        found = similar_to(
            sel, idx[tier], use_role, use_pos, top_k, country=country, fallback_country=fb
        )
        for r in found:
            price = est_value(r["value"], r["role"], tier)
            saving = sel_price - price if price < sel_price else 0.0
            rows.append(
                {
                    "name": display_name(r),
                    "country": r.get("country") or "—",
                    "last": (r.get("last_match_date") or "")[:4],
                    "est_cr": round(price, 1),
                    "save_cr": round(saving, 1) if saving > 0 else "",
                    "sim%": round(r["sim"] * 100),
                    "gem": "💎" if (tier == gem_tier and is_gem(r, gem_med)) else "",
                }
            )
        stale = stale_marker(lg.key)
        if stale:
            title = f"{title} ({stale})"
        # prefer a look-alike from outside the IPL: his profile lives in his own league
        if found and (not first_hit or profile_collection(first_hit) == "ipl"):
            first_hit = found[0]
        if rows:
            _render.pretty_table(rows, title=title, column_styles={"name": "bold cyan"})
        else:
            empty.append(lg.short)
    if empty:
        extra = " — try --country overseas or --country all" if country == "same" else ""
        console().print(f"[dim]No close match of this type in {', '.join(empty)}{extra}.[/dim]")
    if first_hit:
        # a look-alike's profile lives in his own league (a SMAT prospect has no IPL profile)
        _render.hint(
            f'`cricdex profile "{first_hit["name"]}" -c {profile_collection(first_hit)}` '
            "for a look-alike's full profile."
        )
    _render.footnote(
        "Same data + logic as the web Scout (locked by test_web_parity.py). Same type only: "
        "role, seam/spin for anyone who bowls, and the batting band unless --pos any. est_cr = the "
        "auction's skill→price curve (tier-discounted); 💎 = uncapped gem (high standing, low "
        "exposure)."
    )
