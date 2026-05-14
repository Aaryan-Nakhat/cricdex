"""Textual TUI — `cricdex tui` (also `cricdex` with no subcommand).

11 tabs matching the 11 Streamlit dashboard pages 1-to-1:
Leaderboard / Rules / Records / Match-Report / Compare / Venues /
Auction (Solve + Recommend) / Profile / Translate / Auction-Sim /
Twins. Same code paths as the one-shot CLI, so behaviour stays in
lockstep.

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
    ("Recoverability", "recoverability"),
    ("Counter-Attack", "counter_attack"),
    ("Boundary Dependency", "boundary_dependency"),
    ("Sticky Dot Pressure", "sticky_dot_pressure"),
    ("Wicket Quality", "wicket_quality"),
    ("Phase Dilation", "phase_dilation"),
    ("Setting Tax", "setting_tax"),
]

METRIC_KEYS: dict[str, tuple[str, str]] = {
    "ngi": ("ngi_per_match", "name"),
    "pressure_runs": ("pressure_sr_per_100_balls", "batter"),
    "intent_curve": ("intent", "batter"),
    "recoverability": ("recoverability", "batter"),
    "counter_attack": ("counter_attack", "batter"),
    "boundary_dependency": ("boundary_dependency", "batter"),
    "sticky_dot_pressure": ("wicket_rate_pct", "bowler"),
    "wicket_quality": ("wicket_quality", "bowler"),
    "phase_dilation": ("phase_dilation", "batter"),
    "setting_tax": ("setting_tax", "batter"),
}

VENUE_VIEW_OPTIONS = [
    ("Innings totals", "innings"),
    ("Phase run rates", "phases"),
    ("Chase vs set winrate", "chase"),
]

TRANSLATE_OPTIONS = [
    ("Hindi", "hi"),
    ("Tamil", "ta"),
    ("Bengali", "bn"),
    ("Urdu", "ur"),
    ("Sinhala", "si"),
    ("Marathi", "mr"),
    ("Telugu", "te"),
    ("Kannada", "kn"),
]

SCOUT_MODE_OPTIONS = [
    ("Co-faced bowlers", "co_faced"),
    ("Teammate overlap", "teammates"),
    ("Find replacement", "find_replacement"),
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

    # CSS uses explicit-height controls bar + 1fr result area so the
    # bottom widget always stays in view. The earlier vertical-stack
    # layout pushed DataTable/RichLog off-screen on shorter terminals
    # because the controls panel + intro text totalled >30 rows.
    CSS = """
    Screen { background: $surface; }
    Header { background: $primary; color: $text; }
    #status-bar {
        height: 1;
        background: $boost;
        color: $accent;
        padding: 0 2;
    }
    TabbedContent { height: 1fr; }
    TabPane { padding: 0; }
    .controls {
        height: 5;
        layout: horizontal;
        background: $panel;
        border: solid $primary;
        padding: 0 1;
        margin: 1 1 0 1;
    }
    .controls Label {
        width: auto;
        padding: 1 1 0 0;
        color: $accent;
    }
    .controls Input { width: 18; margin: 0 1; }
    .controls Select { width: 28; margin: 0 1; }
    .controls Button { width: 14; margin: 1 1 0 1; }
    .intro {
        height: auto;
        max-height: 3;
        color: $text-muted;
        padding: 0 2;
    }
    DataTable {
        height: 1fr;
        margin: 1;
        border: solid $primary;
    }
    DataTable > .datatable--header {
        background: $boost;
        color: $accent;
        text-style: bold;
    }
    RichLog {
        height: 1fr;
        background: $panel;
        border: solid $primary;
        margin: 1;
        padding: 0 1;
    }
    LoadingIndicator { color: $accent; }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("escape", "quit", "Quit"),
        Binding("ctrl+c", "quit", "Quit"),
    ]

    TITLE = "CricDex — open cricket intelligence"
    SUB_TITLE = "tab/shift-tab to switch panels  ·  q to quit"

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Static(self._status_text(), id="status-bar")
        with TabbedContent(id="tabs"):
            with TabPane("📊 Leaderboard", id="tab-leaderboard"):
                yield from self._leaderboard_panel()
            with TabPane("📜 Rules", id="tab-rules"):
                yield from self._rules_panel()
            with TabPane("🏆 Records", id="tab-records"):
                yield from self._records_panel()
            with TabPane("📝 Match Report", id="tab-matchreport"):
                yield from self._matchreport_panel()
            with TabPane("🆚 Compare", id="tab-compare"):
                yield from self._compare_panel()
            with TabPane("🏟 Venues", id="tab-venues"):
                yield from self._venues_panel()
            with TabPane("💸 Auction", id="tab-auction"):
                yield from self._auction_panel()
            with TabPane("🪪 Profile", id="tab-profile"):
                yield from self._profile_panel()
            with TabPane("🌐 Translate", id="tab-translate"):
                yield from self._translate_panel()
            with TabPane("🎲 Auction Sim", id="tab-auction-sim"):
                yield from self._auction_sim_panel()
            with TabPane("🔗 Twins", id="tab-twins"):
                yield from self._twins_panel()
            with TabPane("🔄 Update Data", id="tab-update"):
                yield from self._update_panel()
        yield Footer()

    # ---- status -----------------------------------------------------------

    def _status_text(self) -> str:
        n = (DATA_DIR / "cricsheet" / "cricsheet.duckdb").exists()
        r = (DATA_DIR / "rules" / "qdrant").exists()
        m = (DATA_DIR / "metrics").exists()
        return (
            f"  data: cricsheet [{'✓' if n else '✗'}]  rules [{'✓' if r else '✗'}]  "
            f"metrics [{'✓' if m else '✗'}]   ·   tab/shift-tab switches panels  "
            f"·   q quits"
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

    # ===== Match Report ===================================================

    def _matchreport_panel(self) -> ComposeResult:
        with Vertical():
            with Horizontal(classes="controls"):
                yield Label("Match ID:")
                yield Input(value="980987", id="mr-id")
                yield Label("Coll:")
                yield Input(value="ipl", id="mr-collection")
                yield Button("Generate ▸", id="mr-run", variant="primary")
            yield Static(_copy.MATCH_REPORT_INTRO, classes="intro")
            yield RichLog(id="mr-log", highlight=False, markup=True, wrap=True)

    def _on_run_matchreport(self) -> None:
        log = self.query_one("#mr-log", RichLog)
        log.clear()
        from cricdex.config import settings

        if not (settings.gemini_api_key or settings.gemini_tmp_url):
            log.write(
                "[red]missing Gemini credential[/red]\n"
                "set via `cricdex config set gemini_api_key <key>` then re-launch the TUI."
            )
            return
        match_id = self.query_one("#mr-id", Input).value.strip()
        collection = self.query_one("#mr-collection", Input).value
        try:
            from cricdex.reports import match_report as mr

            path = mr.generate(match_id=match_id, collection=collection)
        except Exception as e:  # noqa: BLE001
            log.write(f"[red]error:[/red] {e}")
            return
        for line in path.read_text().splitlines():
            log.write(line)

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

    def _on_run_compare(self) -> None:
        table = self.query_one("#cmp-table", DataTable)
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
                yield Button("Recommend", id="auc-rec-run", variant="primary")
                yield Button("Solve MILP", id="auc-solve-run", variant="warning")
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

    # ===== Translate ======================================================

    def _translate_panel(self) -> ComposeResult:
        with Vertical():
            with Horizontal(classes="controls"):
                yield Label("Text:")
                yield Input(
                    value="Kohli pulls the short ball for six over deep mid-wicket",
                    id="tr-text",
                )
                yield Label("To:")
                yield Select(
                    options=TRANSLATE_OPTIONS,
                    value="hi",
                    id="tr-lang",
                    allow_blank=False,
                )
                yield Button("Translate ▸", id="tr-run", variant="primary")
            yield Static(_copy.TRANSLATE_INTRO, classes="intro")
            yield RichLog(id="tr-log", highlight=False, markup=True, wrap=True)

    def _on_run_translate(self) -> None:
        log = self.query_one("#tr-log", RichLog)
        log.clear()
        text = self.query_one("#tr-text", Input).value
        lang = self.query_one("#tr-lang", Select).value
        try:
            from cricdex.commentary_translate import translate as tr

            out = tr.translate(text, target=lang)
        except Exception as e:  # noqa: BLE001
            log.write(f"[red]error:[/red] {e}")
            return
        log.write(f"[bold]Input[/bold]  {text}")
        log.write(f"[bold]Output ({lang})[/bold]  [cyan]{out}[/cyan]")

    # ===== Auction Simulator ==============================================

    def _auction_sim_panel(self) -> ComposeResult:
        with Vertical():
            with Horizontal(classes="controls"):
                yield Label("Sims:")
                yield Input(value="100", id="sim-n")
                yield Label("Franch:")
                yield Input(value="10", id="sim-fr")
                yield Label("Purse:")
                yield Input(value="90", id="sim-purse")
                yield Label("Top N:")
                yield Input(value="20", id="sim-topn")
                yield Button("Simulate ▸", id="sim-run", variant="primary")
            yield Static(_copy.AUCTION_SIMULATE_INTRO, classes="intro")
            yield DataTable(id="sim-table", zebra_stripes=True)

    def _on_run_auction_sim(self) -> None:
        table = self.query_one("#sim-table", DataTable)
        try:
            n_sims = int(self.query_one("#sim-n", Input).value or "100")
            n_fr = int(self.query_one("#sim-fr", Input).value or "10")
            purse = float(self.query_one("#sim-purse", Input).value or "90")
            top_n = int(self.query_one("#sim-topn", Input).value or "20")
        except ValueError:
            _fill_datatable(table, [{"error": "all 4 inputs must be numeric"}])
            return
        try:
            from cricdex.auction import real_pool, simulator

            pool = real_pool.build_pool()
            franchises = [
                {"id": f"F{i + 1}", "purse": purse, "aggression": 1.0, "risk": 0.15}
                for i in range(n_fr)
            ]
            result = simulator.simulate(pool, franchises=franchises, n_sims=n_sims)
        except Exception as e:  # noqa: BLE001
            _fill_datatable(table, [{"error": str(e)}])
            return
        _fill_datatable(table, result["per_player"].head(top_n).to_dicts(), max_cols=8)

    # ===== Player Twins ===================================================

    def _twins_panel(self) -> ComposeResult:
        with Vertical():
            with Horizontal(classes="controls"):
                yield Label("Player:")
                yield Input(value="JJ Bumrah", id="twins-name")
                yield Label("Mode:")
                yield Select(
                    options=SCOUT_MODE_OPTIONS,
                    value="co_faced",
                    id="twins-mode",
                    allow_blank=False,
                )
                yield Label("Top K:")
                yield Input(value="15", id="twins-k")
                yield Button("Query ▸", id="twins-run", variant="primary")
            yield Static("", id="twins-meta", classes="intro")
            yield DataTable(id="twins-table", zebra_stripes=True)

    def _on_run_twins(self) -> None:
        table = self.query_one("#twins-table", DataTable)
        meta = self.query_one("#twins-meta", Static)
        name = self.query_one("#twins-name", Input).value
        mode = self.query_one("#twins-mode", Select).value
        try:
            top_k = int(self.query_one("#twins-k", Input).value or "15")
        except ValueError:
            top_k = 15
        try:
            from cricdex.scout.graph import similar
        except ImportError as e:
            _fill_datatable(table, [{"error": f"neo4j extra missing: {e}"}])
            return
        try:
            if mode == "co_faced":
                rows = similar.co_faced_bowlers(name, top_k=top_k)
            elif mode == "teammates":
                rows = similar.teammate_overlap(name, top_k=top_k)
            else:
                rows = similar.find_replacement(name, top_k=top_k)
        except Exception as e:  # noqa: BLE001
            _fill_datatable(table, [{"error": str(e)}])
            return
        archetype, style = _detect_archetype(name)
        meta.update(
            f"{_copy.TWINS_INTRO}   ·   auto-detected: [bold]{archetype}[/bold] / "
            f"[bold]{style}[/bold]   ·   {len(rows)} candidates"
        )
        _fill_datatable(table, rows)

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

    def on_button_pressed(self, event: Button.Pressed) -> None:
        handlers = {
            "metric-run": self._on_run_leaderboard,
            "rules-run": self._on_run_rules,
            "records-run": self._on_run_records,
            "mr-run": self._on_run_matchreport,
            "cmp-run": self._on_run_compare,
            "ven-run": self._on_run_venues,
            "auc-rec-run": self._on_run_auction_recommend,
            "auc-solve-run": self._on_run_auction_solve,
            "profile-run": self._on_run_profile,
            "tr-run": self._on_run_translate,
            "sim-run": self._on_run_auction_sim,
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
            "intent",
            "recoverability",
            "counter_attack",
            "boundary_dependency",
            "wicket_rate_pct",
            "wicket_quality",
            "phase_dilation",
            "setting_tax",
        ):
            v = payload.get(key)
            if v is not None:
                return f"{v:.2f}" if isinstance(v, float) else str(v)
        for v in payload.values():
            if isinstance(v, int | float):
                return f"{v:.2f}" if isinstance(v, float) else str(v)
        return "—"
    return str(payload)


def _detect_archetype(name: str) -> tuple[str, str]:
    try:
        from cricdex.scout.graph.schema import driver

        drv = driver()
        try:
            with drv.session() as s:
                row = s.run(
                    "MATCH (p:Player {unique_name: $name}) "
                    "RETURN p.balls_bowled AS bb, p.balls_faced AS bf, "
                    "p.bowling_style AS style",
                    name=name,
                ).single()
        finally:
            drv.close()
    except Exception:
        return ("unknown", "unknown")
    if row is None:
        return ("unknown", "unknown")
    bb = row.get("bb") or 0
    bf = row.get("bf") or 0
    archetype = "bowler" if bb > bf else "batter"
    style = row.get("style") or "—"
    return (archetype, style)


def run_tui() -> None:
    CricDexApp().run()
