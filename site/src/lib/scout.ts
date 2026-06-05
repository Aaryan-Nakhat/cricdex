// Scout look-alikes + gems + replacement-by-need. CANONICAL; the Python port
// `src/cricdex/web_parity/scout.py` mirrors this (locked by
// test_scripts/test_web_parity.py). Scout.tsx renders these; the desktop
// surfaces re-use the Python port.

import type { ScoutPlayer } from "./data.ts";
import { estValue, type PriceTier, type Role } from "./auction.ts";

// Uncapped "gem": punches above its sample — high standing on low exposure.
export const GEM_Z = 0.6;

// Half-up 1dp, matched by the Python `_r1` so saving-ranked rows agree.
const r1 = (x: number): number => Math.floor(x * 10 + 0.5) / 10;

export type SimilarRow = ScoutPlayer & { sim: number };
export type ReplacementRow = SimilarRow & { est_cr: number; saving: number };

/** Median SMAT exposure (balls > 0) — the gem cutoff. balls[floor(len/2)]. */
export function gemThreshold(smat: ScoutPlayer[]): number | null {
  const vals = smat.filter((p) => (p.balls ?? 0) > 0).map((p) => p.balls).sort((a, b) => a - b);
  if (!vals.length) return null;
  return vals[Math.floor(vals.length / 2)];
}

export function isGem(p: ScoutPlayer, medianBalls: number | null): boolean {
  if (medianBalls === null) return false;
  return p.z >= GEM_Z && (p.balls ?? 0) > 0 && p.balls <= medianBalls;
}

/** Most-similar players of the chosen role (defaults to the pick's own),
 * optionally a seam/spin (bowlers) and batting-slot filter. Sorted by
 * similarity desc, top-N. */
export function similarTo(
  sel: ScoutPlayer,
  pool: ScoutPlayer[],
  role?: string,
  pos?: string,
  top = 8,
): SimilarRow[] {
  const wantRole = role || sel.role;
  const out: SimilarRow[] = [];
  for (const p of pool) {
    if (p.cricsheet_id === sel.cricsheet_id || p.role !== wantRole) continue;
    if (wantRole === "bowler" && sel.bowling_category && p.bowling_category !== sel.bowling_category)
      continue;
    if (pos && p.batting_position !== pos) continue;
    const sim = Math.max(0, 1 - Math.abs(p.z - sel.z) / 2.5);
    out.push({ ...p, sim });
  }
  // Stable sort by sim desc (ties keep pool order — matches Python stable sort).
  out.sort((a, b) => b.sim - a.sim);
  return out.slice(0, top);
}

/** Cheaper same-mould replacements for `sel`: similar players (same role,
 * optional batting slot) priced ≤ `maxPrice` (defaults to the pick's own IPL
 * price), ranked by saving then similarity. Each row carries est_cr + saving. */
export function replacementByNeed(
  sel: ScoutPlayer,
  pool: ScoutPlayer[],
  tier: PriceTier = "ipl",
  role?: string,
  maxPrice?: number,
  pos?: string,
  top = 8,
): ReplacementRow[] {
  const selPrice = estValue(sel.value, sel.role as Role, "ipl");
  const cap = maxPrice !== undefined ? maxPrice : selPrice;
  const out: ReplacementRow[] = [];
  for (const r of similarTo(sel, pool, role, pos, 200)) {
    const price = estValue(r.value, r.role as Role, tier);
    if (price > cap) continue;
    out.push({ ...r, est_cr: r1(price), saving: r1(Math.max(0, selPrice - price)) });
  }
  // Biggest saving, then closest. Stable sort, matching Python's tuple key.
  out.sort((a, b) => b.saving - a.saving || b.sim - a.sim);
  return out.slice(0, top);
}
