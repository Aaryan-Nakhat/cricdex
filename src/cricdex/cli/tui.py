"""Textual TUI — `cricdex tui` (also `cricdex` with no subcommand).

10 tabs matching the Streamlit dashboard pages 1-to-1:
Leaders / Rules / Records / Compare / Venues / Auction (Solve +
Recommend) / Profile / Auction-Sim / Scout / Update.
Same code paths as the one-shot CLI, so behaviour stays in lockstep —
the Auction-Sim and Scout tabs run the web-identical `cricdex.web_parity`.

Quit: q / Ctrl-C / Esc.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from rich.console import Console
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import (
    Button,
    DataTable,
    Footer,
    Header,
    Input,
    Label,
    RichLog,
    Select,
    Static,
    TabbedContent,
    TabPane,
)

from cricdex.cli import _copy, _render
from cricdex.config import DATA_DIR

METRIC_OPTIONS: list[tuple[str, str]] = [
    ("NGI (Net Game Impact)", "ngi"),
    ("Pressure Runs", "pressure_runs"),
    ("Intent Curve", "intent_curve"),
    ("Dot-Ball Recovery", "dot_ball_recovery"),
    ("Counter-Attack", "counter_attack"),
    ("Boundary Dependency", "boundary_dependency"),
    ("Pressure Conversion", "pressure_conversion"),
    ("Wicket Quality", "wicket_quality"),
    ("Crease Longevity", "crease_longevity"),
    ("Slow-Start Cost", "slow_start_cost"),
]

METRIC_KEYS: dict[str, tuple[str, str]] = {
    "ngi": ("ngi_per_match", "name"),
    "pressure_runs": ("pressure_sr_per_100_balls", "batter"),
    "intent_curve": ("sr", "batter"),
    "dot_ball_recovery": ("runs_per_6_after_dot", "batter"),
    "counter_attack": ("counter_attack_sr", "batter"),
    "boundary_dependency": ("bdr_pct", "batter"),
    "pressure_conversion": ("wicket_rate_pct", "bowler"),
    "wicket_quality": ("wicket_quality", "bowler"),
    "crease_longevity": ("longevity_index", "batter"),
    "slow_start_cost": ("slow_start_cost", "batter"),
}

VENUE_VIEW_OPTIONS = [
    ("Innings totals", "innings"),
    ("Phase run rates", "phases"),
    ("Chase vs set winrate", "chase"),
]

SCOUT_TIER_OPTIONS = [
    ("IPL peers", "ipl"),
    ("Uncapped · SMAT", "smat"),
    ("Overseas · BBL", "bbl"),
]
SCOUT_ROLE_OPTIONS = [
    ("(pick's role)", ""),
    ("Batter", "batter"),
    ("All-rounder", "all_rounder"),
    ("Keeper", "keeper"),
    ("Bowler", "bowler"),
]


def _fmt_cell(val: Any) -> Any:
    """Return cell content as a Rich Text with `fold` overflow so the
    DataTable wraps long strings across multiple lines instead of
    silently truncating. None → em-dash; floats trimmed to 3dp."""
    from rich.text import Text

    if val is None:
        return Text("—", style="dim")
    if isinstance(val, float):
        return f"{val:.3f}" if abs(val) < 100 else f"{val:.1f}"
    s = str(val)
    return Text(s, overflow="fold", no_wrap=False)


def _fill_datatable(table: DataTable, rows: list[dict], max_cols: int = 8) -> None:
    """Populate a DataTable with auto-wrapping cells. We compute row
    heights from the longest cell content so wraps render correctly."""
    table.clear(columns=True)
    if not rows:
        table.add_column("(no rows)")
        return
    cols = list(rows[0].keys())[:max_cols]
    table.add_columns(*cols)
    for r in rows:
        cells = tuple(_fmt_cell(r.get(c)) for c in cols)
        # Auto-grow row height to fit the longest folded cell.
        longest = max(
            (len(str(r.get(c))) for c in cols if r.get(c) is not None),
            default=20,
        )
        # ~32 chars per column line on a 160-wide screen with 8 cols.
        height = max(1, min(4, (longest // 32) + 1))
        table.add_row(*cells, height=height)


class CricDexApp(App):
    """Main Textual app — 11 tabs, one per Streamlit page."""

    # Layout notes:
    # - `.controls` is a horizontal bar with `align-vertical: middle` so
    #   labels / inputs / selects / buttons line up on one baseline (the
    #   earlier `height: 5` top-aligned everything → ragged row).
    # - Tab labels are short + emoji-free so all 12 fit inside a 120-col
    #   terminal (the emoji versions overflowed to 157 cols and clipped
    #   the last tabs off-screen).
    # - Palette comes from the built-in `nord` theme set in on_mount;
    #   `$accent` / `$panel` / `$boost` resolve to nord tokens.
    CSS = """
    Screen { background: $surface; }
    #status-bar {
        height: 1;
        background: $boost;
        color: $accent;
        text-style: bold;
        padding: 0 2;
    }
    TabbedContent { height: 1fr; }
    Tabs { background: $surface-darken-1; }
    Tab { padding: 0 1; }
    TabPane { padding: 0; }
    .controls {
        height: auto;
        layout: horizontal;
        align-vertical: middle;
        background: $panel;
        border: round $primary;
        padding: 1;
        margin: 1 1 0 1;
    }
    .controls Label {
        width: auto;
        height: 3;
        content-align: left middle;
        padding: 0 1 0 1;
        color: $accent;
    }
    .controls Input { width: 16; height: 3; margin: 0 1; }
    .controls Input.num { width: 8; }
    .controls Input.wide { width: 24; }
    .controls Select { width: 22; height: 3; margin: 0 1; }
    .controls Button { min-width: 12; height: 3; margin: 0 1; }
    .intro {
        height: auto;
        max-height: 3;
        color: $text-muted;
        padding: 0 2;
    }
    DataTable {
        height: 1fr;
        margin: 1;
        border: round $primary;
    }
    DataTable > .datatable--header {
        background: $boost;
        color: $accent;
        text-style: bold;
    }
    DataTable > .datatable--cursor { background: $accent 35%; }
    RichLog {
        height: 1fr;
        background: $panel;
        border: round $primary;
        margin: 1;
        padding: 0 1;
    }
    LoadingIndicator { color: $accent; }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("ctrl+c", "quit", "Quit"),
        Binding("right", "next_tab", "Next tab"),
        Binding("left", "prev_tab", "Prev tab"),
        Binding("ctrl+p", "command_palette", "Palette"),
    ]

    TITLE = "CricDex — open cricket intelligence"
    SUB_TITLE = "← → switch panels · q quit"

    def on_mount(self) -> None:
        # Built-in nord theme — clean dark palette, good contrast. Users
        # can cycle themes live via the command palette (ctrl+p).
        self.theme = "nord"

    _TAB_ORDER = [
        "tab-leaderboard",
        "tab-rules",
        "tab-records",
        "tab-compare",
        "tab-venues",
        "tab-auction",
        "tab-profile",
        "tab-auction-sim",
        "tab-twins",
        "tab-update",
    ]

    def _shift_tab(self, delta: int) -> None:
        tabs = self.query_one(TabbedContent)
        try:
            idx = self._TAB_ORDER.index(tabs.active)
        except ValueError:
            idx = 0
        tabs.active = self._TAB_ORDER[(idx + delta) % len(self._TAB_ORDER)]

    def action_next_tab(self) -> None:
        self._shift_tab(1)

    def action_prev_tab(self) -> None:
        self._shift_tab(-1)

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Static(self._status_text(), id="status-bar")
        with TabbedContent(id="tabs"):
            with TabPane("Leaders", id="tab-leaderboard"):
                yield from self._leaderboard_panel()
            with TabPane("Rules", id="tab-rules"):
                yield from self._rules_panel()
            with TabPane("Records", id="tab-records"):
                yield from self._records_panel()
            with TabPane("Compare", id="tab-compare"):
                yield from self._compare_panel()
            with TabPane("Venues", id="tab-venues"):
                yield from self._venues_panel()
            with TabPane("Auction", id="tab-auction"):
                yield from self._auction_panel()
            with TabPane("Profile", id="tab-profile"):
                yield from self._profile_panel()
            with TabPane("Sim", id="tab-auction-sim"):
                yield from self._auction_sim_panel()
            with TabPane("Scout", id="tab-twins"):
                yield from self._twins_panel()
            with TabPane("Update", id="tab-update"):
                yield from self._update_panel()
        yield Footer()

    # ---- status -----------------------------------------------------------

    def _status_text(self) -> str:
        n = (DATA_DIR / "cricsheet" / "cricsheet.duckdb").exists()
        r = (DATA_DIR / "rules" / "qdrant").exists()
        m = (DATA_DIR / "metrics").exists()
        return (
            f"  data: cricsheet [{'✓' if n else '✗'}]  rules [{'✓' if r else '✗'}]  "
            f"metrics [{'✓' if m else '✗'}]   ·   ← → switch panels  ·   "
            f"ctrl+p themes  ·   q quit"
        )

    # ===== Leaderboard ====================================================

    def _leaderboard_panel(self) -> ComposeResult:
        with Vertical():
            with Horizontal(classes="controls"):
                yield Label("Metric:")
                yield Select(
                    options=METRIC_OPTIONS, value="ngi", id="metric-select", allow_blank=False
                )
                yield Label("Collection:")
                yield Input(value="ipl", id="metric-collection")
                yield Label("Top N:")
                yield Input(value="20", id="metric-topn")
                yield Button("Show ▸", id="metric-run", variant="primary")
            yield Static(_copy.LEADERBOARD_INTRO, id="metric-hint", classes="intro")
            yield DataTable(id="metric-table", zebra_stripes=True)

    def _on_run_leaderboard(self) -> None:
        metric = self.query_one("#metric-select", Select).value
        collection = self.query_one("#metric-collection", Input).value
        try:
            top_n = int(self.query_one("#metric-topn", Input).value or "20")
        except ValueError:
            top_n = 20
        path = Path(DATA_DIR) / "metrics" / f"{metric}_{collection}.json"
        table = self.query_one("#metric-table", DataTable)
        hint = self.query_one("#metric-hint", Static)
        if not path.exists():
            _fill_datatable(
                table,
                [
                    {
                        "error": f"missing {path.name}",
                        "fix": f"`cricdex data ingest metrics -c {collection}`",
                    }
                ],
            )
            return
        rows = json.loads(path.read_text())
        if not isinstance(rows, list):
            rows = []
        sort_col, primary_key = METRIC_KEYS.get(metric, (None, None))
        if sort_col:
            rows = sorted(rows, key=lambda r: r.get(sort_col, 0) or 0, reverse=True)
        rows = rows[:top_n]
        if rows and sort_col and primary_key:
            extras = [k for k in rows[0].keys() if k not in {primary_key, sort_col}][:4]
            cols = [primary_key, sort_col, *extras]
            pruned = [{c: r.get(c) for c in cols} for r in rows]
            spark = _render.sparkline([r.get(sort_col) or 0 for r in rows])
            hint.update(f"{_copy.METRIC_HINTS.get(metric, '')}   ·   [{sort_col}] shape: {spark}")
            _fill_datatable(table, pruned)
        else:
            _fill_datatable(table, rows)

    # ===== Rules ==========================================================

    def _rules_panel(self) -> ComposeResult:
        with Vertical():
            with Horizontal(classes="controls"):
                yield Label("Q:")
                yield Input(value="what is the impact player rule in IPL", id="rules-q")
                yield Label("Fmts:")
                yield Input(value="ipl", id="rules-formats")
                yield Button("Ask ▸", id="rules-run", variant="primary")
            yield Static(_copy.RULES_INTRO, classes="intro")
            yield RichLog(id="rules-log", highlight=False, markup=True, wrap=True)

    def _on_run_rules(self) -> None:
        log = self.query_one("#rules-log", RichLog)
        log.clear()
        from cricdex.config import settings

        if not (settings.gemini_api_key or settings.gemini_tmp_url):
            log.write(
                "[red]missing Gemini credential[/red]\n"
                "set via `cricdex config set gemini_api_key <key>` then re-launch the TUI."
            )
            return
        question = self.query_one("#rules-q", Input).value
        formats = [
            f.strip() for f in self.query_one("#rules-formats", Input).value.split(",") if f.strip()
        ] or None
        try:
            from cricdex.rules import sources
            from cricdex.rules.qa import answer

            res = answer(question, formats=formats, top_k=8)
        except Exception as e:  # noqa: BLE001
            log.write(f"[red]error:[/red] {e}")
            return
        log.write(f"[bold]Q.[/bold] {question}\n")
        log.write(f"[bold green]A.[/bold green] {res.get('answer', '')}\n")
        for src_id, law in res.get("citations") or []:
            log.write(
                f"  [dim]•[/dim] [bold]{sources.label_for(src_id)}[/bold], "
                f"clause [cyan]{law}[/cyan]"
            )

    # ===== Records ========================================================

    def _records_panel(self) -> ComposeResult:
        with Vertical():
            with Horizontal(classes="controls"):
                yield Label("Key:")
                yield Input(value="today", id="records-key")
                yield Label("Coll:")
                yield Input(value="ipl", id="records-collection")
                yield Label("Top N:")
                yield Input(value="25", id="records-topn")
                yield Button("Show ▸", id="records-run", variant="primary")
            yield Static(_copy.RECORDS_INTRO, classes="intro")
            yield DataTable(id="records-table", zebra_stripes=True)

    def _on_run_records(self) -> None:
        import datetime as _dt

        table = self.query_one("#records-table", DataTable)
        key = self.query_one("#records-key", Input).value.strip()
        collection = self.query_one("#records-collection", Input).value
        try:
            top_n = int(self.query_one("#records-topn", Input).value or "25")
        except ValueError:
            top_n = 25
        try:
            from cricdex.records import queries

            if key == "today":
                today = _dt.date.today()
                df = queries.on_this_day(month=today.month, day=today.day, collection=collection)
                rows = df.to_dicts() if hasattr(df, "to_dicts") else df
            else:
                fn = getattr(queries, key, None)
                if not callable(fn):
                    rows = [{"error": f"unknown record key `{key}`"}]
                else:
                    df = fn(collection=collection, top_n=top_n)
                    rows = df.to_dicts() if hasattr(df, "to_dicts") else df
        except Exception as e:  # noqa: BLE001
            _fill_datatable(table, [{"error": str(e)}])
            return
        _fill_datatable(table, rows)

    # ===== Compare ========================================================

    def _compare_panel(self) -> ComposeResult:
        with Vertical():
            with Horizontal(classes="controls"):
                yield Label("Player A:")
                yield Input(value="V Kohli", id="cmp-a")
                yield Label("Player B:")
                yield Input(value="RG Sharma", id="cmp-b")
                yield Label("Coll:")
                yield Input(value="ipl", id="cmp-collection")
                yield Button("Compare ▸", id="cmp-run", variant="primary")
            yield Static(_copy.COMPARE_INTRO, classes="intro")
            yield DataTable(id="cmp-table", zebra_stripes=True)
            yield Static("Bayesian skill head-to-head", classes="intro")
            yield DataTable(id="cmp-h2h-table", zebra_stripes=True)

    def _on_run_compare(self) -> None:
        table = self.query_one("#cmp-table", DataTable)
        h2h_table = self.query_one("#cmp-h2h-table", DataTable)
        a = self.query_one("#cmp-a", Input).value.strip()
        b = self.query_one("#cmp-b", Input).value.strip()
        collection = self.query_one("#cmp-collection", Input).value
        try:
            from cricdex.comparator import compare as cmp

            df = cmp.compare([a, b], collection=collection)
        except Exception as e:  # noqa: BLE001
            _fill_datatable(table, [{"error": str(e)}])
            return
        if df.is_empty():
            _fill_datatable(table, [{"info": "comparator returned no rows"}])
            return
        pdf = df.to_pandas().set_index("player").T.reset_index().rename(columns={"index": "metric"})
        _fill_datatable(table, pdf.to_dict(orient="records"), max_cols=10)

        # Bayesian skill head-to-head — P(A > B) per role.
        from cricdex.scout.ratings.head_to_head import head_to_head

        h2h = head_to_head(a, b, collection=collection)
        if h2h.get("error"):
            _fill_datatable(h2h_table, [{"info": h2h["error"]}])
            return
        rows_h: list[dict] = []
        for role in ("batter", "bowler", "all_rounder"):
            c = h2h["comparisons"].get(role)
            if c is None:
                continue
            rows_h.append(
                {
                    "role": role,
                    f"{a}": f"{c['mean_a']:+.3f}±{c['sd_a']:.2f}",
                    f"{b}": f"{c['mean_b']:+.3f}±{c['sd_b']:.2f}",
                    f"P({a}>)": f"{c['p_a_better']:.0%}",
                    "verdict": c["verdict"],
                }
            )

        # Matchup rivalry — bowler-credited dismissals either way.
        from cricdex.metrics import dismissal_fingerprint as dfp

        for batter, bowler in ((a, b), (b, a)):
            log = dfp.matchup_log(batter, bowler, collection=collection)
            if log["total"]:
                kinds = ", ".join(f"{r['count']}× {r['kind']}" for r in log["rows"])
                rows_h.append(
                    {
                        "role": "rivalry",
                        f"{a}": "",
                        f"{b}": "",
                        f"P({a}>)": "",
                        "verdict": f"{bowler} dismissed {batter} {log['total']}× ({kinds})",
                    }
                )
        _fill_datatable(
            h2h_table,
            rows_h or [{"info": "no overlapping Bayesian ratings for these two"}],
            max_cols=6,
        )

    # ===== Venues =========================================================

    def _venues_panel(self) -> ComposeResult:
        with Vertical():
            with Horizontal(classes="controls"):
                yield Label("Venue:")
                yield Input(value="Eden Gardens", id="ven-name")
                yield Label("Coll:")
                yield Input(value="ipl", id="ven-collection")
                yield Label("View:")
                yield Select(
                    options=VENUE_VIEW_OPTIONS,
                    value="innings",
                    id="ven-view",
                    allow_blank=False,
                )
                yield Button("Show ▸", id="ven-run", variant="primary")
            yield Static(_copy.VENUES_INTRO, classes="intro")
            yield DataTable(id="ven-table", zebra_stripes=True)

    def _on_run_venues(self) -> None:
        table = self.query_one("#ven-table", DataTable)
        venue = self.query_one("#ven-name", Input).value.strip()
        collection = self.query_one("#ven-collection", Input).value
        view = self.query_one("#ven-view", Select).value
        try:
            from cricdex.venues import profile as v

            if view == "innings":
                df = v.innings_totals(venue, collection)
            elif view == "phases":
                df = v.phase_run_rates(venue, collection)
            else:
                df = v.chase_vs_set_winrate(venue, collection)
        except Exception as e:  # noqa: BLE001
            _fill_datatable(table, [{"error": str(e)}])
            return
        if df.is_empty():
            _fill_datatable(table, [{"info": f"no data for `{view}` at {venue}"}])
            return
        _fill_datatable(table, df.to_dicts(), max_cols=10)

    # ===== Auction (Solve + Recommend in same tab — mirrors Streamlit) ====

    def _auction_panel(self) -> ComposeResult:
        with Vertical():
            with Horizontal(classes="controls"):
                yield Label("Target:")
                yield Input(value="JJ Bumrah", id="auc-target")
                yield Label("Budget:")
                yield Input(value="8", id="auc-budget")
                yield Label("Role:")
                yield Input(value="bowler", id="auc-role")
                yield Label("Top N:")
                yield Input(value="10", id="auc-n")
            with Horizontal(classes="controls"):
                yield Button("Recommend substitutes", id="auc-rec-run", variant="primary")
                yield Button("Solve MILP squad", id="auc-solve-run", variant="warning")
            yield Static(
                f"{_copy.AUCTION_RECOMMEND_INTRO}   ·   "
                f"Solve MILP uses purse=120, squad=25, overseas-cap=8.",
                classes="intro",
            )
            yield DataTable(id="auc-table", zebra_stripes=True)

    def _on_run_auction_recommend(self) -> None:
        table = self.query_one("#auc-table", DataTable)
        try:
            budget = float(self.query_one("#auc-budget", Input).value)
        except ValueError:
            _fill_datatable(table, [{"error": "budget must be a number"}])
            return
        try:
            n = int(self.query_one("#auc-n", Input).value or "10")
        except ValueError:
            n = 10
        try:
            from cricdex.auction import advisor

            rec = advisor.recommend_substitutes(
                self.query_one("#auc-target", Input).value,
                budget=budget,
                role=self.query_one("#auc-role", Input).value.strip() or None,
                n=n,
            )
        except Exception as e:  # noqa: BLE001
            _fill_datatable(table, [{"error": str(e)}])
            return
        if rec.is_empty():
            _fill_datatable(table, [{"info": "no affordable graph-similar candidates"}])
            return
        _fill_datatable(table, rec.to_dicts(), max_cols=8)

    def _on_run_auction_solve(self) -> None:
        table = self.query_one("#auc-table", DataTable)
        try:
            from cricdex.auction import real_pool, solver

            df = real_pool.build_pool()
            res = solver.solve(
                df,
                purse=120.0,
                squad_size=25,
                overseas_cap=8,
                role_mins={"batter": 5, "bowler": 5, "all_rounder": 3, "keeper": 0},
            )
        except Exception as e:  # noqa: BLE001
            _fill_datatable(table, [{"error": str(e)}])
            return
        if not res["feasible"]:
            _fill_datatable(table, [{"error": f"infeasible: {res.get('reason')}"}])
            return
        _fill_datatable(table, res["selected"].to_dicts(), max_cols=8)

    # ===== Profile ========================================================

    def _profile_panel(self) -> ComposeResult:
        with Vertical():
            with Horizontal(classes="controls"):
                yield Label("Player:")
                yield Input(value="V Kohli", id="profile-name")
                yield Label("Coll:")
                yield Input(value="ipl", id="profile-collection")
                yield Button("Build ▸", id="profile-run", variant="primary")
            yield Static(_copy.PROFILE_INTRO, classes="intro")
            yield RichLog(id="profile-log", highlight=False, markup=True, wrap=True)

    def _on_run_profile(self) -> None:
        log = self.query_one("#profile-log", RichLog)
        log.clear()
        name = self.query_one("#profile-name", Input).value
        collection = self.query_one("#profile-collection", Input).value
        try:
            from cricdex.profiles import builder

            p = builder.build(name, collection)
        except Exception as e:  # noqa: BLE001
            log.write(f"[red]error:[/red] {e}")
            return

        buf = Console(record=True, width=140, force_terminal=True, highlight=False)
        buf.print(f"[bold bright_cyan]{p.get('name', name)}[/bold bright_cyan]")
        ids = p.get("ids") or {}
        if ids:
            parts = [
                f"[dim]{k}=[/dim][cyan]{v}[/cyan]"
                for k, v in ids.items()
                if v and k != "unique_name"
            ]
            if parts:
                buf.print(" · ".join(parts))

        wd = _render.load_wikidata(p.get("cricsheet_id"))
        if wd and wd.get("_status") == "ok":
            buf.print("\n[bold]Wikidata[/bold]")
            age = _render._compute_age(wd.get("dob"))
            buf.print(
                f"  DOB: {wd.get('dob') or '—'}   Age: {age or '—'}   "
                f"Country: {wd.get('country_qid') or '—'}   "
                f"Birthplace: {wd.get('birthplace_qid') or '—'}"
            )
            if wd.get("image_url"):
                buf.print(f"  [dim]Photo:[/dim] {wd['image_url']}")
            social: list[str] = []
            if wd.get("twitter"):
                social.append(f"𝕏 @{wd['twitter']}")
            if wd.get("instagram"):
                social.append(f"Instagram @{wd['instagram']}")
            if wd.get("espn_id"):
                social.append(f"ESPN({wd['espn_id']})")
            if wd.get("cricbuzz_id"):
                social.append(f"Cricbuzz({wd['cricbuzz_id']})")
            if social:
                buf.print(f"  [dim]Socials:[/dim] {' · '.join(social)}")

        career = p.get("career") or {}
        if career:
            buf.print("\n[bold]Career totals[/bold]")
            for k in (
                "career_runs",
                "career_balls_faced",
                "career_innings",
                "career_sixes",
                "career_fours",
                "career_wickets",
                "career_legal_balls_bowled",
            ):
                if k in career:
                    buf.print(
                        f"  [dim]{k.replace('career_', '').replace('_', ' ').title()}:[/dim] "
                        f"[bold]{career[k]}[/bold]"
                    )

        metrics = p.get("metrics") or {}
        buf.print("\n[bold]Novel metrics[/bold]")
        for slug, hint_txt in _copy.METRIC_HINTS.items():
            payload = metrics.get(slug)
            value = _summarise_metric(payload)
            buf.print(
                f"  [cyan]{slug.replace('_', ' ').title()}:[/cyan] [bold]{value}[/bold]  "
                f"[dim italic]{hint_txt}[/dim italic]"
            )

        bayes = p.get("bayes") or {}
        buf.print("\n[bold]Bayesian scout-rating[/bold]")
        buf.print(f"  {_render.bayes_sentence(bayes, 'batter', 'Batter skill')}")
        buf.print(f"  {_render.bayes_sentence(bayes, 'bowler', 'Bowler skill')}")
        buf.print(f"  [dim italic]{_copy.BAYES_SCALE}[/dim italic]")

        twins_b = p.get("style_twins_batter") or []
        if twins_b:
            buf.print("\n[bold]Style twins (batter)[/bold]")
            for t in twins_b[:6]:
                buf.print(f"  • {t.get('name'):<28}  d={t.get('distance', 0):.4f}")

        for line in buf.export_text(clear=False, styles=False).splitlines():
            log.write(line)

    # ===== Auction Simulator ==============================================

    def _auction_sim_panel(self) -> ComposeResult:
        from cricdex.auction.real_pool import (
            IPL_TEAMS_DEFAULT,
            PERSONALITY_IDS,
            load_team_overrides,
        )

        # Persistent dict — picks survive across Run clicks. Initialised
        # from the YAML override if present, otherwise IPL defaults.
        self._team_personalities = dict(load_team_overrides() or IPL_TEAMS_DEFAULT)
        team_opts = [(t, t) for t, _ in IPL_TEAMS_DEFAULT]
        pers_opts = [(p, p) for p in PERSONALITY_IDS]

        with Vertical():
            with Horizontal(classes="controls"):
                yield Label("Type:")
                yield Select(
                    options=[("Mega", "mega"), ("Mini", "mini")],
                    value="mega",
                    id="sim-mode",
                    allow_blank=False,
                )
                yield Label("Sims:")
                yield Input(value="300", id="sim-n", classes="num")
                yield Label("Purse:")
                yield Input(value="120", id="sim-purse", classes="num")
                yield Button("Simulate ▸", id="sim-run", variant="primary")
            with Horizontal(classes="controls"):
                yield Label("Edit:")
                yield Select(options=team_opts, value="CSK", id="sim-team", allow_blank=False)
                yield Label("→")
                yield Select(
                    options=pers_opts,
                    value=self._team_personalities.get("CSK", "Balanced"),
                    id="sim-pers",
                    allow_blank=False,
                )
                yield Button("Apply", id="sim-apply", variant="success")
                yield Button("Reset", id="sim-reset", variant="warning")
            yield Static(
                self._sim_team_map_line(),
                id="sim-team-map",
                classes="intro",
            )
            yield DataTable(id="sim-table", zebra_stripes=True)
            with Horizontal(classes="controls"):
                yield Label("Find player:")
                yield Input(placeholder="name… (after a run)", id="sim-find", classes="wide")
                yield Button("Find ▸", id="sim-find-run", variant="success")
            yield DataTable(id="sim-find-table", zebra_stripes=True)

    def _sim_team_map_line(self) -> str:
        from cricdex.auction.real_pool import IPL_TEAMS_DEFAULT

        return "  ".join(
            f"{t}→[bold]{self._team_personalities.get(t, 'Balanced')}[/bold]"
            for t, _ in IPL_TEAMS_DEFAULT
        )

    def _on_apply_sim_team(self) -> None:
        team = self.query_one("#sim-team", Select).value
        personality = self.query_one("#sim-pers", Select).value
        self._team_personalities[team] = personality
        self.query_one("#sim-team-map", Static).update(self._sim_team_map_line())

    def _on_reset_sim_teams(self) -> None:
        from cricdex.auction.real_pool import IPL_TEAMS_DEFAULT

        self._team_personalities = dict(IPL_TEAMS_DEFAULT)
        self.query_one("#sim-team-map", Static).update(self._sim_team_map_line())
        # Resync the personality select to the currently-shown team.
        team = self.query_one("#sim-team", Select).value
        self.query_one("#sim-pers", Select).value = self._team_personalities[team]

    def _on_run_auction_sim(self) -> None:
        # Canonical, web-identical auction (cricdex.web_parity): same exported
        # pool + real 2025 retentions + seeded Monte-Carlo as the live site.
        table = self.query_one("#sim-table", DataTable)
        mode = self.query_one("#sim-mode", Select).value or "mega"
        try:
            n_sims = int(self.query_one("#sim-n", Input).value or "300")
            purse = float(self.query_one("#sim-purse", Input).value or "120")
        except ValueError:
            _fill_datatable(table, [{"error": "Sims and Purse must be numeric"}])
            return
        try:
            from cricdex.web_parity import (
                IPL_TEAMS_DEFAULT,
                build_pool,
                default_retentions,
                load_auction_pool,
                load_retentions,
                simulate_auction,
            )

            pool = build_pool(load_auction_pool("ipl"))
            ret = load_retentions("ipl")
            mega_ids = {t: [r["cricsheet_id"] for r in rows] for t, rows in ret["mega"].items()}
            real_prices = {
                r["cricsheet_id"]: r["price"] for rows in ret["mega"].values() for r in rows
            }
            teams = [
                {
                    "team": t["team"],
                    "personality": self._team_personalities.get(t["team"], t["personality"]),
                }
                for t in IPL_TEAMS_DEFAULT
            ]
            retentions = default_retentions(pool, teams, mode, mega_ids)
            res = simulate_auction(
                pool,
                teams,
                {
                    "purse": purse,
                    "squad_size": 25,
                    "overseas_cap": 8,
                    "trials": n_sims,
                    "mode": mode,
                    "retentions": retentions,
                    "real_prices": real_prices,
                },
            )
        except Exception as e:  # noqa: BLE001
            _fill_datatable(table, [{"error": str(e)}])
            return
        self._sim_outcomes = res["outcomes"]  # cached for the player-search below
        rows = [
            {
                "team": t["team"],
                "personality": t["personality"],
                "retained": t["retained"],
                "bought": round(t["avg_bought"]),
                "spend_cr": round(t["avg_spend"], 1),
                "squad_value": round(t["avg_value"], 1),
                "overseas": round(t["avg_overseas"]),
            }
            for t in sorted(res["teams"], key=lambda t: t["avg_value"], reverse=True)
        ]
        _fill_datatable(table, rows, max_cols=8)

    def _on_find_sim_player(self) -> None:
        # Search the last run's per-player outcomes: retained / sold / unsold.
        out = self.query_one("#sim-find-table", DataTable)
        outcomes = getattr(self, "_sim_outcomes", None)
        if not outcomes:
            _fill_datatable(out, [{"info": "run a simulation first"}])
            return
        needle = (self.query_one("#sim-find", Input).value or "").strip().lower()
        if len(needle) < 2:
            _fill_datatable(out, [{"info": "type 2+ letters"}])
            return
        hits = [o for o in outcomes if needle in o["name"].lower()]
        if not hits:
            _fill_datatable(out, [{"info": f"no player matches '{needle}'"}])
            return
        rows = []
        for o in hits[:50]:
            if o["status"] == "retained":
                where = f"{o['team']} · retained"
            elif o["status"] == "unsold":
                where = "went unsold"
            else:
                where = ", ".join(f"{w['team']} {w['pct']:.0f}%" for w in o["winners"])
            rows.append(
                {
                    "player": o["name"],
                    "role": o["role"].replace("_", "-"),
                    "status": o["status"],
                    "avg_cr": "—" if o["status"] == "unsold" else round(o["avgPrice"], 1),
                    "sold%": round(o["soldPct"]) if o["status"] == "sold" else "—",
                    "where": where,
                }
            )
        _fill_datatable(out, rows, max_cols=6)

    # ===== Scout — 3-tier look-alikes (web-identical) =====================

    def _twins_panel(self) -> ComposeResult:
        with Vertical():
            with Horizontal(classes="controls"):
                yield Label("Player:")
                yield Input(value="JJ Bumrah", id="twins-name")
                yield Label("Tier:")
                yield Select(
                    options=SCOUT_TIER_OPTIONS, value="smat", id="twins-tier", allow_blank=False
                )
                yield Label("Role:")
                yield Select(
                    options=SCOUT_ROLE_OPTIONS, value="", id="twins-role", allow_blank=False
                )
                yield Label("Top K:")
                yield Input(value="8", id="twins-k", classes="num")
                yield Button("Scout ▸", id="twins-run", variant="primary")
            yield Static("", id="twins-meta", classes="intro")
            yield DataTable(id="twins-table", zebra_stripes=True)

    def _on_run_twins(self) -> None:
        # Canonical, web-identical scout (cricdex.web_parity): same exported
        # scout_index + look-alike logic + tier-discounted pricing as the site.
        table = self.query_one("#twins-table", DataTable)
        meta = self.query_one("#twins-meta", Static)
        name = self.query_one("#twins-name", Input).value
        tier = self.query_one("#twins-tier", Select).value
        role_sel = self.query_one("#twins-role", Select).value
        try:
            top_k = int(self.query_one("#twins-k", Input).value or "8")
        except ValueError:
            top_k = 8
        try:
            from cricdex.web_parity import (
                est_value,
                gem_threshold,
                is_gem,
                load_scout_index,
                similar_to,
            )

            idx = load_scout_index("ipl")
        except FileNotFoundError as e:
            _fill_datatable(table, [{"error": str(e)}])
            return

        names = {p["name"]: p for p in idx["ipl"]}
        sel = names.get(name) or next(
            (p for n, p in names.items() if name.lower() in n.lower()), None
        )
        if sel is None:
            _fill_datatable(table, [{"error": f"no active IPL player matching '{name}'"}])
            return

        role = role_sel or sel["role"]
        sel_price = est_value(sel["value"], sel["role"], "ipl")
        gem_med = gem_threshold(idx["smat"])
        rows = []
        for r in similar_to(sel, idx[tier], role, "")[:top_k]:
            price = est_value(r["value"], r["role"], tier)
            saving = sel_price - price if price < sel_price else 0.0
            rows.append(
                {
                    "name": r["name"],
                    "country": r.get("country") or "—",
                    "last": (r.get("last_match_date") or "")[:4],
                    "est_cr": round(price, 1),
                    "save_cr": round(saving, 1) if saving > 0 else None,
                    "sim%": round(r["sim"] * 100),
                    "gem": "💎" if (tier == "smat" and is_gem(r, gem_med)) else "",
                }
            )
        tier_label = {b: a for a, b in SCOUT_TIER_OPTIONS}[tier]
        meta.update(
            f"[bold]{sel['name']}[/bold] · {role} · standing {sel['z']:.2f} · "
            f"≈ {sel_price:.1f} cr   →   {tier_label}"
        )
        _fill_datatable(table, rows or [{"info": "no close match of this archetype"}])

    # ===== Update Data ====================================================

    def _update_panel(self) -> ComposeResult:
        with Vertical():
            with Horizontal(classes="controls"):
                yield Label("Collection:")
                yield Input(value="ipl", id="upd-collection")
                yield Label("Force?")
                yield Select(
                    options=[("no", "no"), ("yes", "yes")],
                    value="no",
                    id="upd-force",
                    allow_blank=False,
                )
                yield Button("Cricsheet", id="upd-cricsheet", variant="primary")
                yield Button("Ratings", id="upd-ratings", variant="primary")
                yield Button("Metrics", id="upd-metrics", variant="primary")
            with Horizontal(classes="controls"):
                yield Button("Graph", id="upd-graph", variant="primary")
                yield Button("Rules", id="upd-rules", variant="primary")
                yield Button("Wikidata", id="upd-wikidata", variant="primary")
                yield Button("All (chained)", id="upd-all", variant="warning")
            yield Static(
                "Each button shells into `cricdex data ingest <slice> -c <collection>`. "
                "Order if running individually: cricsheet → ratings → metrics → graph. "
                "Rules + wikidata independent. `All (chained)` runs every slice in order.",
                classes="intro",
            )
            yield RichLog(id="upd-log", highlight=False, markup=True, wrap=True)

    def _run_update_slice(self, slice_: str) -> None:
        log = self.query_one("#upd-log", RichLog)
        collection = self.query_one("#upd-collection", Input).value.strip() or "ipl"
        force = self.query_one("#upd-force", Select).value == "yes"
        log.write(
            f"[bold cyan]▶[/bold cyan] ingest [bold]{slice_}[/bold] "
            f"(collection={collection}, force={force})"
        )
        try:
            from cricdex.cli.data_cmd import run_ingest

            msg = run_ingest(slice_, collection=collection, force=force)
        except Exception as e:  # noqa: BLE001
            log.write(f"[red]✗ {slice_} failed:[/red] {e}")
            return
        log.write(f"[green]✓[/green] {msg}")

    def _run_update_all(self) -> None:
        log = self.query_one("#upd-log", RichLog)
        log.write(
            "[bold]▶ chained refresh: cricsheet → ratings → metrics → graph → rules → wikidata[/bold]"
        )
        for slice_ in ("cricsheet", "ratings", "metrics", "graph", "rules", "wikidata"):
            self._run_update_slice(slice_)
        log.write("[bold green]✓ all slices complete[/bold green]")

    # ===== event dispatch ================================================

    def on_select_changed(self, event: Select.Changed) -> None:
        # Sim tab — when the team Select changes, surface that team's
        # currently-chosen personality in the personality Select so the
        # user sees what's set before they edit it.
        if getattr(event.select, "id", None) == "sim-team":
            new_team = event.value
            try:
                pers_select = self.query_one("#sim-pers", Select)
            except Exception:
                return
            pers_select.value = self._team_personalities.get(new_team, "Balanced")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        handlers = {
            "metric-run": self._on_run_leaderboard,
            "rules-run": self._on_run_rules,
            "records-run": self._on_run_records,
            "cmp-run": self._on_run_compare,
            "ven-run": self._on_run_venues,
            "auc-rec-run": self._on_run_auction_recommend,
            "auc-solve-run": self._on_run_auction_solve,
            "profile-run": self._on_run_profile,
            "sim-run": self._on_run_auction_sim,
            "sim-find-run": self._on_find_sim_player,
            "sim-apply": self._on_apply_sim_team,
            "sim-reset": self._on_reset_sim_teams,
            "twins-run": self._on_run_twins,
        }
        if event.button.id in handlers:
            handlers[event.button.id]()
            return
        # Update Data buttons
        if event.button.id == "upd-all":
            self._run_update_all()
        elif event.button.id and event.button.id.startswith("upd-"):
            slice_ = event.button.id.removeprefix("upd-")
            if slice_ in ("cricsheet", "ratings", "metrics", "graph", "rules", "wikidata"):
                self._run_update_slice(slice_)


# ---- helpers ----------------------------------------------------------------


def _summarise_metric(payload) -> str:
    if not payload:
        return "—"
    if isinstance(payload, dict):
        for key in (
            "ngi_per_match",
            "pressure_sr_per_100_balls",
            "sr",
            "runs_per_6_after_dot",
            "counter_attack_sr",
            "bdr_pct",
            "wicket_rate_pct",
            "wicket_quality",
            "longevity_index",
            "slow_start_cost",
        ):
            v = payload.get(key)
            if v is not None:
                return f"{v:.2f}" if isinstance(v, float) else str(v)
        for v in payload.values():
            if isinstance(v, int | float):
                return f"{v:.2f}" if isinstance(v, float) else str(v)
        return "—"
    return str(payload)


def run_tui() -> None:
    CricDexApp().run()
