// Scout look-alikes + gems. CANONICAL; the Python port
// `src/cricdex/web_parity/scout.py` mirrors this (locked by
// test_scripts/test_web_parity.py). Scout.tsx renders these; the desktop
// surfaces re-use the Python port.

import type { ScoutPlayer } from "./data.ts";

// Uncapped "gem": punches above its sample — high standing on low exposure.
export const GEM_Z = 0.6;

export type SimilarRow = ScoutPlayer & { sim: number };

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
