"""Top-level one-shot commands: profile / compare / records / venues.
All renderers parity-match the Streamlit pages (8_Player_Profile,
5_Compare, 3_Records, 6_Venues).
"""

from __future__ import annotations

import typer

from cricdex.cli import _copy, _render
from cricdex.cli._shared import (
    EXIT_MISSING_DATA,
    coll_subtitle,
    console,
    die,
    load_players,
    metric_headline,
    resolve_or_die,
)
from cricdex.common.display import display_name
from cricdex.common.metrics import DIRECTION_LABEL, METRIC_BY_SLUG


def _need_duckdb(what: str, collection: str) -> None:
    """profile / compare build live from the DuckDB, unlike the JSON-backed commands."""
    from cricdex.profiles.identity import DEFAULT_DB_PATH

    if not DEFAULT_DB_PATH.exists():
        die(
            f"{what} reads the live DuckDB, and there is none at {DEFAULT_DB_PATH}",
            code=EXIT_MISSING_DATA,
            hint=f"run `cricdex data ingest cricsheet -c {collection}` (or use the TUI Profile tab, "
            "which reads the exported JSON)",
        )


def profile(
    name: str = typer.Argument(..., help="player name (fuzzy-matched against collection)"),
    collection: str = typer.Option("ipl", "--collection", "-c"),
) -> None:
    from cricdex.profiles import builder

    _need_duckdb("profile", collection)
    name = resolve_or_die(name, collection=collection)
    with _render.spinner(f"building profile for {name}"):
        p = builder.build(name, collection)

    row = next((r for r in load_players(collection) or [] if r.get("name") == name), None)
    shown = display_name(row) if row else ""
    _render.header(shown or p.get("name", name), subtitle=coll_subtitle(collection))
    _render.intro_panel(_copy.PROFILE_INTRO, title="Profile")

    # cross-source IDs as a chip row
    ids = p.get("ids") or {}
    if ids:
        _render.chips({k: v for k, v in ids.items() if k != "unique_name"})

    # Wikidata enrichment (photo URL, DOB, age, Q-ids, socials)
    wd = _render.load_wikidata(p.get("cricsheet_id"))
    _render.wikidata_block(wd)

    # LLM taxonomy + activity (role / bowling type / batting slot / country)
    tax = p.get("taxonomy") or {}
    act = p.get("activity") or {}
    if tax or act:
        _pos = {
            "opener": "Opener",
            "no3": "No. 3",
            "middle": "Middle order",
            "finisher": "Finisher",
            "lower": "Lower order",
            "tailender": "Tailender",
        }
        items: dict[str, object] = {}
        if act:
            last = (act.get("last_match_date") or "")[:4]
            items["Status"] = (
                "Active" if act.get("active") else (f"Retired (last {last})" if last else "Retired")
            )
        if tax.get("primary_role"):
            items["Role"] = str(tax["primary_role"]).replace("_", "-")
        if tax.get("bowling_style"):
            items["Bowling"] = str(tax["bowling_style"]).replace("-", " ")
        if tax.get("batting_position"):
            items["Bats"] = _pos.get(tax["batting_position"], tax["batting_position"])
        if tax.get("country"):
            items["Country"] = tax["country"]
        if items:
            _render.kv_grid(items, title="Profile", cols=5)

    # career totals
    career = p.get("career") or {}
    if career:
        _render.kv_grid(
            {
                "Runs": career.get("career_runs", 0),
                "Balls faced": career.get("career_balls_faced", 0),
                "Sixes": career.get("career_sixes", 0),
                "Fours": career.get("career_fours", 0),
                "Innings": career.get("career_innings", 0),
                "Wickets": career.get("career_wickets", 0),
                "Legal balls bowled": career.get("career_legal_balls_bowled", 0),
                "Matches bowled": career.get("career_matches_bowled", 0),
            },
            title="Career totals",
            cols=4,
        )

    # novel metrics — one row per metric with hint + value summary
    metrics = p.get("metrics") or {}
    _render.section("Novel metrics")
    rows = []
    for slug, m in METRIC_BY_SLUG.items():
        payload = metrics.get(slug)
        label, value = metric_headline(slug, payload)
        rows.append(
            {
                "metric": m.name,
                "value": f"{value} ({label.lower()})" if label and value != "—" else value,
                "how to read it": m.read,
                "which way": DIRECTION_LABEL.get(m.direction, ""),
            }
        )
    _render.pretty_table(
        rows,
        columns=["metric", "value", "how to read it", "which way"],
        column_styles={"metric": "bold", "value": "cyan"},
    )

    # Bayes scout-rating
    _render.section("Bayesian scout-rating")
    bayes = p.get("bayes") or {}
    c = console()
    c.print(_render.bayes_sentence(bayes, "batter", "Batter scoring"))
    c.print(_render.bayes_extra(bayes, "batter", "survival_skill", "Batter survival"))
    c.print(_render.bayes_sentence(bayes, "bowler", "Bowler economy"))
    c.print(_render.bayes_extra(bayes, "bowler", "strike_skill", "Bowler strike"))
    _render.footnote(_copy.BAYES_SCALE)

    # Style twins (scout/search/style_twin.py: how he bats / bowls, same role and bowling type)
    twins_b = p.get("style_twins_batter") or []
    twins_k = p.get("style_twins_bowler") or []
    if twins_b:
        _render.pretty_table(
            [_fmt_twin(t) for t in twins_b[:8]],
            title="Style twins — as batter (% alike)",
        )
    if twins_k:
        _render.pretty_table(
            [_fmt_twin(t) for t in twins_k[:8]],
            title="Style twins — as bowler (% alike)",
        )

    # Dismissal fingerprint — how this player gets out / takes wickets.
    fp = p.get("dismissal_fingerprint") or {}
    bat_fp = fp.get("batter") or {}
    bowl_fp = fp.get("bowler") or {}
    if bat_fp.get("total"):
        _render.pretty_table(
            [
                {"kind": r["kind"], "count": r["count"], "pct": f"{r['pct']}%"}
                for r in bat_fp["rows"]
            ],
            title=f"Dismissal fingerprint — as batter ({bat_fp['total']} dismissals)",
            column_styles={"kind": "bold cyan"},
        )
        _render.footnote(bat_fp.get("read", ""))
    if bowl_fp.get("total"):
        _render.pretty_table(
            [
                {"kind": r["kind"], "count": r["count"], "pct": f"{r['pct']}%"}
                for r in bowl_fp["rows"]
            ],
            title=f"Dismissal fingerprint — as bowler ({bowl_fp['total']} wickets)",
            column_styles={"kind": "bold cyan"},
        )
        _render.footnote(bowl_fp.get("read", ""))

    _render.hint("`cricdex tui` for an interactive view, `cricdex dashboard` for the browser UI.")


