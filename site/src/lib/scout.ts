// Scout look-alikes + gems. CANONICAL; the Python port
// `src/cricdesk/web_parity/scout.py` mirrors this (locked by
// test_scripts/test_web_parity.py). Scout.tsx renders these; the desktop
// surfaces re-use the Python port.

import type { ScoutPlayer } from "./data.ts";

// Uncapped "gem": punches above its sample — high standing on low exposure.
export const GEM_Z = 0.6;

/** `pos` value meaning "the pick's own batting band" (top / middle / lower order). */
export const SAME_SLOT = "same";

/** Batting slot -> band: a No. 3 matches openers, a finisher matches the middle order. */
export const SLOT_BAND: Record<string, string> = {
  opener: "top",
  no3: "top",
  middle: "middle",
  finisher: "middle",
  lower: "lower",
  tailender: "lower",
};
export const BAND_LABEL: Record<string, string> = {
  top: "Top order (1–3)",
  middle: "Middle order (4–7)",
  lower: "Lower order (8–11)",
};

/** The band a slot belongs to ("" when the slot is unknown). */
export function slotBand(pos: string | null | undefined): string {
  return pos ? (SLOT_BAND[pos] ?? "") : "";
}

/** Country filter: the pick's own country, every other country, or anyone. */
export type CountryMode = "same" | "overseas" | "all";

export interface SimilarOpts {
  /** Which countries count (default "all"). */
  country?: CountryMode;
  /** Country assumed for a pool player with none on file (a domestic pool: every SMAT player is Indian). */
  fallbackCountry?: string | null;
}

export type SimilarRow = ScoutPlayer & { sim: number };

// Older exports mix IOC-style and ISO-3 codes for the same nation; compare on one spelling.
const COUNTRY_ALIAS: Record<string, string> = { RSA: "ZAF", SA: "ZAF", SRI: "LKA", SL: "LKA" };

/** One spelling per nation ("RSA" and "ZAF" are the same team); null when unknown. */
export function normCountry(c: string | null | undefined): string | null {
  if (!c) return null;
  const up = c.trim().toUpperCase();
  return up ? (COUNTRY_ALIAS[up] ?? up) : null;
}

/** Roles that bowl: these must match the pick's seam / spin type. */
const BOWLING_ROLES = new Set(["bowler", "all_rounder"]);

/** Median SMAT exposure (balls > 0) — the gem cutoff. balls[floor(len/2)]: the
 * upper-middle value for an even count (not averaged), the middle one for an odd count. */
export function gemThreshold(smat: ScoutPlayer[]): number | null {
  const vals = smat.filter((p) => (p.balls ?? 0) > 0).map((p) => p.balls).sort((a, b) => a - b);
  if (!vals.length) return null;
  return vals[Math.floor(vals.length / 2)];
}

export function isGem(p: ScoutPlayer, medianBalls: number | null): boolean {
  if (medianBalls === null) return false;
  return p.z >= GEM_Z && (p.balls ?? 0) > 0 && p.balls <= medianBalls;
}

/** Most-similar players of the chosen role (defaults to the pick's own), of the
 * same type: a bowler or all-rounder only matches players who bowl the same way
 * (seam with seam, spin with spin). `pos` narrows the batting slot ("" = any,
 * "same" = the pick's own band: top / middle / lower order, else one exact
 * slot). `opts.country` keeps the pick's country, every other country, or all.
 * Sorted by similarity desc, top-N. */
export function similarTo(
  sel: ScoutPlayer,
  pool: ScoutPlayer[],
  role?: string,
  pos?: string,
  top = 8,
  opts: SimilarOpts = {},
): SimilarRow[] {
  const wantRole = role || sel.role;
  const wantBand = pos === SAME_SLOT ? slotBand(sel.batting_position) : "";
  const wantPos = pos === SAME_SLOT ? "" : (pos ?? "");
  const mode: CountryMode = opts.country ?? "all";
  const selCountry = normCountry(sel.country);
  const fallback = normCountry(opts.fallbackCountry);
  const out: SimilarRow[] = [];
  for (const p of pool) {
    if (p.cricsheet_id === sel.cricsheet_id || p.role !== wantRole) continue;
    if (
      BOWLING_ROLES.has(wantRole) &&
      BOWLING_ROLES.has(sel.role) &&
      sel.bowling_category &&
      p.bowling_category !== sel.bowling_category
    )
      continue;
    if (wantPos && p.batting_position !== wantPos) continue;
    if (wantBand && slotBand(p.batting_position) !== wantBand) continue;
    if (mode !== "all" && selCountry) {
      const pc = normCountry(p.country) ?? fallback;
      if (pc === null) continue; // unknown country: can't say it's the same or overseas
      if (mode === "same" ? pc !== selCountry : pc === selCountry) continue;
    }
    const sim = Math.max(0, 1 - Math.abs(p.z - sel.z) / 2.5);
    out.push({ ...p, sim });
  }
  // Stable sort by sim desc (ties keep pool order — matches Python stable sort).
  out.sort((a, b) => b.sim - a.sim);
  return out.slice(0, top);
}
