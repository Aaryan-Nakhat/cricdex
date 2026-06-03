// The 10 novel metrics — one catalog entry each. Drives the metric
// switcher, the leaderboard columns, the sort, and the explainer copy.
// `key` is the row's player-name column; `sort` is the headline column.

export interface Column {
  key: string;
  label: string;
  digits?: number; // numeric formatting
  primary?: boolean; // the headline / sortable metric column
  bar?: boolean; // render an inline magnitude bar
}

export interface MetricDef {
  slug: string;
  name: string;
  one_liner: string;
  what: string; // longer explainer for the page header
  how: string; // step-by-step "how it's calculated" (shown in the i-popover)
  nameCol: string; // column holding the player's name
  higherIsBetter: boolean;
  columns: Column[];
}

export const METRICS: MetricDef[] = [
  {
    slug: "ngi",
    name: "Net Game Impact",
    one_liner: "Total runs added vs a replacement-level player, batting + bowling.",
    what: "NGI rolls a player's batting and bowling contribution into one win-currency number — runs added above a replacement-level player across their career — then normalises per match so part-timers and veterans compare fairly.",
    how: "For every ball, compute expected runs for a replacement-level player in that exact match state (over, wickets, venue). A batter's credit = actual runs − expected; a bowler's = expected − conceded (plus a wicket bonus weighted by the batter's value). Sum a player's batting + bowling credit across all matches → NGI total, then divide by matches → NGI per match.",
    nameCol: "name",
    higherIsBetter: true,
    columns: [
      { key: "name", label: "Player" },
      { key: "ngi_per_match", label: "NGI / match", digits: 3, primary: true, bar: true },
      { key: "ngi_total", label: "NGI total", digits: 1 },
      { key: "ngi_batting", label: "Batting", digits: 1 },
      { key: "ngi_bowling", label: "Bowling", digits: 1 },
      { key: "matches", label: "Matches", digits: 0 },
    ],
  },
  {
    slug: "pressure_runs",
    name: "Pressure Runs",
    one_liner: "Strike rate when the required rate is climbing in a chase.",
    what: "Isolates balls faced under genuine chase pressure (required rate above par) and reports how fast a batter scores in exactly those moments — separating flat-track bullies from players who lift when it's tight.",
    how: "Look only at 2nd-innings (chasing) balls. Flag a ball as 'under pressure' when the required run-rate exceeds a multiplier of par. Over just those flagged balls, Pressure SR = (runs / balls) × 100. % balls is how often this player was actually put under that pressure.",
    nameCol: "batter",
    higherIsBetter: true,
    columns: [
      { key: "batter", label: "Batter" },
      { key: "pressure_sr_per_100_balls", label: "Pressure SR", digits: 1, primary: true, bar: true },
      { key: "pressure_runs", label: "Pressure runs", digits: 0 },
      { key: "pressure_balls", label: "Pressure balls", digits: 0 },
      { key: "pct_balls_under_pressure", label: "% balls", digits: 1 },
    ],
  },
  {
    slug: "intent_curve",
    name: "Intent Curve",
    one_liner: "Strike rate from ball one — who comes out firing, with the full innings shape.",
    what: "Ranks batters by how hard they go in their first 10 balls — pure early intent, before they're set — and shows the full shape of their innings (strike rate across ball-faced buckets) as an inline sparkline. Separates immediate-aggressors from slow-starters who only launch once they're in.",
    how: "Bucket every ball a batter faced by how deep into their innings it was (0–5, 6–10, 11–20, 21–30, 31–50, 51+). Within each bucket, SR = runs ÷ balls × 100 — that 6-point sequence is the curve (the sparkline). The ranking number is Early SR: their combined SR over balls 1–10, weighted by balls faced.",
    nameCol: "batter",
    higherIsBetter: true,
    columns: [
      { key: "batter", label: "Batter" },
      { key: "early_sr", label: "Early SR (balls 1–10)", digits: 1, primary: true, bar: true },
      { key: "curve", label: "Innings curve (0–5 → 51+)" },
      { key: "peak_sr", label: "Peak SR", digits: 1 },
      { key: "balls", label: "Balls", digits: 0 },
    ],
  },
  {
    slug: "dot_ball_recovery",
    name: "Dot-Ball Recovery",
    one_liner: "Runs scored in the 6 balls after eating a dot.",
    what: "Measures how a batter responds to a dot ball: runs accumulated over the next six deliveries. High scorers refuse to let pressure compound; low scorers let dots snowball into more dots.",
    how: "Find every dot ball the batter faced. For each, sum the runs they scored over the following six deliveries. Metric = total of those runs ÷ (dots faced) — average runs reclaimed in the six balls after a dot.",
    nameCol: "batter",
    higherIsBetter: true,
    columns: [
      { key: "batter", label: "Batter" },
      { key: "runs_per_6_after_dot", label: "Runs / 6 after dot", digits: 2, primary: true, bar: true },
      { key: "dots_faced", label: "Dots faced", digits: 0 },
      { key: "runs_in_following", label: "Runs after", digits: 0 },
    ],
  },
  {
    slug: "counter_attack",
    name: "Counter-Attack",
    one_liner: "Strike rate immediately after a partner is dismissed.",
    what: "Captures the player who counter-punches when a wicket has just fallen — strike rate on balls faced right after losing a partner, when most batters retreat into their shell.",
    how: "Mark the balls a batter faced in the window right after a partner was dismissed. Counter SR = (runs / balls) × 100 over just those balls — high means they accelerate through a wicket, not shut down.",
    nameCol: "batter",
    higherIsBetter: true,
    columns: [
      { key: "batter", label: "Batter" },
      { key: "counter_attack_sr", label: "Counter SR", digits: 1, primary: true, bar: true },
      { key: "runs_after_partner_wkt", label: "Runs", digits: 0 },
      { key: "balls_after_partner_wkt", label: "Balls", digits: 0 },
    ],
  },
  {
    slug: "boundary_dependency",
    name: "Boundary Dependency",
    one_liner: "Share of runs that come from fours and sixes.",
    what: "The fraction of a batter's runs scored in boundaries. High dependency flags a player who can go quiet when boundaries dry up; low dependency means they rotate strike and keep the score ticking without the rope.",
    how: "Boundary runs = (fours × 4) + (sixes × 6). Boundary % = boundary runs ÷ total runs × 100. Lower is better here — it means more of the score came from running, not just the rope.",
    nameCol: "batter",
    higherIsBetter: false,
    columns: [
      { key: "batter", label: "Batter" },
      { key: "bdr_pct", label: "Boundary %", digits: 1, primary: true, bar: true },
      { key: "boundary_runs", label: "Boundary runs", digits: 0 },
      { key: "fours", label: "4s", digits: 0 },
      { key: "sixes", label: "6s", digits: 0 },
      { key: "total_runs", label: "Total runs", digits: 0 },
    ],
  },
  {
    slug: "pressure_conversion",
    name: "Pressure Conversion",
    one_liner: "How often a bowler turns pressure balls into wickets.",
    what: "After a bowler builds pressure (a run of dots / tight overs), how often do they actually convert it into a wicket? Separates the bowlers who finish the squeeze from those who let batters off the hook.",
    how: "Identify 'pressure balls' — deliveries that follow a run of dots / tight scoring. Conversion % = wickets taken on those pressure balls ÷ pressure balls × 100. Measures finishing the squeeze, not just bowling dots.",
    nameCol: "bowler",
    higherIsBetter: true,
    columns: [
      { key: "bowler", label: "Bowler" },
      { key: "wicket_rate_pct", label: "Conversion %", digits: 1, primary: true, bar: true },
      { key: "wickets_after_pressure", label: "Wickets", digits: 0 },
      { key: "pressure_balls", label: "Pressure balls", digits: 0 },
    ],
  },
  {
    slug: "wicket_quality",
    name: "Wicket Quality",
    one_liner: "Wickets weighted by the calibre of batter dismissed.",
    what: "Not all wickets are equal. This weights each dismissal by the quality of the batter removed (their Bayesian rating), rewarding bowlers who take the big scalps over those who pad stats against tail-enders.",
    how: "For each wicket, look up the dismissed batter's Bayesian batting value. Sum those values across all the bowler's wickets → wicket quality. Removing top-order stars scores far higher than mopping up the tail.",
    nameCol: "bowler",
    higherIsBetter: true,
    columns: [
      { key: "bowler", label: "Bowler" },
      { key: "wicket_quality", label: "Wicket quality", digits: 3, primary: true, bar: true },
      { key: "wickets", label: "Wickets", digits: 0 },
      { key: "opponents_seen", label: "Opponents", digits: 0 },
    ],
  },
  {
    slug: "crease_longevity",
    name: "Crease Longevity",
    one_liner: "Balls survived per dismissal vs the cohort average.",
    what: "How long a batter typically lasts at the crease — balls faced per dismissal — indexed against the cohort. Above 1.0 means they stick around longer than peers; an anchor's signature.",
    how: "Balls per dismissal = total balls faced ÷ dismissals. Longevity index = that figure ÷ the cohort average. 1.0 = exactly average survival; 1.3 = lasts 30% longer than peers per dismissal.",
    nameCol: "batter",
    higherIsBetter: true,
    columns: [
      { key: "batter", label: "Batter" },
      { key: "longevity_index", label: "Longevity index", digits: 3, primary: true, bar: true },
      { key: "avg_balls_per_dismissal", label: "Balls / dismissal", digits: 1 },
      { key: "cohort_avg", label: "Cohort avg", digits: 1 },
      { key: "innings_count", label: "Innings", digits: 0 },
    ],
  },
  {
    slug: "slow_start_cost",
    name: "Slow-Start Cost",
    one_liner: "Strike-rate drop while setting a total vs chasing.",
    what: "Quantifies how much a batter slows down when batting first (setting) compared to their career strike rate — the hidden cost of cautious starts when there's no target to chase.",
    how: "Setting SR = strike rate on 1st-innings (no target) balls. Slow-start cost = career SR − setting SR. Positive = they bat slower when setting a total; lower (or negative) is better.",
    nameCol: "batter",
    higherIsBetter: false,
    columns: [
      { key: "batter", label: "Batter" },
      { key: "slow_start_cost", label: "Slow-start cost", digits: 1, primary: true, bar: true },
      { key: "career_sr", label: "Career SR", digits: 1 },
      { key: "setting_sr", label: "Setting SR", digits: 1 },
      { key: "setting_balls", label: "Setting balls", digits: 0 },
    ],
  },
];

export const METRIC_BY_SLUG: Record<string, MetricDef> = Object.fromEntries(
  METRICS.map((m) => [m.slug, m]),
);
