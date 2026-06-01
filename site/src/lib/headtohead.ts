import type { RatingRow } from "./data";

// Abramowitz & Stegun 7.1.26 — erf good to ~1e-7, plenty for a CDF.
function erf(x: number): number {
  const sign = x < 0 ? -1 : 1;
  x = Math.abs(x);
  const t = 1 / (1 + 0.3275911 * x);
  const y =
    1 -
    ((((1.061405429 * t - 1.453152027) * t + 1.421413741) * t - 0.284496736) * t +
      0.254829592) *
      t *
      Math.exp(-x * x);
  return sign * y;
}

function normalCdf(z: number): number {
  return 0.5 * (1 + erf(z / Math.SQRT2));
}

export interface Axis {
  mean: number;
  sd: number;
}

/** Complete batting/bowling value = raw sum of the two relevant latent
 * axes (variances add — they're modelled separately). Mirrors
 * scout/ratings/head_to_head.py `_complete_axis`. */
export function completeAxis(r: RatingRow, role: "batter" | "bowler"): Axis | null {
  if (role === "batter") {
    if (r.skill === null || r.survival_skill === null) return null;
    const sd1 = r.skill_sd ?? 0;
    const sd2 = r.survival_skill_sd ?? 0;
    return { mean: r.skill + r.survival_skill, sd: Math.sqrt(sd1 * sd1 + sd2 * sd2) };
  } else {
    if (r.skill === null || r.strike_skill === null) return null;
    const sd1 = r.skill_sd ?? 0;
    const sd2 = r.strike_skill_sd ?? 0;
    return { mean: r.skill + r.strike_skill, sd: Math.sqrt(sd1 * sd1 + sd2 * sd2) };
  }
}

export interface H2HResult {
  role: "batter" | "bowler";
  a: { name: string; axis: Axis };
  b: { name: string; axis: Axis };
  pAbetter: number; // P(A's true skill > B's)
  gap: number; // mean difference (A - B)
  verdict: string;
}

export function headToHead(
  ratings: RatingRow[],
  cidA: string,
  cidB: string,
  role: "batter" | "bowler",
): H2HResult | null {
  const ra = ratings.find((r) => r.cricsheet_id === cidA && r.role === role);
  const rb = ratings.find((r) => r.cricsheet_id === cidB && r.role === role);
  if (!ra || !rb) return null;
  const axA = completeAxis(ra, role);
  const axB = completeAxis(rb, role);
  if (!axA || !axB) return null;

  const denom = Math.sqrt(axA.sd * axA.sd + axB.sd * axB.sd) || 1e-9;
  const p = normalCdf((axA.mean - axB.mean) / denom);

  const pct = Math.round(p * 100);
  let verdict: string;
  if (pct >= 80) verdict = "Clear edge";
  else if (pct >= 65) verdict = "Likely better";
  else if (pct >= 55) verdict = "Slight edge";
  else if (pct > 45) verdict = "Too close to call";
  else verdict = "Other side favoured";

  return {
    role,
    a: { name: ra.unique_name, axis: axA },
    b: { name: rb.unique_name, axis: axB },
    pAbetter: p,
    gap: axA.mean - axB.mean,
    verdict,
  };
}

/** Which roles does a cricsheet_id have a rating for? */
export function rolesFor(ratings: RatingRow[], cid: string): ("batter" | "bowler")[] {
  const out: ("batter" | "bowler")[] = [];
  if (ratings.some((r) => r.cricsheet_id === cid && r.role === "batter")) out.push("batter");
  if (ratings.some((r) => r.cricsheet_id === cid && r.role === "bowler")) out.push("bowler");
  return out;
}
