"""The 10 novel metrics + the two fielding boards — one catalog, shared by every surface.

A Python mirror of `site/src/lib/metrics.ts`: the same slugs, display names,
name column, sort column, direction, per-column layout, and the plain-English
`what` / `how` / `read` / `good` explainer copy (word for word; locked by
tests/test_metrics_copy_parity.py). Drives the Streamlit + TUI leaderboard switcher,
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
    fmt: str | None = None  # "pct": a 0–1 share shown as a signed percentage (0.097 -> +9.7%)


@dataclass(frozen=True)
class MetricDef:
    slug: str
    name: str
    one_liner: str
    what: str  # longer explainer for the page header
    how: str  # step-by-step "how it's calculated"
    read: str  # how to read the number, for a fan
    good: str  # what a good value looks like
    direction: str  # "higher" | "lower" | "descriptive" (a style, not a level)
    name_col: str  # column holding the player's name
    higher_is_better: bool  # sort direction: False = smallest first
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
        one_liner=(
            "How much a player adds to his team's chance of winning, per match — batting, bowling"
            " and fielding together."
        ),
        what=(
            "NGI scores every ball by how much it changed the batting side's chance of winning "
            "and credits it to whoever caused it — the batter for his runs, the bowler for runs, "
            "extras and wickets, the fielder for a catch or run out — then averages it per match,"
            " so a 30* that wins a tight chase counts for more than a hundred in a lost cause."
        ),
        how=(
            "A win-probability model (gradient-boosted trees with a smooth calibration) reads the"
            " state before each delivery: innings, balls and wickets left, score, target and "
            "required rate, the run rate against the ground's average and the league's recent "
            "scoring level. Every ball is scored by a model that never saw that match. The change"
            " in win chance is split: runs off the bat go to the striker (+) and the bowler (−); "
            "wides and no-balls to the bowler only; byes and leg-byes to nobody; a wicket debits "
            "the batter who is out (the non-striker in a run out at his end) and credits the "
            "bowler, with 20% of a catch or stumping to the fielder and all of a run out to the "
            "fielders. Win chance added per match = the career sum divided by matches in the "
            "playing XI, shown as a percentage. Wins added = the career sum itself: every 1.0 is "
            "one whole win's worth of win chance."
        ),
        read=(
            "Win chance added per match: +5% means that in a typical game he adds five percentage "
            "points to his team's chance of winning — a 50-50 game becomes 55-45 in his side's "
            "favour. 0% means the good and bad balls cancel out; below zero, he costs his side more "
            "than he adds. Wins added is a career total, like career runs: it keeps growing with "
            "every match he plays."
        ),
        good=(
            "In the IPL most regulars sit between −4% and +3% per match; +3% or more is top-10%, "
            "and +5% or more is elite. Compare wins added only between players with similar "
            "numbers of matches — a long career piles it up."
        ),
        direction="higher",
        name_col="name",
        higher_is_better=True,
        columns=[
            Column("name", "Player"),
            Column(
                "ngi_per_match", "Win chance added / match", 1, primary=True, bar=True, fmt="pct"
            ),
            Column("ngi_total", "Wins added (career)", 1),
            Column("ngi_batting", "…from batting", 1),
            Column("ngi_bowling", "…from bowling", 1),
            Column("ngi_fielding", "…from fielding", 1),
            Column("matches", "Matches", 0),
        ],
    ),
    MetricDef(
        slug="pressure_runs",
        name="Pressure Runs",
        one_liner="Strike rate when the required rate is climbing in a chase.",
        what=(
            "Isolates balls faced under genuine chase pressure (required rate above par) and reports "
            "how fast a batter scores in exactly those moments — separating flat-track bullies from "
            "players who lift when it's tight."
        ),
        how=(
            "Look only at chasing balls. A ball is 'under pressure' when the required rate is above "
            "1.5× the usual required rate at that ground, in that phase and format. Over just those "
            "balls, Pressure SR = (runs / balls) × 100 (wides aren't balls faced). % balls is how "
            "often this player was actually put under that pressure."
        ),
        read=(
            "A strike rate (runs per 100 balls), counting only the hard moments of a chase — when the"
            " asking rate has climbed well above normal for that ground. 180 means 18 runs for every "
            "10 of those balls."
        ),
        good=(
            "In the IPL the typical batter scores at about 145 under this pressure; 190 or more is "
            "top-10%. Check the pressure-balls column too — a big number from a handful of balls is "
            "less reliable."
        ),
        direction="higher",
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
            "they're set — and shows the full shape of their innings (strike rate across ball-faced "
            "buckets) as an inline sparkline. Separates immediate-aggressors from slow-starters who "
            "only launch once they're in."
        ),
        how=(
            "Bucket every ball a batter faced by how deep into their innings it was (0–5, 6–10, "
            "11–20, 21–30, 31–50, 51+). Within each bucket, SR = runs ÷ balls × 100 — that 6-point "
            "sequence is the curve (the sparkline). The ranking number is Early SR: their combined SR"
            " over balls 1–10, weighted by balls faced."
        ),
        read=(
            "Strike rate over a batter's first 10 balls, before he has settled: 130 means 13 runs off"
            " his first 10 balls. The little bars show his strike rate as the innings goes on — "
            "rising bars mean he builds up, flat high bars mean he attacks from ball one."
        ),
        good=(
            "In the IPL about 118 is typical and 135 or more is top-10% — a genuine early hitter. A "
            "low number isn't wrong for an anchor, but it puts pressure on the batter at the other "
            "end."
        ),
        direction="higher",
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
            "deliveries. High scorers refuse to let pressure compound; low scorers let dots snowball "
            "into more dots."
        ),
        how=(
            "Find every dot ball the batter faced and the deliveries they faced right after it. "
            "Metric = runs per six balls over those following deliveries — how quickly they score "
            "again once a dot has landed."
        ),
        read=(
            "After he plays out a dot ball, how many runs does he score over his next six balls? 9 "
            "means he answers a dot with a nine-run over; 6 means the dots tend to pile up."
        ),
        good=(
            "In the IPL about 7.8 is typical and 9.3 or more is top-10%. Below 6.5 suggests bowlers "
            "can tie him down."
        ),
        direction="higher",
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
            "Take the 12 balls after each partner wicket and keep the ones faced by the batter who "
            "was already at the crease (not the one out, not the new arrival); a ball after two quick"
            " wickets counts once. Counter SR = (runs / balls) × 100 over those balls — high means "
            "they accelerate through a wicket, not shut down."
        ),
        read=(
            "His strike rate on the balls just after his batting partner gets out — the moment most "
            "batters slow down. 150 means 15 runs for every 10 of those balls."
        ),
        good=(
            "In the IPL about 137 is typical and 164 or more is top-10% — he hits back instead of "
            "retreating."
        ),
        direction="higher",
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
            "The fraction of a batter's runs scored in boundaries. High dependency flags a player who"
            " can go quiet when boundaries dry up; low dependency means they rotate strike and keep "
            "the score ticking without the rope."
        ),
        how=(
            "Boundary runs = (fours × 4) + (sixes × 6). Boundary % = boundary runs ÷ total runs × "
            "100. It describes a style, not a level: the board lists the lowest first only so the "
            "strike-rotators are easy to find."
        ),
        read=(
            "What share of his runs come from fours and sixes: 70% means seven of every ten runs "
            "crossed the rope and the rest were run. Neither high nor low is better — it describes "
            "how he scores, not how well."
        ),
        good=(
            "In the IPL most batters sit between 50% and 72%, with about 60% typical. High means "
            "boundary-or-bust (he can go quiet when the rope is guarded); low means he keeps the "
            "score moving with singles and twos. Read it next to his strike rate."
        ),
        direction="descriptive",
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
            "within one over (any run, bye, wide or no-ball breaks the run). Conversion % = pressure "
            "balls where the next ball of that over is a wicket the bowler is credited with (run-outs"
            " don't count) ÷ pressure balls × 100. The last ball of an over has no next ball, so it "
            "isn't counted."
        ),
        read=(
            "When he has bowled four or more dot balls in a row in an over, how often does the very "
            "next ball take a wicket? 10% means one wicket for every ten of those chances."
        ),
        good=(
            "It's a rare event, so most IPL bowlers sit at 0% and anything above zero stands out; 12%"
            " or more is top-10%. Small samples swing a lot — check the pressure-balls column."
        ),
        direction="higher",
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
            "For each wicket, look up the dismissed batter's Bayesian batting skill. Wicket quality ="
            " the average of those skills across the bowler's wickets, so removing top-order stars "
            "scores far higher than mopping up the tail."
        ),
        read=(
            "How good, on average, the batters he gets out are — on the model's batting scale, where "
            "0 is an average batter. A higher number means he removes the dangerous batters, not just"
            " the tail."
        ),
        good=(
            "In the IPL about 0.13 is typical and 0.19 or more is top-10% — a taker of big wickets. "
            "Below 0.05 means most of his wickets are lower-order batters."
        ),
        direction="higher",
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
            "Balls per dismissal = total balls faced ÷ times out (run outs at either end count; "
            "retired hurt doesn't). Longevity index = that figure ÷ the cohort average. 1.0 = exactly"
            " average survival; 1.3 = lasts 30% longer than peers per dismissal."
        ),
        read=(
            "How long he lasts before getting out, compared with a typical batter: 1.0 is typical, "
            "1.5 means he faces 50% more balls per dismissal."
        ),
        good=(
            "In the IPL about 1.1 is typical and 1.6 or more is top-10% — an anchor. Openers and "
            "top-order batters naturally score higher than finishers, whose job is to take risks."
        ),
        direction="higher",
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
            "Setting SR = strike rate over the first 20 balls a batter faces in each innings (wides "
            "aren't balls faced). Slow-start cost = career SR − setting SR. Positive = they start "
            "slower than they bat overall; lower (or negative) is better. Needs 200+ career balls and"
            " 50+ setting balls."
        ),
        read=(
            "How many strike-rate points he loses while getting set (his first 20 balls) compared "
            "with his overall strike rate. 10 means he scores 10 runs per 100 balls slower at the "
            "start; zero or below means he's just as quick from ball one."
        ),
        good=(
            "In the IPL about 5 is typical and 12 or more marks a slow starter. Zero or below is "
            "excellent — no warm-up cost."
        ),
        direction="lower",
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
        read=(
            "A count of his dismissals as wicket-keeper: catches, stumpings and run-outs. It's a "
            "career total, so long careers collect more — compare keepers with similar match counts "
            "(use Min matches)."
        ),
        good=(
            "In the IPL half the keepers on this board have 20 or fewer dismissals and 110 or more is"
            " top-10%. Divide by matches for a per-game feel."
        ),
        direction="higher",
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
            "fielder named is credited; caught-and-bowled is a bowling wicket, excluded). Keepers are"
            " split off to their own board. Dismissals = catches + run-outs."
        ),
        read=(
            "A count of his catches and run-outs in the field. It's a career total, so long careers "
            "collect more — compare fielders with similar match counts (use Min matches)."
        ),
        good=(
            "In the IPL half the fielders on this board have 19 or fewer dismissals and 48 or more is"
            " top-10%. Divide by matches for a per-game feel."
        ),
        direction="higher",
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

DIRECTION_LABEL = {
    "higher": "Higher is better",
    "lower": "Lower is better",
    "descriptive": "Neither — describes a style",
}


def fmt_metric(v: object, col: Column) -> str:
    """A metric value in its display units: "+9.7%" for a pct column, else a plain number."""
    if v is None or v == "":
        return "—"
    try:
        n = float(v)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return "—"
    if n != n:  # NaN
        return "—"
    if col.fmt == "pct":
        p = n * 100
        body = f"{abs(p):.{col.digits if col.digits is not None else 1}f}"
        sign = "+" if p > 0 else "−" if p < 0 else ""
        return f"{sign}{body}%"
    if n.is_integer():
        return f"{int(n):,}"
    return f"{n:,.{col.digits if col.digits is not None else 2}f}"


__all__ = ["DIRECTION_LABEL", "METRIC_BY_SLUG", "METRICS", "Column", "MetricDef", "fmt_metric"]
