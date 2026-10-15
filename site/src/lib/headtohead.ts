// Head-to-head P(A better than B). CANONICAL for the web; the Python engine
// `src/cricdex/scout/ratings/head_to_head.py` is the same logic (locked by
// test_scripts/test_h2h_parity.py) — change both together.

import type { RatingRow } from "./data";

/** erf to ~1e-14: Maclaurin series near 0, continued fraction for erfc beyond.
 * (Python uses math.erf; this keeps the two within float noise.) */
function erf(x: number): number {
  const ax = Math.abs(x);
  if (ax < 2.5) {
    const x2 = x * x;
    let term = x;
    let sum = x;
    for (let n = 1; n < 200; n++) {
      term *= -x2 / n;
      const add = term / (2 * n + 1);
      sum += add;
      if (Math.abs(add) < 1e-17 * Math.abs(sum)) break;
    }
    return (2 / Math.sqrt(Math.PI)) * sum;
  }
  if (ax > 6) return x < 0 ? -1 : 1;
  // erfc(x) = exp(-x²)/√π · 1/(x + (1/2)/(x + 1/(x + (3/2)/(x + …))))
  let f = ax;
  for (let n = 120; n >= 1; n--) f = ax + n / 2 / f;
  const erfc = Math.exp(-ax * ax) / (Math.sqrt(Math.PI) * f);
  return x < 0 ? erfc - 1 : 1 - erfc;
}

export function normalCdf(z: number): number {
  return 0.5 * (1 + erf(z / Math.SQRT2));
}

export interface Axis {
  mean: number;
  sd: number;
}

type RatedRole = "batter" | "bowler";
export type H2HRole = RatedRole | "all_rounder";

const SECOND_AXIS = {
  batter: { col: "survival_skill", sdCol: "survival_skill_sd", full: "scoring + survival", legacy: "scoring only" },
  bowler: { col: "strike_skill", sdCol: "strike_skill_sd", full: "economy + strike", legacy: "economy only" },
} as const;

/** A usable posterior sd, or null when missing / non-positive (unknown — never guessed). */
function usableSd(x: number | null | undefined): number | null {
  return typeof x === "number" && Number.isFinite(x) && x > 0 ? x : null;
}

/** Complete batting/bowling value of one rating row: the fit's `value`/`value_sd`
 * (both axes in population-sd units); older files without `value_sd` → raw sum
 * of the two axes, variances added; legacy runs-only files → the one axis. */
export function completeAxis(r: RatingRow, role: RatedRole): (Axis & { component: string }) | null {
  const ax = SECOND_AXIS[role];
  if (r.skill == null) return null;
  const second = r[ax.col];
  if (second == null) {
    const sd = usableSd(r.skill_sd);
    return sd === null ? null : { mean: r.skill, sd, component: `${ax.legacy} (legacy ratings)` };
  }
  if (r.value != null && r.value_sd != null) {
    const sd = usableSd(r.value_sd);
    return sd === null ? null : { mean: r.value, sd, component: ax.full };
  }
  const sd1 = usableSd(r.skill_sd);
  const sd2 = usableSd(r[ax.sdCol]);
  if (sd1 === null || sd2 === null) return null;
  return { mean: r.skill + second, sd: Math.sqrt(sd1 ** 2 + sd2 ** 2), component: ax.full };
}

export function verdictText(nameA: string, nameB: string, pA: number): string {
  const pct = Math.floor(100 * Math.max(pA, 1 - pA) + 0.5);
  const leader = pA >= 0.5 ? nameA : nameB;
  if (pct < 60) return `too close to call (${pct}% lean to ${leader})`;
  if (pct < 75) return `${leader} likely better (${pct}%)`;
  if (pct < 90) return `${leader} clearly better (${pct}%)`;
  return `${leader} dominant (${pct}%)`;
}

