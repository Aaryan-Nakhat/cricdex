"""Textual TUI — `cricdex tui` (also `cricdex` with no subcommand).

Tabs mirror the React web app's analytical pages plus a local refresh:
Leaders / Records / Compare / H2H / Venues / Profile / Auction / Scout / Update.
The data tabs read the SAME exported JSON the React web app + Streamlit pages
read (`site/public/data/<collection>/`). Auction + Scout run the web-identical
`cricdex.web_parity` (same as the live site). Update re-ingests + re-exports
that JSON.

Quit: q / Ctrl-C / Esc.
"""

from __future__ import annotations

import json
import subprocess
import sys
from typing import Any

from rich.console import Console
from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import (
    Button,
    DataTable,
    Footer,
    Header,
    Input,
    Label,
    LoadingIndicator,
    RichLog,
    Select,
    Static,
    TabbedContent,
    TabPane,
)
from textual_autocomplete import AutoComplete, DropdownItem

from cricdex.cli import _copy, _render
from cricdex.common import filters as cf
from cricdex.common.metrics import METRIC_BY_SLUG, METRICS
from cricdex.config import DATA_DIR
from cricdex.web_parity.loader import SITE_DATA

# Metric switcher + sort keys come straight from the shared catalog
# (cricdex.common.metrics) so the TUI can't drift from the web/Streamlit.
METRIC_OPTIONS: list[tuple[str, str]] = [(m.name, m.slug) for m in METRICS]

# Time window + filter dropdowns — Textual Select wants (label, value) pairs;
# the shared OPTS lists are (value, label), so flip them.
WINDOW_OPTIONS = [(cf.WINDOW_LABELS[w], w) for w in cf.WINDOWS]
ROLE_FILTER_OPTIONS = [(lbl, val) for val, lbl in cf.ROLE_OPTS]
BOWLING_FILTER_OPTIONS = [(lbl, val) for val, lbl in cf.BOWLING_OPTS]
POSITION_FILTER_OPTIONS = [(lbl, val) for val, lbl in cf.POSITION_OPTS]
ACTIVITY_FILTER_OPTIONS = [
    ("Active + retired", "all"),
    ("Active only", "active"),
    ("Retired only", "retired"),
]

VENUE_VIEW_OPTIONS = [
    ("Innings totals", "innings"),
    ("Phase run rates", "phases"),
    ("Chase vs set winrate", "chase"),
]

# --- record-board column labels (mirror 3_Records.py COL_LABELS) ----------
COL_LABELS: dict[str, str] = {
    "batter": "Batter",
    "bowler": "Bowler",
    "team": "Team",
    "batting_team": "Team",
    "match_date": "Date",
    "venue": "Venue",
    "runs": "Runs",
    "balls": "Balls",
    "fours": "4s",
    "sixes": "6s",
    "wickets": "Wkts",
    "runs_conceded": "Runs",
    "match_id": "Match",
    "total": "Total",
    "total_runs": "Total",
    "over_runs": "Runs",
}

PHASE_ORDER = ["powerplay", "middle", "death"]

# --- mirror 5_Compare.py ROWS (group, label, profile-path, digits) -------
COMPARE_ROWS: list[tuple[str, str, tuple[str, ...], int]] = [
    ("Bayesian skill", "Batting · scoring", ("bayes", "bayes_batter", "skill"), 3),
    ("Bayesian skill", "Batting · survival", ("bayes", "bayes_batter", "survival_skill"), 3),
    ("Bayesian skill", "Batting value", ("bayes", "bayes_batter", "value"), 3),
    ("Bayesian skill", "Bowling · economy", ("bayes", "bayes_bowler", "skill"), 3),
    ("Bayesian skill", "Bowling · strike", ("bayes", "bayes_bowler", "strike_skill"), 3),
    ("Career", "Runs", ("career", "career_runs"), 0),
    ("Career", "Balls faced", ("career", "career_balls_faced"), 0),
    ("Career", "Wickets", ("career", "career_wickets"), 0),
    ("Metrics", "Pressure SR", ("metrics", "pressure_runs", "pressure_sr_per_100_balls"), 1),
    ("Metrics", "Counter-attack SR", ("metrics", "counter_attack", "counter_attack_sr"), 1),
    ("Metrics", "Boundary %", ("metrics", "boundary_dependency", "bdr_pct"), 1),
    ("Metrics", "Dot recovery", ("metrics", "dot_ball_recovery", "runs_per_6_after_dot"), 2),
]