def _fmt_twin(t: dict) -> dict:
    """Trim a twin row to {name, alike} for compact display (alike = 100 x (1 - distance))."""
    d = t.get("distance")
    try:
        alike = f"{max(0.0, 1 - float(d)) * 100:.0f}%"
    except (TypeError, ValueError):
        alike = "—"
    return {
        "name": t.get("name") or t.get("player") or t.get("batter") or t.get("bowler"),
        "alike": alike,
    }


def compare(
    a: str = typer.Argument(...),
    b: str = typer.Argument(...),
    collection: str = typer.Option("ipl", "--collection", "-c"),
) -> None:
    from cricdex.comparator import compare as cmp

    _need_duckdb("compare", collection)
    a = resolve_or_die(a, collection=collection)
    b = resolve_or_die(b, collection=collection)
    _render.header(f"{a}  vs  {b}", subtitle=coll_subtitle(collection))
    _render.intro_panel(_copy.COMPARE_INTRO, title="Compare")
    df = cmp.compare([a, b], collection=collection)
    if df.is_empty():
        die("comparator returned no rows")
    pdf = df.to_pandas().set_index("player").T.reset_index().rename(columns={"index": "metric"})
    rows = pdf.to_dict(orient="records")
    # empty cells → dash
    for r in rows:
        for k, v in list(r.items()):
            if v is None or (isinstance(v, float) and v != v):  # NaN
                r[k] = None
    _render.pretty_table(rows, column_styles={"metric": "bold cyan"})
    _render.footnote(_copy.COMPARE_THRESHOLD_NOTE)

    # Bayesian skill head-to-head — P(A better than B) per role.
    from cricdex.scout.ratings.head_to_head import head_to_head

    _render.section("Bayesian skill head-to-head")
    h2h = head_to_head(a, b, collection=collection)
    if h2h.get("error"):
        _render.footnote(h2h["error"])
    else:
        # Axis labels per role for the sub-component column.
        axis_labels = {
            "batter": ("score", "survive"),
            "bowler": ("econ", "strike"),
        }
        rows_h: list[dict] = []
        for role in ("batter", "bowler", "all_rounder"):
            c = h2h["comparisons"].get(role)
            if c is None:
                continue
            if "score_a" in c and role in axis_labels:
                p, s = axis_labels[role]
                detail = (
                    f"{a}: {p} {c['score_a']:+.2f} / {s} {c['survival_a']:+.2f}   "
                    f"{b}: {p} {c['score_b']:+.2f} / {s} {c['survival_b']:+.2f}"
                )
            else:
                detail = f"composite {c['mean_a']:+.2f} vs {c['mean_b']:+.2f}"
            rows_h.append(
                {
                    "role": role.replace("_", "-"),
                    f"P({a} better)": f"{c['p_a_better']:.0%}",
                    "verdict": c["verdict"],
                    "components": detail,
                }
            )
        if rows_h:
            _render.pretty_table(rows_h, column_styles={"role": "bold cyan"})
            _render.footnote(_copy.HEAD_TO_HEAD_NOTE)
        else:
            _render.footnote(
                "no overlapping Bayesian ratings for these two — "
                f"run `cricdex data ingest ratings -c {collection}`"
            )

    # Matchup rivalry log — has either ever dismissed the other?
    from cricdex.metrics import dismissal_fingerprint as df

    _render.section("Head-to-head dismissal log")
    any_rivalry = False
    for batter, bowler in ((a, b), (b, a)):
        log = df.matchup_log(batter, bowler, collection=collection)
        if log["total"]:
            any_rivalry = True
            kinds = ", ".join(f"{r['count']}× {r['kind']}" for r in log["rows"])
            console().print(
                f"  [bold cyan]{bowler}[/bold cyan] dismissed [bold]{batter}[/bold] "
                f"[bold]{log['total']}×[/bold] in {log['balls']} balls  "
                f"([dim]{kinds}[/dim])"
            )
    if not any_rivalry:
        _render.footnote("these two have no bowler-credited dismissals of each other on record")


