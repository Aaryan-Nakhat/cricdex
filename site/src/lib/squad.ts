// Squad-balance analyzer — CANONICAL; the Python port
// `src/cricdex/web_parity/squad_balance.py` mirrors this (locked by
// test_scripts/test_web_parity.py).
//
// Given a chosen set of players, report role mix, overseas count, batting-slot
// coverage, and gaps vs the role minimums + overseas cap. Pure deterministic
// aggregation (no RNG), so TS↔Python match trivially.

export interface SquadPlayer {
  role: string | null;
  is_overseas: boolean;
  batting_position: string | null;
}

export interface SquadReport {
  size: number;
  roles: Record<string, number>;
  slots: Record<string, number>;
  overseas: number;
  overseas_cap: number;
  gaps: string[];
  balanced: boolean;
}

export const DEFAULT_ROLE_MINS: Record<string, number> = {
  batter: 3,
  bowler: 3,
  all_rounder: 1,
  keeper: 1,
};
export const SLOTS = ["opener", "no3", "middle", "finisher", "lower", "tailender"] as const;

export function analyzeSquad(
  players: SquadPlayer[],
  roleMins: Record<string, number> = DEFAULT_ROLE_MINS,
  overseasCap = 8,
): SquadReport {
  const roles: Record<string, number> = {};
  const slots: Record<string, number> = {};
  let overseas = 0;
  for (const p of players) {
    const r = p.role || "?";
    roles[r] = (roles[r] ?? 0) + 1;
    const bp = p.batting_position;
    if (bp) slots[bp] = (slots[bp] ?? 0) + 1;
    if (p.is_overseas) overseas++;
  }

  const gaps: string[] = [];
  for (const [r, m] of Object.entries(roleMins)) {
    const have = roles[r] ?? 0;
    if (have < m) gaps.push(`need ${m - have} more ${r.replace(/_/g, "-")} (have ${have}/${m})`);
  }
  if (overseas > overseasCap) {
    gaps.push(`${overseas - overseasCap} over the overseas cap (${overseas}/${overseasCap})`);
  }
  if (!(slots["opener"] ?? 0)) gaps.push("no recognised opener");
  if (!(slots["finisher"] ?? 0)) gaps.push("no death-overs finisher");

  return {
    size: players.length,
    roles,
    slots,
    overseas,
    overseas_cap: overseasCap,
    gaps,
    balanced: gaps.length === 0,
  };
}
