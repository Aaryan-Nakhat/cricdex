"""Textual TUI — `cricdex tui` (also `cricdex` with no subcommand).

Modern keyboard-driven cockpit over the same library functions the
one-shot CLI uses: cricdex.profiles, cricdex.metrics, cricdex.scout,
cricdex.auction, cricdex.records, cricdex.rules. Behaviour stays in
sync because both surfaces share the same code paths.

Theming: dark surface, cyan accent. Each tab has labelled inputs
laid out horizontally, a prominent Run button, and a result area
with a loading indicator overlay while compute is in flight.

Quit: q / Ctrl-C / Esc.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from rich.console import Console
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal
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

# Same map as metrics_cmd.METRICS — primary sort col + key col.
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


def _fmt_cell(val: Any) -> str:
    """Cells get auto-rounded floats + clamped string lengths."""
    if val is None:
        return "—"
    if isinstance(val, float):
        return f"{val:.3f}" if abs(val) < 100 else f"{val:.1f}"
    return str(val)[:60]


def _fill_datatable(table: DataTable, rows: list[dict], max_cols: int = 6) -> None:
    table.clear(columns=True)
    if not rows:
        table.add_column("(no rows)")
        return
    cols = list(rows[0].keys())[:max_cols]
    table.add_columns(*cols)
    for r in rows:
        table.add_row(*(_fmt_cell(r.get(c)) for c in cols))


class CricDexApp(App):
    """Main Textual app."""

    CSS = """
    Screen {
        background: $surface;
    }
    Header {
        background: $primary;
        color: $text;
    }
    #status-bar {
        height: 1;
        background: $boost;
        color: $accent;
        padding: 0 2;
    }
    TabbedContent {
        height: 1fr;
    }
    Tabs {
        background: $surface;
    }
    .controls {
        height: auto;
        background: $panel;
        padding: 1 2;
        border: tall $primary;
        margin: 1 1 0 1;
    }
    .controls Label {
        color: $accent;
        padding: 0 1 0 0;
    }
    .controls Input {
        width: 24;
        margin: 0 1;
    }
    .controls Select {
        width: 36;
        margin: 0 1;
    }
    .controls Button {
        margin: 0 0 0 2;
    }
    DataTable {
        height: 1fr;
        margin: 1;
    }
    DataTable > .datatable--header {
        background: $boost;
        color: $accent;
        text-style: bold;
    }
    DataTable > .datatable--cursor {
        background: $primary 30%;
    }
    RichLog {
        background: $panel;
        border: tall $primary;
        margin: 1;
        padding: 0 1;
    }
    LoadingIndicator {
        color: $accent;
    }
    .intro {
        color: $text-muted;
        padding: 0 2;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("escape", "quit", "Quit"),
        Binding("ctrl+c", "quit", "Quit"),
        Binding("1", "focus_tab('tab-leaderboard')", "Leaderboard", show=False),
        Binding("2", "focus_tab('tab-profile')", "Profile", show=False),
        Binding("3", "focus_tab('tab-scout')", "Scout", show=False),
        Binding("4", "focus_tab('tab-auction')", "Auction", show=False),
        Binding("5", "focus_tab('tab-rules')", "Rules", show=False),
        Binding("6", "focus_tab('tab-records')", "Records", show=False),
    ]

    TITLE = "CricDex — open cricket intelligence"
    SUB_TITLE = "Tab to switch panels  ·  q to quit"

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Static(self._status_text(), id="status-bar")
        with TabbedContent(id="tabs"):
            with TabPane("📊  Leaderboard", id="tab-leaderboard"):
                yield from self._leaderboard_panel()
            with TabPane("🪪  Profile", id="tab-profile"):
                yield from self._profile_panel()
            with TabPane("🔗  Scout", id="tab-scout"):
                yield from self._scout_panel()
            with TabPane("💸  Auction", id="tab-auction"):
                yield from self._auction_panel()
            with TabPane("📜  Rules", id="tab-rules"):
                yield from self._rules_panel()
            with TabPane("🏆  Records", id="tab-records"):
                yield from self._records_panel()
        yield Footer()

    # ---- status -----------------------------------------------------------

    def _status_text(self) -> str:
        n = (DATA_DIR / "cricsheet" / "cricsheet.duckdb").exists()
        r = (DATA_DIR / "rules" / "qdrant").exists()
        m = (DATA_DIR / "metrics").exists()
        return (
            f"  data:  cricsheet [{'✓' if n else '✗'}]   "
            f"rules [{'✓' if r else '✗'}]   metrics [{'✓' if m else '✗'}]      "
            f"hotkeys:  1–6 tabs · q quit"
        )

    def action_focus_tab(self, tab_id: str) -> None:
        self.query_one(TabbedContent).active = tab_id

    # ---- leaderboard ------------------------------------------------------

    def _leaderboard_panel(self) -> ComposeResult:
        yield Static(_copy.LEADERBOARD_INTRO, classes="intro")
        with Container(classes="controls"):
            with Horizontal():
                yield Label("Metric:")
                yield Select(
                    options=METRIC_OPTIONS, value="ngi", id="metric-select", allow_blank=False
                )
                yield Label("Collection:")
                yield Input(value="ipl", id="metric-collection")
                yield Label("Top N:")
                yield Input(value="20", id="metric-topn")
                yield Button("Show ▸", id="metric-run", variant="primary")
        yield Static("", id="metric-hint", classes="intro")
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
        hint.update(_copy.METRIC_HINTS.get(metric, ""))
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
        # Trim cols: primary key + sort col + 4 extras
        if rows and sort_col and primary_key:
            extras = [k for k in rows[0].keys() if k not in {primary_key, sort_col}][:4]
            cols = [primary_key, sort_col, *extras]
            pruned = [{c: r.get(c) for c in cols} for r in rows]
            spark = _render.sparkline([r.get(sort_col) or 0 for r in rows])
            hint.update(f"{_copy.METRIC_HINTS.get(metric, '')}\n" f"[{sort_col}] shape: {spark}")
            _fill_datatable(table, pruned)
        else:
            _fill_datatable(table, rows)

    # ---- profile ----------------------------------------------------------

    def _profile_panel(self) -> ComposeResult:
        yield Static(_copy.PROFILE_INTRO, classes="intro")
        with Container(classes="controls"):
            with Horizontal():
                yield Label("Player:")
                yield Input(value="V Kohli", id="profile-name")
                yield Label("Collection:")
                yield Input(value="ipl", id="profile-collection")
                yield Button("Build ▸", id="profile-run", variant="primary")
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

        # Render the same blocks the one-shot `cricdex profile` shows,
        # but routed through a string-capture Console so RichLog can
        # display them (RichLog takes Renderables or markup strings).
        buf = Console(record=True, width=120, force_terminal=True, highlight=False)
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
                social.append(f"ESPNcricinfo({wd['espn_id']})")
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

        # Pump captured text into RichLog one line at a time so markup
        # is interpreted.
        captured = buf.export_text(clear=False, styles=False)
        for line in captured.splitlines():
            log.write(line)

    # ---- scout ------------------------------------------------------------

    def _scout_panel(self) -> ComposeResult:
        yield Static(_copy.TWINS_INTRO, classes="intro")
        with Container(classes="controls"):
            with Horizontal():
                yield Label("Player:")
                yield Input(value="JJ Bumrah", id="scout-name")
                yield Label("Mode:")
                yield Select(
                    options=[
                        ("Co-faced bowlers", "co_faced"),
                        ("Teammate overlap", "teammates"),
                        ("Find replacement", "find_replacement"),
                    ],
                    value="co_faced",
                    id="scout-mode",
                    allow_blank=False,
                )
                yield Label("Top K:")
                yield Input(value="15", id="scout-k")
                yield Button("Query ▸", id="scout-run", variant="primary")
        yield Static("", id="scout-meta", classes="intro")
        yield DataTable(id="scout-table", zebra_stripes=True)

    def _on_run_scout(self) -> None:
        table = self.query_one("#scout-table", DataTable)
        meta = self.query_one("#scout-meta", Static)
        name = self.query_one("#scout-name", Input).value
        mode = self.query_one("#scout-mode", Select).value
        try:
            top_k = int(self.query_one("#scout-k", Input).value or "15")
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
        # Auto-detect archetype line
        archetype, style = _detect_archetype(name)
        meta.update(
            f"auto-detected archetype: [bold]{archetype}[/bold] · "
            f"bowling style: [bold]{style}[/bold] · {len(rows)} candidates"
        )
        _fill_datatable(table, rows)

    # ---- auction ----------------------------------------------------------

    def _auction_panel(self) -> ComposeResult:
        yield Static(_copy.AUCTION_RECOMMEND_INTRO, classes="intro")
        with Container(classes="controls"):
            with Horizontal():
                yield Label("Target:")
                yield Input(value="JJ Bumrah", id="auction-target")
                yield Label("Budget (cr):")
                yield Input(value="8", id="auction-budget")
                yield Label("Role:")
                yield Input(value="bowler", id="auction-role")
                yield Label("Top N:")
                yield Input(value="10", id="auction-n")
                yield Button("Recommend ▸", id="auction-run", variant="primary")
        yield DataTable(id="auction-table", zebra_stripes=True)

    def _on_run_auction(self) -> None:
        table = self.query_one("#auction-table", DataTable)
        try:
            budget = float(self.query_one("#auction-budget", Input).value)
        except ValueError:
            _fill_datatable(table, [{"error": "budget must be a number"}])
            return
        try:
            n = int(self.query_one("#auction-n", Input).value or "10")
        except ValueError:
            n = 10
        try:
            from cricdex.auction import advisor

            rec = advisor.recommend_substitutes(
                self.query_one("#auction-target", Input).value,
                budget=budget,
                role=self.query_one("#auction-role", Input).value.strip() or None,
                n=n,
            )
        except Exception as e:  # noqa: BLE001
            _fill_datatable(table, [{"error": str(e)}])
            return
        if rec.is_empty():
            _fill_datatable(table, [{"info": "no affordable graph-similar candidates"}])
            return
        _fill_datatable(table, rec.to_dicts(), max_cols=8)

    # ---- rules ------------------------------------------------------------

    def _rules_panel(self) -> ComposeResult:
        yield Static(_copy.RULES_INTRO, classes="intro")
        with Container(classes="controls"):
            with Horizontal():
                yield Label("Question:")
                yield Input(
                    value="what is the impact player rule in IPL",
                    id="rules-q",
                )
                yield Label("Formats:")
                yield Input(value="ipl", id="rules-formats")
                yield Button("Ask ▸", id="rules-run", variant="primary")
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
        citations = res.get("citations") or []
        if citations:
            log.write("[bold]Citations:[/bold]")
            for src_id, law in citations:
                log.write(
                    f"  [dim]•[/dim] [bold]{sources.label_for(src_id)}[/bold], "
                    f"clause [cyan]{law}[/cyan]"
                )

    # ---- records ----------------------------------------------------------

    def _records_panel(self) -> ComposeResult:
        yield Static(_copy.RECORDS_INTRO, classes="intro")
        with Container(classes="controls"):
            with Horizontal():
                yield Label("Record key:")
                yield Input(value="today", id="records-key")
                yield Label("Collection:")
                yield Input(value="ipl", id="records-collection")
                yield Label("Top N:")
                yield Input(value="25", id="records-topn")
                yield Button("Show ▸", id="records-run", variant="primary")
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
        _fill_datatable(table, rows, max_cols=8)

    # ---- event dispatch ---------------------------------------------------

    def on_button_pressed(self, event: Button.Pressed) -> None:
        handlers = {
            "metric-run": self._on_run_leaderboard,
            "profile-run": self._on_run_profile,
            "scout-run": self._on_run_scout,
            "auction-run": self._on_run_auction,
            "rules-run": self._on_run_rules,
            "records-run": self._on_run_records,
        }
        handler = handlers.get(event.button.id)
        if handler:
            handler()


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
