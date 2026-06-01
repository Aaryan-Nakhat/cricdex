"""Top-level one-shot commands: profile / compare / records / venues /
match-report / translate. All renderers parity-match the Streamlit
pages (8_Player_Profile, 5_Compare, 3_Records, 6_Venues,
4_Match_Reports, 9_Translate_Commentary).
"""

from __future__ import annotations

import typer

from cricdex.cli import _copy, _render
from cricdex.cli._shared import (
    EXIT_MISSING_CRED,
    console,
    die,
    resolve_or_die,
)


def profile(
    name: str = typer.Argument(..., help="player name (fuzzy-matched against collection)"),
    collection: str = typer.Option("ipl", "--collection", "-c"),
) -> None:
    from cricdex.profiles import builder

    name = resolve_or_die(name, collection=collection)
    with _render.spinner(f"building profile for {name}"):
        p = builder.build(name, collection)

    _render.header(p.get("name", name), subtitle=f"collection: {collection}")
    _render.intro_panel(_copy.PROFILE_INTRO, title="Profile")

    # cross-source IDs as a chip row
    ids = p.get("ids") or {}
    if ids:
        _render.chips({k: v for k, v in ids.items() if k != "unique_name"})

    # Wikidata enrichment (photo URL, DOB, age, Q-ids, socials)
    wd = _render.load_wikidata(p.get("cricsheet_id"))
    _render.wikidata_block(wd)

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
    for slug, hint in _copy.METRIC_HINTS.items():
        payload = metrics.get(slug)
        rows.append(
            {
                "metric": slug.replace("_", " ").title(),
                "value": _summarise_metric_payload(payload),
                "what it captures": hint,
            }
        )
    _render.pretty_table(
        rows,
        columns=["metric", "value", "what it captures"],
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

    # Style twins (cosine on metric vector)
    twins_b = p.get("style_twins_batter") or []
    twins_k = p.get("style_twins_bowler") or []
    if twins_b:
        _render.pretty_table(
            [_fmt_twin(t) for t in twins_b[:8]],
            title="Style twins — as batter (cosine on metric vector)",
            formatters={"distance": _fmt_distance},
        )
    if twins_k:
        _render.pretty_table(
            [_fmt_twin(t) for t in twins_k[:8]],
            title="Style twins — as bowler (cosine on metric vector)",
            formatters={"distance": _fmt_distance},
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

    # Graph cohort (Neo4j) — optional, soft-fails if extra not installed
    _render.section("Graph cohort (Neo4j)")
    _render.footnote(_copy.GRAPH_COHORT_INTRO)
    try:
        from cricdex.scout.graph import similar

        with _render.spinner("traversing scout graph"):
            cf_rows = similar.co_faced_bowlers(name, top_k=8)
        if cf_rows:
            _render.pretty_table(
                cf_rows,
                title="Co-faced bowlers cohort",
                formatters={"score": _fmt_distance},
            )
        else:
            _render.footnote(
                "no co-faced cohort — populate scout graph "
                f"(`cricdex data ingest graph -c {collection}`)"
            )
        with _render.spinner("loading teammate overlap"):
            tm_rows = similar.teammate_overlap(name, top_k=8)
        if tm_rows:
            _render.pretty_table(
                tm_rows,
                title="Teammate overlap cohort",
                formatters={"score": _fmt_distance},
            )
    except ImportError:
        _render.footnote(
            "neo4j extra not installed — `uv sync --extra graph` to unlock graph cohort"
        )
    except Exception as e:  # noqa: BLE001
        _render.footnote(f"graph cohort skipped: {e}")

    _render.hint("`cricdex tui` for an interactive view, `cricdex dashboard` for the browser UI.")


def _summarise_metric_payload(payload) -> str:
    """One-liner summary of a metric record — picks a headline number."""
    if not payload:
        return "[dim]—[/dim]"
    if isinstance(payload, dict):
        for key in (
            "ngi_per_match",
            "pressure_sr_per_100_balls",
            "intent",
            "recoverability",
            "counter_attack",
            "boundary_dependency",
            "wicket_rate_pct",
            "wicket_quality",
            "phase_dilation",
            "setting_tax",
        ):
            if key in payload and payload[key] is not None:
                v = payload[key]
                return f"{v:.2f}" if isinstance(v, float) else str(v)
        # fall back to first numeric value
        for v in payload.values():
            if isinstance(v, int | float):
                return f"{v:.2f}" if isinstance(v, float) else str(v)
        return "[dim]see expander[/dim]"
    return str(payload)


def _fmt_twin(t: dict) -> dict:
    """Trim a twin row to {name, distance} for compact display."""
    return {
        "name": t.get("name") or t.get("player") or t.get("batter") or t.get("bowler"),
        "distance": t.get("distance"),
    }


def _fmt_distance(v) -> str:
    if v is None:
        return "—"
    try:
        return f"{float(v):.4f}"
    except (TypeError, ValueError):
        return str(v)


def compare(
    a: str = typer.Argument(...),
    b: str = typer.Argument(...),
    collection: str = typer.Option("ipl", "--collection", "-c"),
) -> None:
    from cricdex.comparator import compare as cmp

    a = resolve_or_die(a, collection=collection)
    b = resolve_or_die(b, collection=collection)
    _render.header(f"{a}  vs  {b}", subtitle=f"collection: {collection}")
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

    _render.header(f"Records — {key}", subtitle=f"collection: {collection}")
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

    _render.header(venue, subtitle=f"collection: {collection}")
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


def match_report(
    match_id: str = typer.Argument(...),
    collection: str = typer.Option("ipl", "--collection", "-c"),
) -> None:
    from cricdex.config import settings
    from cricdex.reports import match_report as mr

    if not (settings.gemini_api_key or settings.gemini_tmp_url):
        die(
            "no Gemini credential — `cricdex config set gemini_api_key <key>`",
            code=EXIT_MISSING_CRED,
        )
    _render.header(f"Match report — {match_id}", subtitle=f"collection: {collection}")
    _render.intro_panel(_copy.MATCH_REPORT_INTRO, title="Match report")
    path = mr.generate(match_id=match_id, collection=collection)
    console().print(path.read_text())


def translate(
    text: str = typer.Argument(...),
    to: str = typer.Option("hi", "--to", help="hi|ta|bn|ur|si|mr|te|kn"),
) -> None:
    from cricdex.commentary_translate import translate as tr

    _render.header("Translate", subtitle=f"en → {to}")
    _render.intro_panel(_copy.TRANSLATE_INTRO, title="Translate")
    out = tr.translate(text, target=to)
    console().print(f"[bold]Input  [/bold] {text}")
    console().print(f"[bold]Output [/bold] [cyan]{out}[/cyan]")
