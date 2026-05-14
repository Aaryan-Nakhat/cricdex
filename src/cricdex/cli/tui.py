"""Textual TUI — `cricdex tui` launches this.

Single screen, tabbed content. Each tab wraps one of the CLI
subcommands but binds it to widgets so the user gets immediate
feedback without retyping the whole command. The tabs reuse the same
library functions (cricdex.metrics, cricdex.scout.graph,
cricdex.auction, cricdex.profiles, cricdex.records, cricdex.rules)
so behaviour stays in sync with the one-shot CLI.

Quit: q / Ctrl-C.

Requires the `cli` extra (textual + rich): `uv sync --extra cli`.
"""

from __future__ import annotations

import json
from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.widgets import (
    Button,
    DataTable,
    Footer,
    Header,
    Input,
    Label,
    Select,
    Static,
    TabbedContent,
    TabPane,
)

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


def _fill_table(table: DataTable, rows: list[dict], max_cols: int = 6) -> None:
    table.clear(columns=True)
    if not rows:
        table.add_column("(no rows)")
        return
    cols = list(rows[0].keys())[:max_cols]
    table.add_columns(*cols)
    for r in rows:
        table.add_row(*(str(r.get(c, ""))[:60] for c in cols))


class CricDexApp(App):
    """Main Textual app."""

    CSS = """
    Screen { background: $surface; }
    Header { background: $primary; }
    #status { color: $accent; padding: 0 1; }
    TabbedContent { height: 1fr; }
    DataTable { height: 1fr; }
    Input { margin: 1 0; }
    .controls { height: auto; padding: 1; }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("ctrl+c", "quit", "Quit"),
    ]

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Static(self._status_text(), id="status")
        with TabbedContent(id="tabs"):
            with TabPane("Leaderboard", id="tab-leaderboard"):
                yield from self._leaderboard_panel()
            with TabPane("Profile", id="tab-profile"):
                yield from self._profile_panel()
            with TabPane("Scout", id="tab-scout"):
                yield from self._scout_panel()
            with TabPane("Auction", id="tab-auction"):
                yield from self._auction_panel()
            with TabPane("Rules", id="tab-rules"):
                yield from self._rules_panel()
            with TabPane("Records", id="tab-records"):
                yield from self._records_panel()
        yield Footer()

    # ---- status -----------------------------------------------------------

    def _status_text(self) -> str:
        n = (DATA_DIR / "cricsheet" / "cricsheet.duckdb").exists()
        r = (DATA_DIR / "rules" / "qdrant").exists()
        m = (DATA_DIR / "metrics").exists()
        return f"CricDex TUI  ·  data: cricsheet[{'✓' if n else '✗'}]  rules[{'✓' if r else '✗'}]  metrics[{'✓' if m else '✗'}]  ·  q to quit"

    # ---- leaderboard ------------------------------------------------------

    def _leaderboard_panel(self) -> ComposeResult:
        with Vertical(classes="controls"):
            yield Label("Metric:")
            yield Select(options=METRIC_OPTIONS, value="ngi", id="metric-select", allow_blank=False)
            yield Label("Collection:")
            yield Input(value="ipl", id="metric-collection")
            yield Button("Show top 20", id="metric-run", variant="primary")
        yield DataTable(id="metric-table")

    def _on_run_leaderboard(self) -> None:
        metric = self.query_one("#metric-select", Select).value
        collection = self.query_one("#metric-collection", Input).value
        path = Path(DATA_DIR) / "metrics" / f"{metric}_{collection}.json"
        table = self.query_one("#metric-table", DataTable)
        if not path.exists():
            _fill_table(
                table,
                [
                    {
                        "error": f"missing {path}",
                        "fix": f"`cricdex data ingest metrics -c {collection}`",
                    }
                ],
            )
            return
        rows = json.loads(path.read_text())
        if not isinstance(rows, list):
            rows = []
        rows = rows[:20]
        _fill_table(table, rows)

    # ---- profile ----------------------------------------------------------

    def _profile_panel(self) -> ComposeResult:
        with Vertical(classes="controls"):
            yield Label("Player unique_name (case sensitive):")
            yield Input(value="V Kohli", id="profile-name")
            yield Label("Collection:")
            yield Input(value="ipl", id="profile-collection")
            yield Button("Build profile", id="profile-run", variant="primary")
        yield Static("", id="profile-output", expand=True)

    def _on_run_profile(self) -> None:
        from cricdex.profiles import builder

        out = self.query_one("#profile-output", Static)
        name = self.query_one("#profile-name", Input).value
        collection = self.query_one("#profile-collection", Input).value
        try:
            p = builder.build(name, collection)
        except Exception as e:
            out.update(f"[red]error:[/red] {e}")
            return
        lines = [f"[bold cyan]{p.get('name', name)}[/bold cyan]"]
        if p.get("career"):
            lines.append("\n[bold]Career[/bold]")
            for k, v in p["career"].items():
                lines.append(f"  {k}: {v}")
        if p.get("bayes"):
            lines.append("\n[bold]Bayes scout skill[/bold]")
            for k, v in p["bayes"].items():
                lines.append(f"  {k}: {v}")
        out.update("\n".join(lines))

    # ---- scout ------------------------------------------------------------

    def _scout_panel(self) -> ComposeResult:
        with Vertical(classes="controls"):
            yield Label("Target player:")
            yield Input(value="JJ Bumrah", id="scout-name")
            yield Label("Mode:")
            yield Select(
                options=[
                    ("Co-faced bowlers", "co_faced"),
                    ("Teammate overlap", "teammates"),
                    ("Find replacement (role-aware)", "find_replacement"),
                ],
                value="co_faced",
                id="scout-mode",
                allow_blank=False,
            )
            yield Label("Role filter (only for find_replacement, blank = all):")
            yield Input(value="bowler", id="scout-role")
            yield Button("Query graph", id="scout-run", variant="primary")
        yield DataTable(id="scout-table")

    def _on_run_scout(self) -> None:
        table = self.query_one("#scout-table", DataTable)
        name = self.query_one("#scout-name", Input).value
        mode = self.query_one("#scout-mode", Select).value
        role = self.query_one("#scout-role", Input).value.strip() or None
        try:
            from cricdex.scout.graph import similar
        except ImportError as e:
            _fill_table(table, [{"error": f"neo4j extra missing: {e}"}])
            return
        try:
            if mode == "co_faced":
                rows = similar.co_faced_bowlers(name, top_k=15)
            elif mode == "teammates":
                rows = similar.teammate_overlap(name, top_k=15)
            else:
                rows = similar.find_replacement(name, top_k=15, role=role)
        except Exception as e:
            _fill_table(table, [{"error": str(e)}])
            return
        _fill_table(table, rows)

    # ---- auction ----------------------------------------------------------

    def _auction_panel(self) -> ComposeResult:
        with Vertical(classes="controls"):
            yield Label("Unavailable target:")
            yield Input(value="JJ Bumrah", id="auction-target")
            yield Label("Remaining budget (cr):")
            yield Input(value="8", id="auction-budget")
            yield Label("Role:")
            yield Input(value="bowler", id="auction-role")
            yield Button("Recommend substitutes", id="auction-run", variant="primary")
        yield DataTable(id="auction-table")

    def _on_run_auction(self) -> None:
        table = self.query_one("#auction-table", DataTable)
        try:
            budget = float(self.query_one("#auction-budget", Input).value)
        except ValueError:
            _fill_table(table, [{"error": "budget must be a number"}])
            return
        try:
            from cricdex.auction import advisor

            rec = advisor.recommend_substitutes(
                self.query_one("#auction-target", Input).value,
                budget=budget,
                role=self.query_one("#auction-role", Input).value.strip() or None,
                n=10,
            )
        except Exception as e:
            _fill_table(table, [{"error": str(e)}])
            return
        if rec.is_empty():
            _fill_table(table, [{"info": "no affordable graph-similar candidates"}])
            return
        _fill_table(table, rec.to_dicts())

    # ---- rules ------------------------------------------------------------

    def _rules_panel(self) -> ComposeResult:
        with Vertical(classes="controls"):
            yield Label("Ask a rules question (needs Gemini key):")
            yield Input(value="what is the impact player rule in IPL", id="rules-q")
            yield Label("Formats filter (comma-sep, blank = all):")
            yield Input(value="ipl", id="rules-formats")
            yield Button("Ask", id="rules-run", variant="primary")
        yield Static("", id="rules-output", expand=True)

    def _on_run_rules(self) -> None:
        out = self.query_one("#rules-output", Static)
        from cricdex.config import settings

        if not (settings.gemini_api_key or settings.gemini_tmp_url):
            out.update(
                "[red]missing Gemini credential[/red]\n"
                "set via `cricdex config set gemini_api_key <key>` then re-launch the TUI."
            )
            return
        question = self.query_one("#rules-q", Input).value
        formats = [
            f.strip() for f in self.query_one("#rules-formats", Input).value.split(",") if f.strip()
        ] or None
        try:
            from cricdex.rules.qa import answer, resolve_formats

            res = answer(question, source_ids=resolve_formats(formats), top_k=5)
        except Exception as e:
            out.update(f"[red]error:[/red] {e}")
            return
        body = [f"[bold green]A.[/bold green] {res.get('answer', '')}"]
        for cit in (res.get("citations") or [])[:5]:
            body.append(
                f"  • {cit.get('source_id', '?')} {cit.get('law_number', '')}: "
                f"{cit.get('title', '')[:80]}"
            )
        out.update("\n".join(body))

    # ---- records ----------------------------------------------------------

    def _records_panel(self) -> ComposeResult:
        with Vertical(classes="controls"):
            yield Label("Record key (or `today` for on-this-day):")
            yield Input(value="career_run_leaders", id="records-key")
            yield Label("Collection:")
            yield Input(value="ipl", id="records-collection")
            yield Button("Show", id="records-run", variant="primary")
        yield DataTable(id="records-table")

    def _on_run_records(self) -> None:
        table = self.query_one("#records-table", DataTable)
        key = self.query_one("#records-key", Input).value.strip()
        collection = self.query_one("#records-collection", Input).value
        try:
            from cricdex.records import queries

            if key == "today":
                rows = queries.on_this_day(collection=collection)
            else:
                rows = queries.top(record=key, collection=collection, top_n=25)
        except Exception as e:
            _fill_table(table, [{"error": str(e)}])
            return
        _fill_table(table, rows)

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


def run_tui() -> None:
    CricDexApp().run()
