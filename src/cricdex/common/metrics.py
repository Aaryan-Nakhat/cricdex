"""The 10 novel metrics — one catalog, shared by every surface.

A Python mirror of `site/src/lib/metrics.ts`: the same slugs, display names,
name column, sort column, direction, per-column layout, and the plain-English
`what` / `how` explainer copy. Drives the Streamlit + TUI leaderboard switcher,
columns, sort, and info text so they read identically to the web app.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Column:
    key: str
    label: str
    digits: int | None = None  # None = string column
    primary: bool = False  # headline / sort column
    bar: bool = False  # render an inline magnitude bar


@dataclass(frozen=True)
class MetricDef:
    slug: str
    name: str
    one_liner: str
    what: str  # longer explainer for the page header
    how: str  # step-by-step "how it's calculated"
    name_col: str  # column holding the player's name
    higher_is_better: bool
    columns: list[Column]

    @property
    def sort_col(self) -> str:
        col = next((c.key for c in self.columns if c.primary), None)
        if col is None:
            raise ValueError(f"metric {self.slug!r} has no primary column")
        return col


METRICS: list[MetricDef] = [
    MetricDef(
        slug="ngi",
        name="Net Game Impact",
        one_liner="How much a player moves their team's chance of winning, per match — batting + bowling.",
        what=(
            "NGI scores every ball by how much it changed the batting side's chance of winning, "
            "credits that to the batter (and the opposite to the bowler), and averages it per "
            "match — so a 30* that wins a tight chase counts for more than a hundred in a lost "
            "cause."
        ),
        how=(
            "A win-probability model (gradient-boosted trees, calibrated) trained on every T20 "
            "ball in the league reads the state before each delivery: innings, balls and wickets "
            "left, score, target and required rate, and the run rate against the ground's "
            "average. The change in win chance from before to after the ball is that ball's "
            "value: + to the batter, − to the bowler. NGI total sums it over a career; NGI per "
            "match divides by matches played."
        ),
        name_col="name",
        higher_is_better=True,
        columns=[
            Column("name", "Player"),
            Column("ngi_per_match", "NGI / match", 3, primary=True, bar=True),
            Column("ngi_total", "NGI total", 1),
            Column("ngi_batting", "Batting", 1),
            Column("ngi_bowling", "Bowling", 1),
            Column("matches", "Matches", 0),
        ],
    ),
    MetricDef(
        slug="pressure_runs",
        name="Pressure Runs",
        one_liner="Strike rate when the required rate is climbing in a chase.",
        what=(
            "Isolates balls faced under genuine chase pressure (required rate above par) and "
            "reports how fast a batter scores in exactly those moments — separating flat-track "
            "bullies from players who lift when it's tight."
        ),
        how=(
            "Look only at chasing balls. A ball is 'under pressure' when the required rate is "
            "above 1.5× the usual required rate at that ground, in that phase and format. Over "
            "just those balls, Pressure SR = (runs / balls) × 100 (wides aren't balls faced). "
            "% balls is how often this player was actually put under that pressure."
        ),
        name_col="batter",
        higher_is_better=True,
        columns=[
            Column("batter", "Batter"),
            Column("pressure_sr_per_100_balls", "Pressure SR", 1, primary=True, bar=True),
            Column("pressure_runs", "Pressure runs", 0),
            Column("pressure_balls", "Pressure balls", 0),
            Column("pct_balls_under_pressure", "% balls", 1),
        ],
    ),
    MetricDef(
        slug="intent_curve",
        name="Intent Curve",
        one_liner="Strike rate from ball one — who comes out firing, with the full innings shape.",
        what=(
            "Ranks batters by how hard they go in their first 10 balls — pure early intent, before "
            "they're set — and shows the full shape of their innings (strike rate across "
            "ball-faced buckets) as an inline sparkline. Separates immediate-aggressors from "
            "slow-starters who only launch once they're in."
        ),
        how=(
            "Bucket every ball a batter faced by how deep into their innings it was (0–5, 6–10, "
            "11–20, 21–30, 31–50, 51+). Within each bucket, SR = runs ÷ balls × 100 — that 6-point "
            "sequence is the curve (the sparkline). The ranking number is Early SR: their combined "
            "SR over balls 1–10, weighted by balls faced."
        ),
        name_col="batter",
        higher_is_better=True,
        columns=[
            Column("batter", "Batter"),
            Column("early_sr", "Early SR (balls 1–10)", 1, primary=True, bar=True),
            Column("curve", "Innings curve (0–5 → 51+)"),
            Column("peak_sr", "Peak SR", 1),
            Column("balls", "Balls", 0),
        ],
    ),
    MetricDef(
        slug="dot_ball_recovery",
        name="Dot-Ball Recovery",
        one_liner="Runs scored in the 6 balls after eating a dot.",
        what=(
            "Measures how a batter responds to a dot ball: runs accumulated over the next six "
            "deliveries. High scorers refuse to let pressure compound; low scorers let dots "
            "snowball into more dots."
        ),
        how=(
            "Find every dot ball the batter faced and the deliveries they faced right after "
            "it. Metric = runs per six balls over those following deliveries — how quickly "
            "they score again once a dot has landed."
        ),
        name_col="batter",
        higher_is_better=True,
        columns=[
            Column("batter", "Batter"),
            Column("runs_per_6_after_dot", "Runs / 6 after dot", 2, primary=True, bar=True),
            Column("dots_faced", "Dots faced", 0),
            Column("runs_in_following", "Runs after", 0),
        ],
    ),
    MetricDef(
        slug="counter_attack",
        name="Counter-Attack",
        one_liner="Strike rate immediately after a partner is dismissed.",
        what=(
            "Captures the player who counter-punches when a wicket has just fallen — strike rate on "
            "balls faced right after losing a partner, when most batters retreat into their shell."
        ),
        how=(
            "Take the 12 balls after each partner wicket and keep the ones faced by the batter "
            "who was already at the crease (not the one out, not the new arrival); a ball "
            "after two quick wickets counts once. Counter SR = (runs / balls) × 100 over those "
            "balls — high means they accelerate through a wicket, not shut down."
        ),
        name_col="batter",
        higher_is_better=True,
        columns=[
            Column("batter", "Batter"),
            Column("counter_attack_sr", "Counter SR", 1, primary=True, bar=True),
            Column("runs_after_partner_wkt", "Runs", 0),
            Column("balls_after_partner_wkt", "Balls", 0),
        ],
    ),
    MetricDef(
        slug="boundary_dependency",
        name="Boundary Dependency",
        one_liner="Share of runs that come from fours and sixes.",
        what=(
            "The fraction of a batter's runs scored in boundaries. High dependency flags a player "
            "who can go quiet when boundaries dry up; low dependency means they rotate strike and "
            "keep the score ticking without the rope."
        ),
        how=(
            "Boundary runs = (fours × 4) + (sixes × 6). Boundary % = boundary runs ÷ total runs × "
            "100. Lower is better here — it means more of the score came from running, not just "
            "the rope."
        ),
        name_col="batter",
        higher_is_better=False,
        columns=[
            Column("batter", "Batter"),
            Column("bdr_pct", "Boundary %", 1, primary=True, bar=True),
            Column("boundary_runs", "Boundary runs", 0),
            Column("fours", "4s", 0),
            Column("sixes", "6s", 0),
            Column("total_runs", "Total runs", 0),
        ],
    ),
    MetricDef(
        slug="pressure_conversion",
        name="Pressure Conversion",
        one_liner="How often a bowler turns pressure balls into wickets.",
        what=(
            "After a bowler builds pressure with a run of dot balls, how often does the very next "
            "ball take a wicket? Separates the bowlers who finish the squeeze from those who let "
            "batters off the hook."
        ),
        how=(
            "A pressure ball is a dot that makes it 4 or more dots in a row from the same bowler "
            "within one over (any run, bye, wide or no-ball breaks the run). Conversion % = "
            "pressure balls where the next ball of that over is a wicket the bowler is credited with (run-outs don't count) ÷ "
            "pressure balls × 100. The last ball of an over has no next ball, so it isn't counted."
        ),
        name_col="bowler",
        higher_is_better=True,
        columns=[
            Column("bowler", "Bowler"),
            Column("wicket_rate_pct", "Conversion %", 1, primary=True, bar=True),
            Column("wickets_after_pressure", "Wickets", 0),
            Column("pressure_balls", "Pressure balls", 0),
        ],
    ),
    MetricDef(
        slug="wicket_quality",
        name="Wicket Quality",
        one_liner="Wickets weighted by the calibre of batter dismissed.",
        what=(
            "Not all wickets are equal. This weights each dismissal by the quality of the batter "
            "removed (their Bayesian rating), rewarding bowlers who take the big scalps over those "
            "who pad stats against tail-enders."
        ),
        how=(
            "For each wicket, look up the dismissed batter's Bayesian batting skill. Wicket "
            "quality = the average of those skills across the bowler's wickets, so removing "
            "top-order stars scores far higher than mopping up the tail."
        ),
        name_col="bowler",
        higher_is_better=True,
        columns=[
            Column("bowler", "Bowler"),
            Column("wicket_quality", "Wicket quality", 3, primary=True, bar=True),
            Column("wickets", "Wickets", 0),
            Column("opponents_seen", "Opponents", 0),
        ],
    ),
    MetricDef(
        slug="crease_longevity",
        name="Crease Longevity",
        one_liner="Balls survived per dismissal vs the cohort average.",
        what=(
            "How long a batter typically lasts at the crease — balls faced per dismissal — indexed "
            "against the cohort. Above 1.0 means they stick around longer than peers; an anchor's "
            "signature."
        ),
        how=(
            "Balls per dismissal = total balls faced ÷ times out (run outs at either end "
            "count; retired hurt doesn't). Longevity index = that figure ÷ the cohort average. "
            "1.0 = exactly average survival; 1.3 = lasts 30% longer than peers per dismissal."
        ),
        name_col="batter",
        higher_is_better=True,
        columns=[
            Column("batter", "Batter"),
            Column("longevity_index", "Longevity index", 3, primary=True, bar=True),
            Column("avg_balls_per_dismissal", "Balls / dismissal", 1),
            Column("cohort_avg", "Cohort avg", 1),
            Column("innings_count", "Innings", 0),
        ],
    ),
    MetricDef(
        slug="slow_start_cost",
        name="Slow-Start Cost",
        one_liner="Strike-rate drop over the first 20 balls of an innings.",
        what=(
            "Quantifies how much a batter slows down while getting set (the first 20 balls of each "
            "innings) compared with their career strike rate. The hidden cost of a cautious start, "
            "whether batting first or chasing."
        ),
        how=(
            "Setting SR = strike rate over the first 20 balls a batter faces in each innings "
            "(wides aren't balls faced). Slow-start cost = career SR − setting SR. Positive = they "
            "start slower than they bat overall; lower (or negative) is better. Needs 200+ career "
            "balls and 50+ setting balls."
        ),
        name_col="batter",
        higher_is_better=False,
        columns=[
            Column("batter", "Batter"),
            Column("slow_start_cost", "Slow-start cost", 1, primary=True, bar=True),
            Column("career_sr", "Career SR", 1),
            Column("setting_sr", "Setting SR", 1),
            Column("setting_balls", "Setting balls", 0),
        ],
    ),
    MetricDef(
        slug="keeping",
        name="Wicketkeeping",
        one_liner="Dismissals behind the stumps — catches, stumpings, run-outs.",
        what=(
            "Counts every dismissal a wicket-keeper is credited with: catches taken, stumpings, and "
            "run-out involvements. It's a volume tally (longevity rewards it — use the min-matches "
            "filter), not a per-chance success rate, which ball-by-ball data can't see."
        ),
        how=(
            "From each dismissal's fielder list: caught → catch, stumped → stumping, run out → an "
            "involvement (every fielder named is credited). A player counts as a keeper if the "
            "taxonomy says so or they have any stumping. Dismissals = catches + stumpings + run-outs."
        ),
        name_col="fielder",
        higher_is_better=True,
        columns=[
            Column("fielder", "Keeper"),
            Column("dismissals", "Dismissals", 0, primary=True, bar=True),
            Column("catches", "Catches", 0),
            Column("stumpings", "Stumpings", 0),
            Column("runouts", "Run-outs", 0),
        ],
    ),
    MetricDef(
        slug="fielding",
        name="Fielding",
        one_liner="Outfield dismissals — catches and run-out involvements.",
        what=(
            "Counts an outfielder's dismissals: catches taken and run-out involvements. Fielding is "
            "the least-quantified discipline; this is the count broadcast scorecards bury. It's "
            "volume (use the min-matches filter), not diving range — that needs video."
        ),
        how=(
            "From each dismissal's fielder list: caught → catch, run out → an involvement (every "
            "fielder named is credited; caught-and-bowled is a bowling wicket, excluded). Keepers "
            "are split off to their own board. Dismissals = catches + run-outs."
        ),
        name_col="fielder",
        higher_is_better=True,
        columns=[
            Column("fielder", "Fielder"),
            Column("dismissals", "Dismissals", 0, primary=True, bar=True),
            Column("catches", "Catches", 0),
            Column("runouts", "Run-outs", 0),
        ],
    ),
]

METRIC_BY_SLUG: dict[str, MetricDef] = {m.slug: m for m in METRICS}

__all__ = ["METRIC_BY_SLUG", "METRICS", "Column", "MetricDef"]