export interface Comparison {
  meanA: number;
  sdA: number;
  meanB: number;
  sdB: number;
  diff: number;
  pooledSd: number;
  pAbetter: number;
  pBbetter: number;
  component: string;
  ballsA: number;
  ballsB: number;
  verdict: string;
}

export type RowsByRole = Partial<Record<RatedRole, RatingRow>>;

/** One role's comparison ("all_rounder" = complete batting + complete bowling,
 * variances add). Null when either side lacks a comparable rating. */
export function compareRows(
  nameA: string,
  nameB: string,
  rowsA: RowsByRole,
  rowsB: RowsByRole,
  role: H2HRole,
): Comparison | null {
  const roles: RatedRole[] = role === "all_rounder" ? ["batter", "bowler"] : [role];
  const axesA: Axis[] = [];
  const axesB: Axis[] = [];
  for (const r of roles) {
    const ra = rowsA[r];
    const rb = rowsB[r];
    if (!ra || !rb) return null;
    const ca = completeAxis(ra, r);
    const cb = completeAxis(rb, r);
    // different components = different scales (a legacy row vs a full one)
    if (!ca || !cb || ca.component !== cb.component) return null;
    axesA.push(ca);
    axesB.push(cb);
  }
  const comp = roles.map((r) => completeAxis(rowsA[r]!, r)!.component).join(" | ");
  let meanA = 0, meanB = 0, varA = 0, varB = 0;
  for (const a of axesA) {
    meanA += a.mean;
    varA += a.sd ** 2;
  }
  for (const b of axesB) {
    meanB += b.mean;
    varB += b.sd ** 2;
  }
  const sdA = Math.sqrt(varA);
  const sdB = Math.sqrt(varB);
  const diff = meanA - meanB;
  const pooledSd = Math.sqrt(sdA ** 2 + sdB ** 2) || 1e-9;
  const pA = normalCdf(diff / pooledSd);
  let ballsA = 0, ballsB = 0;
  for (const r of roles) {
    ballsA += rowsA[r]!.balls ?? 0;
    ballsB += rowsB[r]!.balls ?? 0;
  }
  return {
    meanA,
    sdA,
    meanB,
    sdB,
    diff,
    pooledSd,
    pAbetter: pA,
    pBbetter: 1 - pA,
    component: comp,
    ballsA,
    ballsB,
    verdict: verdictText(nameA, nameB, pA),
  };
}

function rowsFor(ratings: RatingRow[], cid: string): RowsByRole {
  const out: RowsByRole = {};
  for (const r of ratings) if (r.cricsheet_id === cid) out[r.role] = r;
  return out;
}

export interface H2HResult extends Comparison {
  role: H2HRole;
  a: { name: string; axis: Axis };
  b: { name: string; axis: Axis };
}

export function headToHead(
  ratings: RatingRow[],
  cidA: string,
  cidB: string,
  role: H2HRole,
): H2HResult | null {
  const rowsA = rowsFor(ratings, cidA);
  const rowsB = rowsFor(ratings, cidB);
  const nameOf = (rows: RowsByRole, cid: string) =>
    rows.batter?.unique_name ?? rows.bowler?.unique_name ?? cid;
  const nameA = nameOf(rowsA, cidA);
  const nameB = nameOf(rowsB, cidB);
  const c = compareRows(nameA, nameB, rowsA, rowsB, role);
  if (!c) return null;
  return {
    ...c,
    role,
    a: { name: nameA, axis: { mean: c.meanA, sd: c.sdA } },
    b: { name: nameB, axis: { mean: c.meanB, sd: c.sdB } },
  };
}

/** Which comparisons a cricsheet_id can take part in ("all_rounder" needs both ratings). */
export function rolesFor(ratings: RatingRow[], cid: string): H2HRole[] {
  const rows = rowsFor(ratings, cid);
  const out: H2HRole[] = [];
  if (rows.batter) out.push("batter");
  if (rows.bowler) out.push("bowler");
  if (rows.batter && rows.bowler) out.push("all_rounder");
  return out;
}