def records(
    key: str = typer.Argument("today", help="`today` or a record key (run `cricdex records list`)"),
    collection: str = typer.Option("ipl", "--collection", "-c"),
    top_n: int = typer.Option(25, "--top-n"),
) -> None:
    import datetime as _dt

    from cricdex.records import queries

    _render.header(f"Records — {key}", subtitle=coll_subtitle(collection))
    _render.intro_panel(_copy.RECORDS_INTRO, title="Records")

    if key == "today":
        today = _dt.date.today()
        df = queries.on_this_day(month=today.month, day=today.day, collection=collection)
        rows = df.to_dicts() if hasattr(df, "to_dicts") else df
        if not rows:
            console().print(
                f"[dim]nothing notable on {today.month:02d}-{today.day:02d} in {collection}.[/dim]"
            )
            return
        _render.pretty_table(
            rows, title=f"on-this-day {today.month:02d}-{today.day:02d} ({collection})"
        )
        return
    if key == "list":
        keys = (
            getattr(queries, "RECORD_KEYS", None)
            or getattr(queries, "RECORDS", None)
            or sorted(
                name
                for name in dir(queries)
                if not name.startswith("_") and name not in {"on_this_day", "top"}
            )
        )
        _render.pretty_table([{"key": k} for k in keys], title="record keys")
        return
    fn = getattr(queries, key, None)
    if not callable(fn):
        die(f"unknown record key `{key}` — try `cricdex records list`")
    df = fn(collection=collection, top_n=top_n)
    rows = df.to_dicts() if hasattr(df, "to_dicts") else df
    _render.pretty_table(rows, title=f"{key} top-{top_n} ({collection})")


def venues(
    venue: str = typer.Argument(...),
    collection: str = typer.Option("ipl", "--collection", "-c"),
) -> None:
    from cricdex.venues import profile as v

    # Accept part of a ground's name ("Wankhede"): exact match first, then the busiest ground containing it.
    try:
        known = v.list_venues(collection, min_matches=1)["venue"].to_list()
    except Exception as e:  # noqa: BLE001
        die(f"venue lookup failed: {e}")
    if venue not in known:
        # any of a ground's names counts (spellings, former names like "Feroz Shah Kotla")
        try:
            import duckdb

            from cricdex.common.venue_names import aliases_for

            with duckdb.connect(str(v.DEFAULT_DB_PATH), read_only=True) as con:
                names_of = aliases_for(con)
        except duckdb.Error:  # no DB: match on the ground's main name only
            names_of = {}
        q = venue.lower()
        hits = [
            k for k in known if q in k.lower() or any(q in a.lower() for a in names_of.get(k, []))
        ]
        if not hits:
            die(
                f"no venue matching '{venue}' in {collection}",
                hint="try part of the ground's name, e.g. Wankhede or Eden",
            )
        if len(hits) > 1:
            typer.echo(
                f"{len(hits)} grounds match — showing the busiest: {hits[0]}  (others: {', '.join(hits[1:4])})"
            )
        venue = hits[0]

    _render.header(venue, subtitle=coll_subtitle(collection))
    _render.intro_panel(_copy.VENUES_INTRO, title="Venue")
    try:
        innings = v.innings_totals(venue, collection)
        if not innings.is_empty():
            _render.pretty_table(innings.to_dicts(), title="Innings totals")
        phases = v.phase_run_rates(venue, collection)
        if not phases.is_empty():
            _render.pretty_table(phases.to_dicts(), title="Phase run rates")
        chase = v.chase_vs_set_winrate(venue, collection)
        if not chase.is_empty():
            _render.pretty_table(chase.to_dicts(), title="Chase vs set win rate")
    except Exception as e:  # noqa: BLE001
        die(f"venue lookup failed: {e}")