SCOUT_TIER_OPTIONS = [
    ("IPL peers", "ipl"),
    ("Uncapped · SMAT", "smat"),
    ("Overseas · BBL", "bbl"),
    ("Overseas · SA20", "sa20"),
    ("Overseas · CPL", "cpl"),
    ("Overseas · T20 Blast", "blast"),
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


# Semantic colours for the status column (retained / sold / unsold) — the only
# place we colour by value, since it's unambiguous (metric ± is lower/higher-
# better per-metric, so we never blanket-colour those).
_STATUS_STYLE = {"retained": "cyan", "sold": "green", "unsold": "red"}


def _styled_cell(col: str, val: Any, accent_col: str | None) -> Any:
    """Base-format a cell, then add a tasteful style: bold-accent the headline
    column, colour the status column, green a positive saving."""
    base = _fmt_cell(val)
    style = ""
    if col == accent_col:
        style = "bold #7aa2f7"  # accent (tokyo-night blue); readable on any theme
    elif col == "status" and isinstance(val, str):
        style = _STATUS_STYLE.get(val, "")
    elif col in {"save_cr", "Save cr"} and isinstance(val, int | float) and val:
        style = "green"
    if not style:
        return base
    return Text(str(base.plain if isinstance(base, Text) else base), style=style, overflow="fold")


def _fill_datatable(
    table: DataTable, rows: list[dict], max_cols: int = 8, accent_col: str | None = None
) -> None:
    """Populate a DataTable with auto-wrapping cells. We compute row
    heights from the longest cell content so wraps render correctly.
    `accent_col` (a column key) is rendered bold-accent — the headline metric."""
    table.clear(columns=True)
    if not rows:
        table.add_column("(no rows)")
        return
    cols = list(rows[0].keys())[:max_cols]
    table.add_columns(*cols)
    for r in rows:
        cells = tuple(_styled_cell(c, r.get(c), accent_col) for c in cols)
        # Auto-grow row height to fit the longest folded cell.
        longest = max(
            (len(str(r.get(c))) for c in cols if r.get(c) is not None),
            default=20,
        )
        # ~32 chars per column line on a 160-wide screen with 8 cols.
        height = max(1, min(4, (longest // 32) + 1))
        table.add_row(*cells, height=height)


def _plotext_chart(build_fn, width: int = 88, height: int = 16) -> Text:
    """Build a plotext figure into a Rich Text (ANSI) so it can drop into a
    Static — the desktop stand-in for the web's Recharts plots. `build_fn(plt)`
    draws onto the cleared canvas; theme 'clear' keeps it monochrome so it sits
    on any Textual background."""
    import plotext as plt

    plt.clf()
    plt.plotsize(width, height)
    plt.theme("pro")  # dark + per-series colour (btop-meter look)
    build_fn(plt)
    return Text.from_ansi(plt.build())


def _h2h_gauge(a: str, b: str, items: list[tuple[str, float, str]], width: int = 36) -> Text:
    """Two-colour P(A>B) gauge, one row per role: the first `pa%` of the bar in
    green (A), the rest in red (B), on a fixed 0–100 scale so 41% reads as 41%."""
    out = Text()
    for role, pa, verdict in items:
        fill = max(0, min(width, round(pa / 100 * width)))
        out.append(f"{role:<10} ", style="bold")
        out.append("█" * fill, style="green")
        out.append("█" * (width - fill), style="red")
        out.append(f"  {a} {pa:.0f}%  ·  {b} {100 - pa:.0f}%", style="bold")
        out.append(f"   {verdict}\n", style="dim italic")
    return out


# Themes offered by the `t` cycle (a curated subset of Textual's built-ins,
# btop/abtop-style). The command palette (ctrl+p) can reach all of them.
THEMES = ["tokyo-night", "nord", "catppuccin-mocha", "dracula", "gruvbox", "monokai"]


def _player_candidates(collection: str = "ipl") -> list[DropdownItem]:
    """Autocomplete candidates 'Full Name (Short)' from players.json — typing
    either the full or scorecard name fuzzy-filters the dropdown (web-parity)."""
    path = SITE_DATA / collection / "players.json"
    if not path.exists():
        return []
    try:
        players = json.loads(path.read_text())
    except (ValueError, OSError):
        return []
    items = []
    for p in sorted(players, key=lambda x: x.get("name", "")):
        short = p.get("name", "")
        full = p.get("full_name")
        items.append(DropdownItem(f"{full} ({short})" if full and full != short else short))
    return items


def _auction_pool_candidates(collection: str = "ipl") -> list[DropdownItem]:
    """Autocomplete candidates restricted to the auction pool (the ~600 active,
    priced players) — NOT all of players.json — so the Find-player dropdown can't
    offer retired/non-pool names. Labels join full_name from players.json."""
    try:
        from cricdex.web_parity import load_auction_pool

        pool = load_auction_pool(collection)
    except Exception:  # noqa: BLE001
        return []
    full: dict[str, str] = {}
    pj = SITE_DATA / collection / "players.json"
    if pj.exists():
        try:
            full = {p["cricsheet_id"]: p.get("full_name") for p in json.loads(pj.read_text())}
        except (ValueError, OSError):
            full = {}
    items = []
    for p in sorted(pool, key=lambda x: x.get("name", "")):
        short = p.get("name", "")
        f = full.get(p.get("cricsheet_id", ""))
        items.append(DropdownItem(f"{f} ({short})" if f and f != short else short))
    return items


def _name_from_label(label: str) -> str:
    """'Jasprit Bumrah (JJ Bumrah)' → 'JJ Bumrah' (the scorecard name the
    handlers resolve on); a bare name passes through unchanged."""
    label = (label or "").strip()
    if label.endswith(")") and " (" in label:
        return label[label.rfind(" (") + 2 : -1]
    return label


def _venue_options(collection: str = "ipl") -> list[tuple[str, str]]:
    """(value, label) venue pairs for the native Select dropdown."""
    path = SITE_DATA / collection / "venues.json"
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text())
    except (ValueError, OSError):
        return []
    return [(v, v) for v in sorted(data)]


def _collection_options() -> list[tuple[str, str]]:
    """(value, label) collection pairs for the `Coll` Selects — from
    collections.json, falling back to a dir scan then ['ipl']."""
    f = SITE_DATA / "collections.json"
    cols: list[str] = []
    if f.exists():
        try:
            cols = [c["collection"] for c in json.loads(f.read_text())]
        except (ValueError, OSError, KeyError, TypeError):
            cols = []
    if not cols and SITE_DATA.exists():
        cols = sorted(d.name for d in SITE_DATA.iterdir() if d.is_dir())
    return [(c, c) for c in (cols or ["ipl"])]


# Record-board slug → label (same 9 boards as dashboard/pages/3_Records.py).
RECORD_LABELS: dict[str, str] = {
    "highest_individual_innings": "Highest individual innings",
    "fastest_fifty": "Fastest fifties",
    "fastest_hundred": "Fastest hundreds",
    "most_sixes_innings": "Most sixes in an innings",
    "career_run_leaders": "Career run leaders",
    "best_bowling_innings": "Best bowling figures",
    "career_wicket_leaders": "Career wicket leaders",
    "highest_team_totals": "Highest team totals",
    "highest_runs_in_over": "Most runs in an over",
}


def _record_board_options(collection: str = "ipl") -> list[tuple[str, str]]:
    """(label, slug) record-board pairs for the Records `Key` Select — Textual
    Select wants (display, value), so the human label shows and the slug is the
    value. Boards present in records.json, labelled via RECORD_LABELS."""
    path = SITE_DATA / collection / "records.json"
    present: list[str] = []
    if path.exists():
        try:
            present = list(json.loads(path.read_text()))
        except (ValueError, OSError):
            present = []
    slugs = [k for k in RECORD_LABELS if not present or k in present]
    slugs += [k for k in present if k not in RECORD_LABELS]
    return [(RECORD_LABELS.get(s, s.replace("_", " ").title()), s) for s in slugs]


class Panel(Vertical):
    """A titled, bordered section box (the btop-style panel). The title sits in
    the top border; pass `title=` and it shows once mounted."""

    def __init__(self, *children, title: str = "", **kwargs) -> None:
        super().__init__(*children, **kwargs)
        self._title = title

    def on_mount(self) -> None:
        self.border_title = self._title


class ControlBar(Horizontal):
    """A titled, bordered horizontal control strip (filters / params)."""

    def __init__(self, *children, title: str = "", **kwargs) -> None:
        super().__init__(*children, classes="controls", **kwargs)
        self._title = title

    def on_mount(self) -> None:
        self.border_title = self._title


def _tabhead(title: str, subtitle: str = "") -> Static:
    """Accent header line at the top of a tab — '▌ LEADERS · Net Game Impact'."""
    text = f"[b]▌ {title}[/b]" + (f"  [dim]·  {subtitle}[/dim]" if subtitle else "")
    return Static(text, classes="tabhead")


class CricDexApp(App):
    """Main Textual app — tabs mirror the React web app's analytical pages."""

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
    Tab { padding: 0 2; color: $text-muted; }
    Tab.-active { color: $accent; text-style: bold; }
    TabPane { padding: 0; }

    /* Per-tab accent header line ("▌ LEADERS · Net Game Impact"). */
    .tabhead {
        height: auto;
        padding: 1 2 0 2;
        color: $accent;
        text-style: bold;
    }

    /* Titled, bordered section boxes — the btop/abtop panel look. Inactive
       panels recede (muted border); the focused one glows accent. */
    Panel {
        height: 1fr;
        border: round $surface-lighten-2;
        border-title-color: $text-muted;
        border-title-style: bold;
        padding: 1 2;
        margin: 1 1 0 1;
    }
    Panel:focus-within {
        border: heavy $accent;
        border-title-color: $accent;
    }
    .controls {
        height: auto;
        layout: horizontal;
        align-vertical: middle;
        background: $panel;
        border: round $surface-lighten-2;
        border-title-color: $text-muted;
        border-title-style: bold;
        padding: 1;
        margin: 1 1 0 1;
    }
    .controls:focus-within {
        border: heavy $accent;
        border-title-color: $accent;
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
        max-height: 4;
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
    DataTable > .datatable--cursor { background: $accent; color: $background; text-style: bold; }
    /* Tables inside a Panel: drop the redundant inner border/margin. */
    Panel DataTable { border: none; margin: 0; }
    RichLog {
        height: 1fr;
        background: $panel;
        border: round $primary;
        margin: 1;
        padding: 0 1;
    }
    Panel RichLog { border: none; margin: 0; background: $surface; }
    LoadingIndicator { color: $accent; height: 1; }
    /* Inline spinner shown next to a Run button while a worker runs. */
    .spinner { height: 1; width: 16; display: none; }
    .spinner.run { display: block; }
    VerticalScroll { height: 1fr; }
    .chart {
        height: auto;
        padding: 0 1;
        margin: 0 1;
        color: $text;
    }
    /* Tabs that pair a table with a plotext chart: let the table size to its
       rows (capped) so the chart below stays visible; the VerticalScroll
       handles any overflow. */
    #cmp-table { height: auto; max-height: 16; }
    #cmp-h2h-table { height: auto; max-height: 9; }
    #ven-table { height: auto; max-height: 12; }
    #h2h-table { height: auto; max-height: 10; }
    #sim-table { height: auto; max-height: 14; }
    #sim-find-table { height: auto; max-height: 12; }
    #sim-marquee { height: auto; max-height: 12; }
    #sim-squad { height: auto; max-height: 18; }
    /* Panels inside a scroll size to their content so the page (not the panel)
       scrolls — keeps the Auction Squads/Player-search reachable. */
    VerticalScroll Panel { height: auto; }
    /* Long-label Selects need more room than the default 22. */
    #records-key { width: 32; }
    #ven-name { width: 28; }
    /* Key-hint bar — accent keys, muted labels (lazygit/k9s style). */
    Footer { background: $panel; }
    Footer > .footer-key--key { color: $accent; text-style: bold; background: $panel; }
    Footer > .footer-key--description { color: $text-muted; background: $panel; }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("ctrl+c", "quit", "Quit"),
        Binding("right", "next_tab", "Next tab"),
        Binding("left", "prev_tab", "Prev tab"),
        Binding("t", "cycle_theme", "Theme"),
        Binding("ctrl+p", "command_palette", "Palette"),
    ]

    TITLE = "CricDex — open cricket intelligence"
    SUB_TITLE = "← → panels · t theme · q quit"

    def on_mount(self) -> None:
        # Built-in nord theme — clean dark palette, good contrast. `t` cycles
        # THEMES; the command palette (ctrl+p) reaches every built-in theme.
        self.theme = "tokyo-night"
        self._refresh_status()
        self._seed_hints()

    def _seed_hints(self) -> None:
        """Fill result tables with a one-line prompt so they don't read as
        broken empty grids before the first run."""
        hints = {
            "#metric-table": "Pick a metric + filters, then Show ▸",
            "#records-table": "Pick a board, then Show ▸",
            "#cmp-table": "Enter two players, then Compare ▸",
            "#h2h-table": "Enter two players, then Compare ▸",
            "#ven-table": "Enter a venue, then Show ▸",
            "#twins-table": "Pick a player + tier, then Scout ▸",
            "#sim-table": "Set the knobs, then Simulate ▸",
            "#sim-find-table": "Run a simulation, then search a player",
        }
        for tid, msg in hints.items():
            try:
                _fill_datatable(self.query_one(tid, DataTable), [{"": msg}])
            except Exception:  # noqa: BLE001 — table not mounted (shouldn't happen)
                pass

    def action_cycle_theme(self) -> None:
        try:
            i = THEMES.index(self.theme)
        except ValueError:
            i = -1
        self.theme = THEMES[(i + 1) % len(THEMES)]
        self._refresh_status()
        self.notify(f"theme: {self.theme}", timeout=1.5)

    def _refresh_status(self) -> None:
        try:
            self.query_one("#status-bar", Static).update(self._status_text())
        except Exception:  # noqa: BLE001 — status bar not mounted yet
            pass

    def _sel_value(self, selector: str, default: str = "ipl") -> str:
        """Current value of a Select (used by the player autocompletes to follow
        the tab's collection); `default` when blank/unmounted."""
        try:
            v = self.query_one(selector, Select).value
        except Exception:  # noqa: BLE001
            return default
        return default if v is Select.BLANK or not v else str(v)

    def _player_cands(self, coll_selector: str):
        """Autocomplete `candidates` callable that follows a tab's Coll Select —
        the dropdown re-lists players for the currently-selected collection."""
        return lambda _state: _player_candidates(self._sel_value(coll_selector))

    _TAB_ORDER = [
        "tab-leaderboard",
        "tab-records",
        "tab-compare",
        "tab-h2h",
        "tab-venues",
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
            with TabPane("Records", id="tab-records"):
                yield from self._records_panel()
            with TabPane("Compare", id="tab-compare"):
                yield from self._compare_panel()
            with TabPane("H2H", id="tab-h2h"):
                yield from self._h2h_panel()
            with TabPane("Venues", id="tab-venues"):
                yield from self._venues_panel()
            with TabPane("Profile", id="tab-profile"):
                yield from self._profile_panel()
            with TabPane("Auction", id="tab-auction-sim"):
                yield from self._auction_sim_panel()
            with TabPane("Scout", id="tab-twins"):
                yield from self._twins_panel()
            with TabPane("Update", id="tab-update"):
                yield from self._update_panel()
        yield Footer()

    # ---- status -----------------------------------------------------------

    def _status_text(self) -> str:
        n = (DATA_DIR / "cricsheet" / "cricsheet.duckdb").exists()
        j = (SITE_DATA / "ipl" / "leaderboards").is_dir()
        theme = getattr(self, "theme", "nord")
        return (
            f"  data: cricsheet [{'✓' if n else '✗'}]  exported-json [{'✓' if j else '✗'}]"
            f"   ·   theme: {theme} (t)   ·   ← → panels   ·   q quit"
        )

    # ===== Leaderboard ====================================================

    def _leaderboard_panel(self) -> ComposeResult:
        with Vertical():
            yield _tabhead("LEADERS", "10 novel impact metrics")
            with ControlBar(title="Metric"):
                yield Label("Metric:")
                yield Select(
                    options=METRIC_OPTIONS, value="ngi", id="metric-select", allow_blank=False
                )
                yield Label("Window:")
                yield Select(
                    options=WINDOW_OPTIONS, value="all", id="metric-window", allow_blank=False
                )
                yield Label("Coll:")
                yield Select(
                    options=_collection_options(),
                    value="ipl",
                    id="metric-collection",
                    allow_blank=False,
                )
                yield Label("Top N:")
                yield Input(value="20", id="metric-topn", classes="num")
                yield Button("Show ▸", id="metric-run", variant="primary")
            with ControlBar(title="Filters"):
                yield Label("Role:")
                yield Select(
                    options=ROLE_FILTER_OPTIONS, value="", id="metric-role", allow_blank=False
                )
                yield Label("Bowling:")
                yield Select(
                    options=BOWLING_FILTER_OPTIONS, value="", id="metric-bowling", allow_blank=False
                )
                yield Label("Position:")
                yield Select(
                    options=POSITION_FILTER_OPTIONS,
                    value="",
                    id="metric-position",
                    allow_blank=False,
                )
                yield Label("Activity:")
                yield Select(
                    options=ACTIVITY_FILTER_OPTIONS,
                    value="all",
                    id="metric-activity",
                    allow_blank=False,
                )
                yield Label("Min mts:")
                yield Input(value="20", id="metric-minmatches", classes="num")
                yield Label("Country:")
                yield Input(placeholder="e.g. IND", id="metric-country", classes="num")
            yield Static(_copy.LEADERBOARD_INTRO, id="metric-hint", classes="intro")
            with Panel(title="Leaderboard"):
                yield DataTable(id="metric-table", zebra_stripes=True)

    def _on_run_leaderboard(self) -> None:
        metric = self.query_one("#metric-select", Select).value
        window = self.query_one("#metric-window", Select).value or "all"
        collection = self.query_one("#metric-collection", Select).value
        table = self.query_one("#metric-table", DataTable)
        hint = self.query_one("#metric-hint", Static)
        try:
            top_n = int(self.query_one("#metric-topn", Input).value or "20")
        except ValueError:
            top_n = 20
        try:
            rows = cf.load_leaderboard(collection, metric, window)
        except FileNotFoundError as e:
            _fill_datatable(table, [{"error": str(e)}])
            return
        if not isinstance(rows, list):
            rows = []

        # Full web FilterBar via the shared port.
        try:
            min_matches = int(self.query_one("#metric-minmatches", Input).value or "0")
        except ValueError:
            min_matches = 0
        filters = cf.Filters(
            min_matches=min_matches,
            role=self.query_one("#metric-role", Select).value or "",
            bowling=self.query_one("#metric-bowling", Select).value or "",
            position=self.query_one("#metric-position", Select).value or "",
            activity=self.query_one("#metric-activity", Select).value or "all",
            country=(self.query_one("#metric-country", Input).value or "").strip(),
        )
        total = len(rows)
        rows = cf.apply_filters(rows, filters)
        kept = len(rows)

        m = METRIC_BY_SLUG.get(metric)
        sort_col = m.sort_col if m else None
        primary_key = m.name_col if m else None
        higher = m.higher_is_better if m else True
        if sort_col:
            rows = sorted(
                rows,
                key=lambda r: (r.get(sort_col) is None, r.get(sort_col) or 0),
                reverse=higher,
            )
        rows = rows[:top_n]
        if rows and sort_col and primary_key:
            extras = [k for k in rows[0].keys() if k not in {primary_key, sort_col}][:4]
            cols = [primary_key, sort_col, *extras]
            pruned = []
            for r in rows:
                row: dict[str, Any] = {}
                for c in cols:
                    v = r.get(c)
                    # Intent-Curve: render the per-innings SR list as an inline
                    # sparkline cell, exactly like the web's mini bar-chart.
                    if c == "curve" and isinstance(v, list):
                        v = _render.sparkline(v)
                    row[c] = v
                pruned.append(row)
            spark = _render.sparkline([r.get(sort_col) or 0 for r in rows])
            arrow = "▲ higher better" if higher else "▼ lower better"
            hint.update(
                f"{_copy.METRIC_HINTS.get(metric, '')}   ·   {arrow}   ·   "
                f"{kept}/{total} after filters   ·   [{sort_col}] shape: {spark}"
            )
            _fill_datatable(table, pruned, accent_col=sort_col)
        else:
            hint.update(f"{kept}/{total} after filters — none match, loosen the filters.")
            _fill_datatable(table, rows or [{"info": "no players match these filters"}])

    # ===== Records ========================================================

    def _records_panel(self) -> ComposeResult:
        with Vertical():
            yield _tabhead("RECORDS", "all-time & seasonal record books")
            with ControlBar(title="Board"):
                yield Label("Key:")
                yield Select(
                    options=_record_board_options(),
                    value="highest_individual_innings",
                    id="records-key",
                    allow_blank=False,
                )
                yield Label("Coll:")
                yield Select(
                    options=_collection_options(),
                    value="ipl",
                    id="records-collection",
                    allow_blank=False,
                )
                yield Label("Top N:")
                yield Input(value="25", id="records-topn", classes="num")
                yield Label("From:")
                yield Input(placeholder="year", id="records-from", classes="num")
                yield Label("To:")
                yield Input(placeholder="year", id="records-to", classes="num")
                yield Button("Show ▸", id="records-run", variant="primary")
            yield Static(_copy.RECORDS_INTRO, classes="intro")
            with Panel(title="Records"):
                yield DataTable(id="records-table", zebra_stripes=True)

    def _on_run_records(self) -> None:
        # Reads the same exported records.json the React app + 3_Records.py read:
        # {board-name -> [rows]}. The "Key" picks a board; default board is
        # highest_individual_innings. On an unknown key we list the valid ones.
        table = self.query_one("#records-table", DataTable)
        key = str(self.query_one("#records-key", Select).value or "").strip()
        collection = self.query_one("#records-collection", Select).value
        try:
            top_n = int(self.query_one("#records-topn", Input).value or "25")
        except ValueError:
            top_n = 25
        path = SITE_DATA / collection / "records.json"
        if not path.exists():
            _fill_datatable(
                table,
                [{"error": f"missing {path.name}", "fix": "run scripts/export_site.py"}],
            )
            return
        data = json.loads(path.read_text())
        if not isinstance(data, dict):
            _fill_datatable(table, [{"error": "records.json is not a board map"}])
            return
        valid = [k for k in data if data.get(k)]
        if key == "today" or not key:
            key = "highest_individual_innings"
        if key not in data:
            _fill_datatable(
                table,
                [{"error": f"unknown board `{key}`", "valid_keys": ", ".join(valid)}],
            )
            return
        rows = list(data.get(key) or [])
        # Optional year-range filter on dated boards (mirror Records.tsx range).
        yr_from = _num(self.query_one("#records-from", Input).value)
        yr_to = _num(self.query_one("#records-to", Input).value)
        if (yr_from or yr_to) and rows and rows[0].get("match_date"):
            lo = yr_from or float("-inf")
            hi = yr_to or float("inf")
            rows = [
                r
                for r in rows
                if (y := _num((r.get("match_date") or "")[:4])) is None or lo <= y <= hi
            ]
        # Records.tsx / 3_Records.py drop the match_id column from the display.
        rows = [{k: v for k, v in r.items() if k != "match_id"} for r in rows][:top_n]
        rows = [{COL_LABELS.get(k, k.replace("_", " ")): v for k, v in r.items()} for r in rows]
        _fill_datatable(table, rows or [{"info": f"no rows for board `{key}`"}], max_cols=10)

    # ===== Compare ========================================================

    def _compare_panel(self) -> ComposeResult:
        with Vertical():
            yield _tabhead("COMPARE", "side-by-side across every number")
            with ControlBar(title="Players"):
                yield Label("Player A:")
                yield Input(value="V Kohli", id="cmp-a")
                yield Label("Player B:")
                yield Input(value="RG Sharma", id="cmp-b")
                yield Label("Coll:")
                yield Select(
                    options=_collection_options(),
                    value="ipl",
                    id="cmp-collection",
                    allow_blank=False,
                )
                yield Button("Compare ▸", id="cmp-run", variant="primary")
            yield AutoComplete(target="#cmp-a", candidates=self._player_cands("#cmp-collection"))
            yield AutoComplete(target="#cmp-b", candidates=self._player_cands("#cmp-collection"))
            yield Static(_copy.COMPARE_INTRO, classes="intro")
            with VerticalScroll():
                yield DataTable(id="cmp-table", zebra_stripes=True)
                yield Static("Skill shape — four Bayesian axes (0–100 scaled)", classes="intro")
                yield Static("", id="cmp-chart", classes="chart")
                yield Static("Bayesian skill head-to-head", classes="intro")
                yield DataTable(id="cmp-h2h-table", zebra_stripes=True)

    def _on_run_compare(self) -> None:
        # Reads the same exported profiles/<cid>.json for both players (via
        # players.json), mirroring 5_Compare.py's side-by-side rows. Keeps the
        # Bayesian head-to-head P(A>B) block below.
        table = self.query_one("#cmp-table", DataTable)
        h2h_table = self.query_one("#cmp-h2h-table", DataTable)
        a = _name_from_label(self.query_one("#cmp-a", Input).value)
        b = _name_from_label(self.query_one("#cmp-b", Input).value)
        collection = self.query_one("#cmp-collection", Select).value

        loaded: list[tuple[str, dict]] = []
        for nm in (a, b):
            cid = _resolve_cid(collection, nm)
            prof = _load_profile(collection, cid) if cid else None
            if prof is None:
                _fill_datatable(table, [{"error": f"no exported profile for '{nm}'"}])
                return
            loaded.append((nm, prof))

        rows: list[dict] = []
        for group, label, path, digits in COMPARE_ROWS:
            rows.append(
                {
                    "group": group,
                    "metric": label,
                    a: _fmt_num(_dig(loaded[0][1], *path), digits),
                    b: _fmt_num(_dig(loaded[1][1], *path), digits),
                }
            )
        # Strike rate is derived (career_runs / career_balls_faced * 100).
        rows.insert(
            7,
            {
                "group": "Career",
                "metric": "Strike rate",
                a: _fmt_num(_strike_rate(loaded[0][1]), 1),
                b: _fmt_num(_strike_rate(loaded[1][1]), 1),
            },
        )
        _fill_datatable(table, rows, max_cols=10)

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
        _fill_datatable(
            h2h_table,
            rows_h or [{"info": "no overlapping Bayesian ratings for these two"}],
            max_cols=6,
        )

        # Skill-shape chart — four Bayesian axes, scaled 0–100 (mirrors the web
        # Compare radar; plotext has no radar so grouped bars carry the shape).
        axes = ["Bat score", "Bat survive", "Bowl econ", "Bowl strike"]
        paths = [
            ("bayes", "bayes_batter", "skill"),
            ("bayes", "bayes_batter", "survival_skill"),
            ("bayes", "bayes_bowler", "skill"),
            ("bayes", "bayes_bowler", "strike_skill"),
        ]

        def _scaled(prof: dict) -> list[float]:
            out = []
            for p in paths:
                v = _dig(prof, *p)
                out.append(max(0.0, min(100.0, (v + 0.6) / 1.2 * 100)) if v is not None else 0.0)
            return out

        series = [_scaled(loaded[0][1]), _scaled(loaded[1][1])]
        chart = self.query_one("#cmp-chart", Static)
        if not any(v for s in series for v in s):
            chart.update("no Bayesian skill data to chart for these two players")
        else:
            try:
                chart.update(
                    _plotext_chart(
                        lambda plt: (
                            plt.multiple_bar(axes, series, labels=[a, b]),
                            plt.title("Skill shape (0–100)"),
                        )
                    )
                )
            except Exception as e:  # noqa: BLE001
                chart.update(f"(chart unavailable: {e})")

    # ===== Head-to-head ===================================================

    def _h2h_panel(self) -> ComposeResult:
        with Vertical():
            yield _tabhead("HEAD-TO-HEAD", "P(A better than B) from the posteriors")
            with ControlBar(title="Players"):
                yield Label("Player A:")
                yield Input(value="V Kohli", id="h2h-a")
                yield Label("Player B:")
                yield Input(value="RG Sharma", id="h2h-b")
                yield Label("Coll:")
                yield Select(
                    options=_collection_options(),
                    value="ipl",
                    id="h2h-collection",
                    allow_blank=False,
                )
                yield Button("Compare ▸", id="h2h-run", variant="primary")
            yield AutoComplete(target="#h2h-a", candidates=self._player_cands("#h2h-collection"))
            yield AutoComplete(target="#h2h-b", candidates=self._player_cands("#h2h-collection"))
            yield Static(
                "P(A is better than B) from the Bayesian skill posteriors, role by role.",
                classes="intro",
            )
            with VerticalScroll():
                yield DataTable(id="h2h-table", zebra_stripes=True)
                yield Static("P(A better) by role — 50% = too close to call", classes="intro")
                yield Static("", id="h2h-chart", classes="chart")

    def _on_run_h2h(self) -> None:
        table = self.query_one("#h2h-table", DataTable)
        chart = self.query_one("#h2h-chart", Static)
        a = _name_from_label(self.query_one("#h2h-a", Input).value)
        b = _name_from_label(self.query_one("#h2h-b", Input).value)
        collection = self.query_one("#h2h-collection", Select).value
        from cricdex.scout.ratings.head_to_head import head_to_head

        res = head_to_head(a, b, collection=collection)
        if res.get("error"):
            _fill_datatable(table, [{"error": res["error"]}])
            chart.update("")
            return
        rows: list[dict] = []
        gauge: list[tuple[str, float, str]] = []
        for role in ("batter", "bowler", "all_rounder"):
            c = res["comparisons"].get(role)
            if c is None:
                continue
            rows.append(
                {
                    "role": role,
                    a: f"{c['mean_a']:+.3f}±{c['sd_a']:.2f}",
                    b: f"{c['mean_b']:+.3f}±{c['sd_b']:.2f}",
                    f"P({a}>)": f"{c['p_a_better']:.0%}",
                    "verdict": c["verdict"],
                }
            )
            gauge.append((role.replace("_", "-"), round(c["p_a_better"] * 100, 1), c["verdict"]))
        _fill_datatable(table, rows or [{"info": "no overlapping role to compare"}], max_cols=6)
        chart.update(_h2h_gauge(a, b, gauge) if gauge else "")

    # ===== Venues =========================================================

    def _venues_panel(self) -> ComposeResult:
        ven_opts = _venue_options("ipl")
        ven_default = (
            "Eden Gardens" if any(v == "Eden Gardens" for v, _ in ven_opts) else Select.BLANK
        )
        with Vertical():
            yield _tabhead("VENUES", "ground conditions — totals, phases, chase")
            with ControlBar(title="Venue"):
                yield Label("Venue:")
                yield Select(options=ven_opts, value=ven_default, id="ven-name", classes="wide")
                yield Label("Coll:")
                yield Select(
                    options=_collection_options(),
                    value="ipl",
                    id="ven-collection",
                    allow_blank=False,
                )
                yield Label("View:")
                yield Select(
                    options=VENUE_VIEW_OPTIONS,
                    value="innings",
                    id="ven-view",
                    allow_blank=False,
                )
                yield Button("Show ▸", id="ven-run", variant="primary")
            yield Static(_copy.VENUES_INTRO, classes="intro")
            with VerticalScroll():
                yield DataTable(id="ven-table", zebra_stripes=True)
                yield Static("", id="ven-chart", classes="chart")

    def _on_run_venues(self) -> None:
        # Reads the same exported venues.json the React app + 6_Venues.py read:
        # {venue -> {innings_totals, phase_run_rates, chase_vs_set}}. Mirrors
        # 6_Venues.py's per-view derivations.
        table = self.query_one("#ven-table", DataTable)
        venue_val = self.query_one("#ven-name", Select).value
        venue = "" if venue_val is Select.BLANK else str(venue_val)
        collection = self.query_one("#ven-collection", Select).value
        view = self.query_one("#ven-view", Select).value
        path = SITE_DATA / collection / "venues.json"
        if not path.exists():
            _fill_datatable(
                table,
                [{"error": f"missing {path.name}", "fix": "run scripts/export_site.py"}],
            )
            return
        data = json.loads(path.read_text())
        selected = data.get(venue)
        if not selected:
            sample = ", ".join(sorted(data.keys())[:6])
            _fill_datatable(
                table,
                [{"error": f"no venue `{venue}`", "try": f"e.g. {sample}"}],
            )
            return

        rows: list[dict] = []
        if view == "innings":
            # innings_idx <= 1 AND innings_count >= 3, ordered by innings_idx.
            totals = [
                r
                for r in (selected.get("innings_totals") or [])
                if (_num(r.get("innings_idx")) or 0) <= 1
                and (_num(r.get("innings_count")) or 0) >= 3
            ]
            totals.sort(key=lambda r: _num(r.get("innings_idx")) or 0)
            rows = [
                {
                    "innings": "Batting first"
                    if (_num(r.get("innings_idx")) or 0) == 0
                    else "Chasing",
                    "sample": int(_num(r.get("innings_count")) or 0),
                    "avg_runs": round(_num(r.get("avg_runs")) or 0, 1),
                    "median": round(_num(r.get("median_runs")) or 0),
                    "avg_wkts": round(_num(r.get("avg_wickets")) or 0, 1),
                }
                for r in totals
            ]
        elif view == "phases":
            phase_rows = [
                r
                for r in (selected.get("phase_run_rates") or [])
                if str(r.get("phase")) in PHASE_ORDER
            ]
            phase_rows.sort(key=lambda r: PHASE_ORDER.index(str(r.get("phase"))))
            rows = [
                {
                    "phase": str(r.get("phase")).title(),
                    "rpo": round(_num(r.get("rpo")) or 0, 2),
                    "dot_pct": round(_num(r.get("dot_pct")) or 0, 1),
                    "boundary_pct": round(_num(r.get("boundary_pct")) or 0, 1),
                    "legal_balls": int(_num(r.get("legal_balls")) or 0),
                }
                for r in phase_rows
            ]
        else:  # chase vs set winrate
            chase = (selected.get("chase_vs_set") or [{}])[0]
            decided = _num(chase.get("decided_matches"))
            first_wins = _num(chase.get("first_innings_team_wins"))
            first_win_pct = (
                (first_wins / decided * 100) if (decided and first_wins is not None) else None
            )
            if first_win_pct is not None:
                rows = [
                    {
                        "outcome": "Bat first wins",
                        "pct": round(first_win_pct, 1),
                        "decided_matches": int(decided),
                    },
                    {
                        "outcome": "Chase wins",
                        "pct": round(100 - first_win_pct, 1),
                        "decided_matches": int(decided),
                    },
                ]
        _fill_datatable(
            table,
            rows or [{"info": f"no data for `{view}` at {venue}"}],
            max_cols=10,
        )

        # Phase bar chart — runs/over, dot %, boundary % across the 3 phases
        # (mirrors the web Venues grouped bar chart). Only for the phases view.
        chart = self.query_one("#ven-chart", Static)
        if view == "phases" and rows:
            phases = [r["phase"] for r in rows]
            series = [
                [r["rpo"] for r in rows],
                [r["dot_pct"] for r in rows],
                [r["boundary_pct"] for r in rows],
            ]
            try:
                chart.update(
                    _plotext_chart(
                        lambda plt: (
                            plt.multiple_bar(
                                phases, series, labels=["Runs/over", "Dot %", "Boundary %"]
                            ),
                            plt.title(f"{venue} — scoring by phase"),
                        )
                    )
                )
            except Exception as e:  # noqa: BLE001
                chart.update(f"(chart unavailable: {e})")
        else:
            chart.update("")

    # ===== Auction (Solve + Recommend in same tab — mirrors Streamlit) ====

    # ===== Profile ========================================================

    def _profile_panel(self) -> ComposeResult:
        with Vertical():
            yield _tabhead("PROFILE", "full per-player dossier")
            with ControlBar(title="Player"):
                yield Label("Player:")
                yield Input(value="V Kohli", id="profile-name")
                yield Label("Coll:")
                yield Select(
                    options=_collection_options(),
                    value="ipl",
                    id="profile-collection",
                    allow_blank=False,
                )
                yield Button("Build ▸", id="profile-run", variant="primary")
            yield AutoComplete(
                target="#profile-name", candidates=self._player_cands("#profile-collection")
            )
            yield Static(_copy.PROFILE_INTRO, classes="intro")
            with Panel(title="Dossier"):
                yield RichLog(id="profile-log", highlight=False, markup=True, wrap=True)

    def _on_run_profile(self) -> None:
        # Reads the same exported profiles/<cid>.json the React app + 8_Player_
        # Profile.py read. Resolve name -> cricsheet_id via players.json, then
        # print identity / taxonomy / bayes / career / metrics / style-twins /
        # dismissal-fingerprint.
        log = self.query_one("#profile-log", RichLog)
        log.clear()
        name = _name_from_label(self.query_one("#profile-name", Input).value)
        collection = self.query_one("#profile-collection", Select).value
        cid = _resolve_cid(collection, name)
        if cid is None:
            log.write(f"[red]error:[/red] no exported player matching '{name}' in {collection}")
            return
        path = SITE_DATA / collection / "profiles" / f"{cid}.json"
        if not path.exists():
            log.write(f"[red]error:[/red] no exported profile {path.name} (run export_site.py)")
            return
        p = json.loads(path.read_text())

        wd = p.get("wikidata") or {}
        tax = p.get("taxonomy") or {}
        act = p.get("activity") or {}
        ids = p.get("ids") or {}
        bayes = p.get("bayes") or {}
        bat = bayes.get("bayes_batter") or {}
        bowl = bayes.get("bayes_bowler") or {}
        career = p.get("career") or {}
        metrics = p.get("metrics") or {}

        buf = Console(record=True, width=140, force_terminal=True, highlight=False)
        buf.print(
            f"[bold bright_cyan]{wd.get('label') or p.get('name') or name}[/bold bright_cyan]"
        )

        # identity chips — taxonomy + activity + value (mirror 8_Player_Profile.py)
        chips: list[str] = []
        if act:
            last = (act.get("last_match_date") or "")[:4]
            chips.append(
                "active" if act.get("active") else (f"retired · last {last}" if last else "retired")
            )
        if tax.get("primary_role"):
            chips.append(str(tax["primary_role"]).replace("_", "-"))
        if tax.get("batting_position"):
            chips.append(str(tax["batting_position"]))
        if tax.get("country"):
            chips.append(str(tax["country"]))
        if _num(bat.get("value")) is not None:
            chips.append(f"batting value {_num(bat.get('value')):.3f}")
        if _num(bowl.get("value")) is not None and (_num(bowl.get("balls")) or 0) > 60:
            chips.append(f"bowling value {_num(bowl.get('value')):.3f}")
        chips.append(f"id {cid}")
        buf.print("[dim]" + " · ".join(chips) + "[/dim]")

        dob = wd.get("dob")
        if dob:
            age = _render._compute_age(dob)
            buf.print(f"[dim]Born {dob[:10]}" + (f" · {age} yrs" if age else "") + "[/dim]")
            if wd.get("image_url"):
                buf.print(f"  [dim]Photo:[/dim] {wd['image_url']}")
            social: list[str] = []
            if wd.get("twitter"):
                social.append(f"𝕏 @{wd['twitter']}")
            if wd.get("instagram"):
                social.append(f"Instagram @{wd['instagram']}")
            if ids.get("key_cricinfo"):
                social.append(f"ESPN({ids['key_cricinfo']})")
            if wd.get("wikidata_qid"):
                social.append(f"Wikidata({wd['wikidata_qid']})")
            if social:
                buf.print(f"  [dim]Socials:[/dim] {' · '.join(social)}")

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

        buf.print("\n[bold]Novel metrics[/bold]")
        for slug, hint_txt in _copy.METRIC_HINTS.items():
            payload = metrics.get(slug)
            if payload is None:
                continue
            value = _summarise_metric(payload)
            buf.print(
                f"  [cyan]{slug.replace('_', ' ').title()}:[/cyan] [bold]{value}[/bold]  "
                f"[dim italic]{hint_txt}[/dim italic]"
            )

        buf.print("\n[bold]Bayesian scout-rating[/bold]")
        buf.print(f"  {_render.bayes_sentence(bayes, 'batter', 'Batter skill')}")
        buf.print(f"  {_render.bayes_sentence(bayes, 'bowler', 'Bowler skill')}")
        buf.print(f"  [dim italic]{_copy.BAYES_SCALE}[/dim italic]")

        # dismissal fingerprint — how they get out / take wickets.
        fp = p.get("dismissal_fingerprint") or {}
        for fp_role, fp_title in (("batter", "As batter"), ("bowler", "As bowler")):
            d = fp.get(fp_role)
            if d and d.get("rows"):
                buf.print(
                    f"\n[bold]Dismissal fingerprint · {fp_title}[/bold] ({d.get('total', 0)})"
                )
                for r in d["rows"][:6]:
                    pct = _num(r.get("pct")) or 0
                    buf.print(
                        f"  • {str(r.get('kind', '')).capitalize():<18} "
                        f"[cyan]{_pct_bar(pct)}[/cyan] {pct:5.1f}% ({r.get('count')})"
                    )
                if d.get("read"):
                    buf.print(f"  [dim italic]“{d['read']}”[/dim italic]")

        for label, twins in (
            ("Style twins (batter)", p.get("style_twins_batter")),
            ("Style twins (bowler)", p.get("style_twins_bowler")),
        ):
            if twins:
                buf.print(f"\n[bold]{label}[/bold]")
                for t in twins[:6]:
                    dist = _num(t.get("distance"))
                    sim = max(0.0, 1 - dist) * 100 if dist is not None else None
                    sim_s = f"{sim:.1f}% alike" if sim is not None else "—"
                    buf.print(f"  • {str(t.get('name')):<28}  {sim_s}")

        # Graph cohort — players who faced the same bowlers / shared a side
        # (reads cohorts/<cid>.json, same as the web Player Profile).
        try:
            co_faced = (cf.load_cohorts(collection, cid) or {}).get("co_faced") or []
        except FileNotFoundError:
            co_faced = []
        if co_faced:
            buf.print("\n[bold]Graph cohort[/bold] [dim](faced the same bowlers)[/dim]")

            # The shared-count field is role-dependent: batters carry
            # `shared_bowlers`, bowlers carry `shared_batters`.
            def _shared(r: dict) -> int:
                return int(r.get("shared_bowlers") or r.get("shared_batters") or 0)

            top = max((_shared(r) for r in co_faced[:10]), default=0) or 1
            for r in co_faced[:10]:
                s = _shared(r)
                buf.print(
                    f"  • {str(r.get('name')):<28} [cyan]{_pct_bar(s / top * 100, 16)}[/cyan]"
                    f"  {s} shared"
                )

        for line in buf.export_text(clear=False, styles=False).splitlines():
            log.write(line)

    # ===== Auction Simulator ==============================================

    def _auction_sim_panel(self) -> ComposeResult:
        from cricdex.auction.real_pool import (
            IPL_TEAMS_DEFAULT,
            PERSONALITY_IDS,
            load_team_overrides,
        )

        # Persistent state — survives Run clicks AND recompose (theme switch).
        if not hasattr(self, "_team_personalities"):
            self._team_personalities = dict(load_team_overrides() or IPL_TEAMS_DEFAULT)
        if not hasattr(self, "_drafted"):
            self._drafted = set()  # cids drafted from the Scout tab
        if not hasattr(self, "_retentions"):
            self._retentions = None  # dict[team, [cid]] — seeded lazily per mode
            self._ret_mode = None
        team_opts = [(t, t) for t, _ in IPL_TEAMS_DEFAULT]
        pers_opts = [(p, p) for p in PERSONALITY_IDS]

        with VerticalScroll():
            yield _tabhead("AUCTION", "real-rules IPL Monte-Carlo — retain → bid")
            yield Static(_copy.AUCTION_SIMULATE_INTRO, classes="intro")
            with ControlBar(title="Auction"):
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
                yield LoadingIndicator(id="sim-spinner", classes="spinner")
            with ControlBar(title="Personalities"):
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
                yield Button("Reset", id="sim-reset", variant="error")
            yield Static(self._sim_team_map_line(), id="sim-team-map", classes="intro")
            # Retentions editor — view + add/drop per team (mirrors web/Streamlit).
            with ControlBar(title="Retentions"):
                yield Label("Team:")
                yield Select(options=team_opts, value="CSK", id="sim-ret-team", allow_blank=False)
                yield Label("Player:")
                yield Input(placeholder="add a player…", id="sim-ret-player", classes="wide")
                yield Button("Add", id="sim-ret-add", variant="success")
                yield Button("Drop", id="sim-ret-drop", variant="warning")
                yield Button("Reset", id="sim-ret-reset", variant="error")
            yield AutoComplete(target="#sim-ret-player", candidates=_auction_pool_candidates("ipl"))
            yield Static("", id="sim-ret-map", classes="intro")
            with Panel(title="Squads"):
                yield DataTable(id="sim-table", zebra_stripes=True)
            with Panel(title="Marquee — who lands the stars"):
                yield DataTable(id="sim-marquee", zebra_stripes=True)
            with ControlBar(title="Representative squad"):
                yield Label("Team:")
                yield Select(options=team_opts, value="CSK", id="sim-squad-team", allow_blank=False)
            with Panel(title="Squad"):
                yield RichLog(id="sim-squad", highlight=False, markup=True, wrap=True)
            with ControlBar(title="Find player"):
                yield Label("Find player:")
                yield Input(placeholder="name… (after a run)", id="sim-find", classes="wide")
                yield Button("Find ▸", id="sim-find-run", variant="success")
            yield AutoComplete(target="#sim-find", candidates=_auction_pool_candidates("ipl"))
            with Panel(title="Player search"):
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

    # ---- auction data + retentions ---------------------------------------

    def _auction_data(self) -> dict:
        """Cached priced pool + lookup maps (loaded once)."""
        if getattr(self, "_auction_cache", None) is None:
            from cricdex.web_parity import build_pool, load_auction_pool, load_retentions

            pool = build_pool(load_auction_pool("ipl"))
            ret = load_retentions("ipl")
            self._auction_cache = {
                "pool": pool,
                "by_cid": {p["cricsheet_id"]: p for p in pool},
                "name_to_cid": {p["name"]: p["cricsheet_id"] for p in pool},
                "mega_ids": {
                    t: [r["cricsheet_id"] for r in rows] for t, rows in ret["mega"].items()
                },
                "real_prices": {
                    r["cricsheet_id"]: r["price"] for rows in ret["mega"].values() for r in rows
                },
            }
        return self._auction_cache

    def _teams_cfg(self) -> list[dict]:
        from cricdex.auction.real_pool import IPL_TEAMS_DEFAULT

        return [
            {"team": t, "personality": self._team_personalities.get(t, p)}
            for t, p in IPL_TEAMS_DEFAULT
        ]

    def _ensure_retentions(self, mode: str) -> dict:
        """Seed editable retentions from the mode default (+ any Scout drafts)
        once, reseeding when the Mega/Mini mode changes."""
        from cricdex.auction.real_pool import IPL_TEAMS_DEFAULT
        from cricdex.web_parity import default_retentions

        if self._retentions is None or self._ret_mode != mode:
            d = self._auction_data()
            base = default_retentions(d["pool"], self._teams_cfg(), mode, d["mega_ids"])
            if self._drafted:
                t0 = IPL_TEAMS_DEFAULT[0][0]
                extra = [c for c in self._drafted if c in d["by_cid"]]
                base[t0] = list(dict.fromkeys(base.get(t0, []) + extra))
            self._retentions = base
            self._ret_mode = mode
        return self._retentions

    def _ret_map_line(self, team: str) -> str:
        d = self._auction_data()
        rets = (self._retentions or {}).get(team, [])
        names = ", ".join(f"[bold]{d['by_cid'].get(c, {}).get('name', c)}[/bold]" for c in rets)
        return f"{team} retentions ({len(rets)}): {names or '[dim](none)[/dim]'}"

    def _refresh_ret_map(self) -> None:
        try:
            mode = self.query_one("#sim-mode", Select).value or "mega"
            self._ensure_retentions(mode)
            team = self.query_one("#sim-ret-team", Select).value
            self.query_one("#sim-ret-map", Static).update(self._ret_map_line(team))
        except Exception as e:  # noqa: BLE001
            self.query_one("#sim-ret-map", Static).update(f"[red]{e}[/red]")

    def _ret_player_cid(self) -> str | None:
        name = _name_from_label(self.query_one("#sim-ret-player", Input).value)
        return self._auction_data()["name_to_cid"].get(name)

    def _on_ret_add(self) -> None:
        rets = self._ensure_retentions(self.query_one("#sim-mode", Select).value or "mega")
        cid = self._ret_player_cid()
        if not cid:
            self.notify("not in the auction pool — pick from the dropdown", severity="warning")
            return
        team = self.query_one("#sim-ret-team", Select).value
        if cid not in rets.setdefault(team, []):
            rets[team].append(cid)
        self.query_one("#sim-ret-player", Input).value = ""
        self._refresh_ret_map()

    def _on_ret_drop(self) -> None:
        rets = self._ensure_retentions(self.query_one("#sim-mode", Select).value or "mega")
        cid = self._ret_player_cid()
        team = self.query_one("#sim-ret-team", Select).value
        if cid and cid in rets.get(team, []):
            rets[team].remove(cid)
        self.query_one("#sim-ret-player", Input).value = ""
        self._refresh_ret_map()

    def _on_ret_reset(self) -> None:
        self._retentions = None
        self._ret_mode = None
        self._refresh_ret_map()
        self.notify("retentions reset to defaults", timeout=1.5)

    def _render_squad(self, team: str) -> None:
        log = self.query_one("#sim-squad", RichLog)
        log.clear()
        res = getattr(self, "_sim_res", None)
        if not res:
            log.write("[dim]run a simulation to see a representative squad.[/dim]")
            return
        s = next((x for x in res["sample_draft"] if x["team"] == team), None)
        if not s:
            log.write(f"[dim]no squad sampled for {team}.[/dim]")
            return

        def _line(p: dict) -> str:
            plane = " ✈" if p.get("is_overseas") else ""
            return f"  • {p['name']} [dim]{p['role'].replace('_', '-')}{plane}[/dim]"

        log.write(f"[bold]Retained ({len(s['retained'])})[/bold]")
        for p in s["retained"]:
            log.write(_line(p))
        if not s["retained"]:
            log.write("  [dim]none[/dim]")
        log.write(f"\n[bold]Bought ({len(s['bought'])})[/bold]")
        for p in s["bought"]:
            log.write(_line(p))
        if not s["bought"]:
            log.write("  [dim]no buys in this sample[/dim]")
        log.write(
            f"\n[dim]{len(s['retained']) + len(s['bought'])} total · "
            f"{s['overseas']} overseas · spend {s['spent']:.1f} cr[/dim]"
        )

    def _on_run_auction_sim(self) -> None:
        # Main thread: validate, show the spinner, hand the heavy Monte-Carlo to
        # a thread worker so the UI stays responsive (no freeze on 300 trials).
        table = self.query_one("#sim-table", DataTable)
        mode = self.query_one("#sim-mode", Select).value or "mega"
        try:
            n_sims = int(self.query_one("#sim-n", Input).value or "300")
            purse = float(self.query_one("#sim-purse", Input).value or "120")
        except ValueError:
            _fill_datatable(table, [{"error": "Sims and Purse must be numeric"}])
            self.notify("Sims and Purse must be numeric", severity="error")
            return
        self.query_one("#sim-spinner", LoadingIndicator).add_class("run")
        _fill_datatable(table, [{"info": f"simulating {n_sims} auctions…"}])
        self._auction_worker(mode, n_sims, purse)

    @work(thread=True, exclusive=True, group="auction")
    def _auction_worker(self, mode: str, n_sims: int, purse: float) -> None:
        # Canonical, web-identical auction (cricdex.web_parity): same exported
        # pool + real 2025 retentions + seeded Monte-Carlo as the live site.
        try:
            from cricdex.web_parity import simulate_auction

            d = self._auction_data()
            teams = self._teams_cfg()
            retentions = self._ensure_retentions(mode)  # editable per-team retentions
            res = simulate_auction(
                d["pool"],
                teams,
                {
                    "purse": purse,
                    "squad_size": 25,
                    "overseas_cap": 8,
                    "trials": n_sims,
                    "mode": mode,
                    "retentions": retentions,
                    "real_prices": d["real_prices"],
                },
            )
        except Exception as e:  # noqa: BLE001
            self.call_from_thread(self._auction_done, None, str(e))
            return
        self.call_from_thread(self._auction_done, res, None)

    def _auction_done(self, res: dict | None, err: str | None) -> None:
        self.query_one("#sim-spinner", LoadingIndicator).remove_class("run")
        table = self.query_one("#sim-table", DataTable)
        if err is not None or res is None:
            _fill_datatable(table, [{"error": err or "auction failed"}])
            self.notify(err or "auction failed", severity="error")
            return
        self._sim_res = res
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
        # Marquee — who lands the stars (unsold when no winners).
        _fill_datatable(
            self.query_one("#sim-marquee", DataTable),
            [
                {
                    "player": m["player"]["name"],
                    "role": m["player"]["role"].replace("_", "-"),
                    "value": round(m["player"]["projected_value"], 1),
                    "landing": ", ".join(f"{w['team']} {w['pct']:.0f}%" for w in m["winners"])
                    or "unsold",
                }
                for m in res["marquee"]
            ],
            max_cols=4,
        )
        # Representative squad for the currently-selected team.
        self._render_squad(self.query_one("#sim-squad-team", Select).value)
        self.notify("auction complete", timeout=1.5)

    def _on_find_sim_player(self) -> None:
        # Search the last run's per-player outcomes: retained / sold / unsold.
        out = self.query_one("#sim-find-table", DataTable)
        outcomes = getattr(self, "_sim_outcomes", None)
        if not outcomes:
            _fill_datatable(out, [{"info": "run a simulation first"}])
            return
        needle = _name_from_label(self.query_one("#sim-find", Input).value).lower()
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
            yield _tabhead("SCOUT", "cross-competition look-alikes")
            with ControlBar(title="Pick"):
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
            yield AutoComplete(target="#twins-name", candidates=_player_candidates())
            yield Static("", id="twins-meta", classes="intro")
            with Panel(title="Look-alikes"):
                yield DataTable(id="twins-table", zebra_stripes=True)
            # Draft a look-alike (SMAT/BBL/SA20/CPL/Blast) into the Auction room
            # as a retention — populated after a scout on a draftable tier.
            with ControlBar(title="Draft to Auction"):
                yield Label("Prospect:")
                yield Select(options=[], id="twins-draft-pick", classes="wide", allow_blank=True)
                yield Button("Draft ▸", id="twins-draft", variant="success")

    def _on_run_twins(self) -> None:
        # Canonical, web-identical scout (cricdex.web_parity): same exported
        # scout_index + look-alike logic + tier-discounted pricing as the site.
        table = self.query_one("#twins-table", DataTable)
        meta = self.query_one("#twins-meta", Static)
        name = _name_from_label(self.query_one("#twins-name", Input).value)
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
        draftables: list[tuple[str, str]] = []  # (label, cid) for the draft picker
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
            if r.get("cricsheet_id"):
                draftables.append((f"{r['name']} ({tier.upper()})", r["cricsheet_id"]))
        tier_label = {b: a for a, b in SCOUT_TIER_OPTIONS}[tier]
        meta.update(
            f"[bold]{sel['name']}[/bold] · {role} · standing {sel['z']:.2f} · "
            f"≈ {sel_price:.1f} cr   →   {tier_label}"
        )
        _fill_datatable(table, rows or [{"info": "no close match of this archetype"}])
        # Draftable only for the non-IPL tiers (IPL peers can't be "drafted").
        self._draft_names = {cid: lbl for lbl, cid in draftables}
        self.query_one("#twins-draft-pick", Select).set_options(draftables if tier != "ipl" else [])

    def _on_draft_twin(self) -> None:
        # Draft the picked prospect into the Auction room as a retention
        # (mirrors the web Scout "Draft" button + Streamlit session-state handoff).
        cid = self.query_one("#twins-draft-pick", Select).value
        if cid is Select.BLANK or not cid:
            self.notify("scout a SMAT/BBL/… tier, then pick a prospect", severity="warning")
            return
        name = getattr(self, "_draft_names", {}).get(cid, cid)
        # Only players in the priced auction pool can be drafted (the rest are
        # too few balls / a non-IPL nation) — mirrors the web's draft guard.
        if cid not in self._auction_data()["by_cid"]:
            self.notify(
                f"{name} isn't in the priced auction pool (too few balls, or a "
                "non-IPL nation) — can't draft.",
                severity="warning",
                timeout=4,
            )
            return
        if not hasattr(self, "_drafted"):
            self._drafted = set()
        self._drafted.add(cid)
        self._retentions = None  # reseed so the auction picks the draft up
        self.notify(f"drafted {name} → Auction retentions", timeout=2.5)

    # ===== Update — refresh data then re-export the JSON ==================

    def _update_panel(self) -> ComposeResult:
        with Vertical():
            yield _tabhead("UPDATE", "re-ingest → recompute → re-export JSON")
            with ControlBar(title="Target"):
                yield Label("Collection:")
                yield Select(
                    options=_collection_options(),
                    value="ipl",
                    id="upd-collection",
                    allow_blank=False,
                )
                yield Label("Force:")
                yield Select(
                    options=[("no", "no"), ("yes", "yes")],
                    value="no",
                    id="upd-force",
                    allow_blank=False,
                )
            with ControlBar(title="Run"):
                yield Button("Cricsheet", id="upd-cricsheet")
                yield Button("Ratings", id="upd-ratings")
                yield Button("Metrics", id="upd-metrics")
                yield Button("Wikidata", id="upd-wikidata")
                yield Button("Re-export JSON", id="upd-export", variant="success")
                yield Button("Full refresh", id="upd-all", variant="primary")
            yield Static(
                "Re-ingest → recompute ratings + metrics → re-export the JSON every "
                "tab reads (the same pipeline the web's nightly Action runs).",
                classes="intro",
            )
            with Panel(title="Log"):
                yield RichLog(id="upd-log", highlight=False, markup=True, wrap=True)

    def _on_update(self, button_id: str) -> None:
        from cricdex.config import ROOT

        log = self.query_one("#upd-log", RichLog)
        collection = str(self.query_one("#upd-collection", Select).value or "ipl")
        force = self.query_one("#upd-force", Select).value == "yes"

        def _run_slice(slice_: str) -> None:
            from cricdex.cli.data_cmd import run_ingest

            log.write(f"[cyan]ingest {slice_} ({collection}, force={force}) …[/cyan]")
            try:
                msg = run_ingest(slice_, collection=collection, force=force)
                log.write(f"[green]{slice_} ✓[/green] {msg}")
            except Exception as e:  # noqa: BLE001
                log.write(f"[red]{slice_} failed:[/red] {e}")

        def _run_export() -> None:
            log.write(f"[cyan]export_site.py -c {collection} …[/cyan]")
            try:
                proc = subprocess.run(
                    [sys.executable, "scripts/export_site.py", "-c", collection],
                    cwd=ROOT,
                    capture_output=True,
                    text=True,
                )
                if proc.returncode == 0:
                    log.write("[green]re-exported JSON ✓[/green] — tabs now read the new data.")
                else:
                    log.write(f"[red]export failed:[/red] {proc.stderr[-800:]}")
            except Exception as e:  # noqa: BLE001
                log.write(f"[red]export failed:[/red] {e}")

        slice_map = {
            "upd-cricsheet": "cricsheet",
            "upd-ratings": "ratings",
            "upd-metrics": "metrics",
            "upd-wikidata": "wikidata",
        }
        if button_id in slice_map:
            _run_slice(slice_map[button_id])
        elif button_id == "upd-export":
            _run_export()
        elif button_id == "upd-all":
            for s in ("cricsheet", "ratings", "metrics"):
                _run_slice(s)
            _run_export()
            log.write("[bold green]Full refresh complete.[/bold green] Every tab reads fresh JSON.")

    # ===== event dispatch ================================================

    def on_tabbed_content_tab_activated(self, event: TabbedContent.TabActivated) -> None:
        # Seed the retentions map the first time the Auction tab is opened, so
        # the user can SEE the current retentions without running anything.
        if self.query_one(TabbedContent).active == "tab-auction-sim":
            self._refresh_ret_map()

    def on_select_changed(self, event: Select.Changed) -> None:
        # Sim tab — when the team Select changes, surface that team's
        # currently-chosen personality in the personality Select so the
        # user sees what's set before they edit it.
        sid = getattr(event.select, "id", None)
        if sid == "sim-team":
            new_team = event.value
            try:
                pers_select = self.query_one("#sim-pers", Select)
            except Exception:  # noqa: BLE001
                return
            pers_select.value = self._team_personalities.get(new_team, "Balanced")
        elif sid == "sim-ret-team":
            self._refresh_ret_map()
        elif sid == "sim-squad-team" and event.value is not Select.BLANK:
            self._render_squad(event.value)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        handlers = {
            "metric-run": self._on_run_leaderboard,
            "records-run": self._on_run_records,
            "cmp-run": self._on_run_compare,
            "h2h-run": self._on_run_h2h,
            "ven-run": self._on_run_venues,
            "profile-run": self._on_run_profile,
            "sim-run": self._on_run_auction_sim,
            "sim-find-run": self._on_find_sim_player,
            "sim-apply": self._on_apply_sim_team,
            "sim-reset": self._on_reset_sim_teams,
            "sim-ret-add": self._on_ret_add,
            "sim-ret-drop": self._on_ret_drop,
            "sim-ret-reset": self._on_ret_reset,
            "twins-run": self._on_run_twins,
            "twins-draft": self._on_draft_twin,
        }
        if event.button.id in handlers:
            handlers[event.button.id]()
        elif event.button.id and event.button.id.startswith("upd-"):
            self._on_update(event.button.id)


# ---- helpers ----------------------------------------------------------------


def _pct_bar(pct: float, width: int = 20) -> str:
    """A solid block bar for a 0–100 percentage — the text-mode stand-in for
    the web's dismissal / skill bars."""
    pct = max(0.0, min(100.0, pct))
    filled = round(pct / 100 * width)
    return "█" * filled + "░" * (width - filled)


def _num(v: Any) -> float | None:
    """Coerce a value to float, treating ''/None/NaN as missing."""
    if v is None or v == "":
        return None
    try:
        n = float(v)
    except (TypeError, ValueError):
        return None
    return n if n == n else None  # drop NaN


def _dig(profile: dict, *path: str) -> Any:
    """Walk a nested dict path; return the numeric leaf or None (mirror _g+_num)."""
    cur: Any = profile
    for p in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(p)
    return _num(cur)


def _fmt_num(v: float | None, digits: int) -> str:
    """Format like 5_Compare.py / 8_Player_Profile.py: '—', ints, thousands, dp."""
    if v is None:
        return "—"
    if abs(v) >= 1000:
        return f"{v:,.0f}"
    if float(v).is_integer():
        return str(int(v))
    return f"{v:.{digits}f}"


def _strike_rate(profile: dict) -> float | None:
    r = _dig(profile, "career", "career_runs")
    b = _dig(profile, "career", "career_balls_faced")
    return (r / b * 100) if (r is not None and b) else None


def _resolve_cid(collection: str, name: str) -> str | None:
    """Resolve a display name -> cricsheet_id via the exported players.json.
    Exact match first, then case-insensitive substring (mirror the TUI's twins
    lookup)."""
    path = SITE_DATA / collection / "players.json"
    if not name or not path.exists():
        return None
    players = json.loads(path.read_text())
    by_name = {
        p["name"]: p["cricsheet_id"] for p in players if p.get("name") and p.get("cricsheet_id")
    }
    if name in by_name:
        return by_name[name]
    needle = name.lower()
    return next((cid for n, cid in by_name.items() if needle in n.lower()), None)


def _load_profile(collection: str, cid: str | None) -> dict | None:
    if not cid:
        return None
    path = SITE_DATA / collection / "profiles" / f"{cid}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text())


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
