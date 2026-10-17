// The scorecard numbers every fan knows — batting average, strike rate, economy… — computed from a
// profile's exported career block. A number the export doesn't carry yet comes back null and shows as "—".

import type { Profile } from "./data";

function num(v: unknown): number | null {
  if (v === null || v === undefined || v === "") return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}

export interface StandardStats {
  // batting
  innings: number | null;
  runs: number | null;
  balls: number | null;
  dismissals: number | null;
  average: number | null;
  strikeRate: number | null;
  fifties: number | null;
  hundreds: number | null;
  highest: string | null; // "113*"
  dotPct: number | null; // % of balls faced that were dots
  boundaryPct: number | null; // % of balls faced hit for 4 or 6
  ballsPerBoundary: number | null;
  // bowling
  ballsBowled: number | null;
  wickets: number | null;
  runsConceded: number | null;
  economy: number | null;
  bowlAverage: number | null;
  bowlStrikeRate: number | null;
  best: string | null; // "4/12"
  threeW: number | null; // innings with exactly 3 wickets
  fourW: number | null; // innings with 4 or more wickets
  bowlDotPct: number | null;
}

/** Standard stats from a profile. Dismissals fall back to the dismissal fingerprint's total when the career
 * block doesn't carry them. */
export function standardStats(p: Profile): StandardStats {
  const c = (p.career ?? {}) as Record<string, unknown>;
  const fp = (p.dismissal_fingerprint ?? {}) as Record<string, { total?: number } | null>;
  const cl = ((p.metrics ?? {}) as Record<string, Record<string, unknown> | null>).crease_longevity;
  const runs = num(c.career_runs);
  const balls = num(c.career_balls_faced);
  const dismissals = num(c.career_dismissals) ?? num(fp.batter?.total) ?? num(cl?.dismissals);
  const fours = num(c.career_fours);
  const sixes = num(c.career_sixes);
  const boundaries = fours !== null && sixes !== null ? fours + sixes : null;
  const dots = num(c.career_dots_faced);
  const hs = num(c.career_highest_score);
  const hsNo = c.career_highest_score_not_out === true;

  const ballsBowled = num(c.career_legal_balls_bowled);
  const wickets = num(c.career_wickets);
  const conceded = num(c.career_runs_conceded);
  const bestW = num(c.career_best_bowling_wickets);
  const bestR = num(c.career_best_bowling_runs);
  const dotsBowled = num(c.career_dots_bowled);

  return {
    innings: num(c.career_innings),
    runs,
    balls,
    dismissals,
    average: runs !== null && dismissals ? runs / dismissals : null,
    strikeRate: runs !== null && balls ? (runs / balls) * 100 : null,
    fifties: num(c.career_fifties),
    hundreds: num(c.career_hundreds),
    highest: hs !== null ? `${hs}${hsNo ? "*" : ""}` : null,
    dotPct: dots !== null && balls ? (dots / balls) * 100 : null,
    boundaryPct: boundaries !== null && balls ? (boundaries / balls) * 100 : null,
    ballsPerBoundary: boundaries && balls ? balls / boundaries : null,
    ballsBowled,
    wickets,
    runsConceded: conceded,
    economy: conceded !== null && ballsBowled ? (conceded / ballsBowled) * 6 : null,
    bowlAverage: conceded !== null && wickets ? conceded / wickets : null,
    bowlStrikeRate: ballsBowled !== null && wickets ? ballsBowled / wickets : null,
    best: bestW !== null && bestR !== null ? `${bestW}/${bestR}` : null,
    threeW: num(c.career_three_wkt_hauls),
    fourW: num(c.career_four_wkt_hauls),
    bowlDotPct: dotsBowled !== null && ballsBowled ? (dotsBowled / ballsBowled) * 100 : null,
  };
}

export interface StatRow {
  key: keyof StandardStats;
  label: string;
  hint: string; // plain-English meaning
  digits: number;
  better: "high" | "low" | "none";
  suffix?: string;
}

export const BAT_STATS: StatRow[] = [
  { key: "average", label: "Batting average", hint: "runs per dismissal", digits: 2, better: "high" },
  { key: "strikeRate", label: "Strike rate", hint: "runs per 100 balls", digits: 1, better: "high" },
  { key: "fifties", label: "50s", hint: "innings of 50–99", digits: 0, better: "high" },
  { key: "hundreds", label: "100s", hint: "innings of 100+", digits: 0, better: "high" },
  { key: "highest", label: "Highest score", hint: "* = not out", digits: 0, better: "none" },
  { key: "dotPct", label: "Dot-ball %", hint: "balls faced with no run", digits: 1, better: "low", suffix: "%" },
  { key: "boundaryPct", label: "Boundary %", hint: "balls faced hit for 4 or 6", digits: 1, better: "high", suffix: "%" },
];

export const BOWL_STATS: StatRow[] = [
  { key: "economy", label: "Economy", hint: "runs per over", digits: 2, better: "low" },
  { key: "bowlAverage", label: "Bowling average", hint: "runs per wicket", digits: 2, better: "low" },
  { key: "bowlStrikeRate", label: "Bowling strike rate", hint: "balls per wicket", digits: 1, better: "low" },
  { key: "best", label: "Best figures", hint: "wickets / runs in one innings", digits: 0, better: "none" },
  { key: "threeW", label: "3-wicket hauls", hint: "innings with exactly 3 wickets", digits: 0, better: "high" },
  { key: "fourW", label: "4+ wicket hauls", hint: "innings with 4 or more", digits: 0, better: "high" },
  { key: "bowlDotPct", label: "Dot-ball %", hint: "balls bowled with no run", digits: 1, better: "high", suffix: "%" },
];

/** A stat for display: "—" when the export doesn't carry it. */
export function fmtStat(s: StandardStats, r: StatRow): string {
  const v = s[r.key];
  if (v === null || v === undefined) return "—";
  if (typeof v === "string") return v;
  const body =
    r.digits === 0
      ? Math.round(v).toLocaleString("en-US")
      : v.toLocaleString("en-US", { minimumFractionDigits: r.digits, maximumFractionDigits: r.digits });
  return `${body}${r.suffix ?? ""}`;
}
