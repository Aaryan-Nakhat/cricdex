import type { PlayerRow, RatingRow } from "./data";

export interface PoolPlayer {
  cricsheet_id: string;
  name: string;
  role: "batter" | "bowler" | "all_rounder";
  value: number; // complete Bayes value (best of bat/bowl)
  projected_value: number; // scaled to credits (cr)
  base_price: number; // estimated tier (cr)
  vpc: number; // value per credit
}

const ROLE_FLOOR: Record<string, number> = { batter: 0.5, bowler: 0.5, all_rounder: 0.8 };
const PRICE_TIERS = [0.3, 0.5, 0.75, 1.0, 1.5, 2.0];

function priceTier(pv: number): number {
  // monotone map projected value (cr) → an estimated base-price band
  if (pv < 2) return PRICE_TIERS[0];
  if (pv < 3) return PRICE_TIERS[1];
  if (pv < 5) return PRICE_TIERS[2];
  if (pv < 7) return PRICE_TIERS[3];
  if (pv < 10) return PRICE_TIERS[4];
  return PRICE_TIERS[5];
}

/** Build a priced auction pool from ratings + ball counts. Mirrors the
 * CLI's real_pool calibration: value = exp(skill)·role_floor·4, then a
 * base-price tier. (No country data in the static export, so the
 * overseas cap is a desktop-only constraint.) */
export function buildPool(players: PlayerRow[], ratings: RatingRow[]): PoolPlayer[] {
  const ratByKey = new Map<string, RatingRow>();
  for (const r of ratings) ratByKey.set(`${r.cricsheet_id}:${r.role}`, r);

  const ballsById = new Map<string, PlayerRow>();
  for (const p of players) ballsById.set(p.cricsheet_id, p);

  const out: PoolPlayer[] = [];
  const seen = new Set<string>();
  for (const r of ratings) {
    if (seen.has(r.cricsheet_id)) continue;
    seen.add(r.cricsheet_id);
    const p = ballsById.get(r.cricsheet_id);
    if (!p) continue;

    const bat = ratByKey.get(`${r.cricsheet_id}:batter`);
    const bowl = ratByKey.get(`${r.cricsheet_id}:bowler`);
    const batVal = bat?.value ?? null;
    const bowlVal = bowl?.value ?? null;

    // role: all-rounder if meaningful balls both ways, else dominant skill
    const allround = p.balls_faced > 200 && p.balls_bowled > 200;
    let role: PoolPlayer["role"];
    let value: number;
    if (allround) {
      role = "all_rounder";
      value = Math.max(batVal ?? -2, bowlVal ?? -2);
    } else if ((bowlVal ?? -99) > (batVal ?? -99) && p.balls_bowled > p.balls_faced) {
      role = "bowler";
      value = bowlVal ?? -2;
    } else {
      role = "batter";
      value = batVal ?? bowlVal ?? -2;
    }
    if (!Number.isFinite(value)) continue;

    const pv = Math.max(0.5, Math.min(14, Math.exp(value) * ROLE_FLOOR[role] * 4));
    const base = priceTier(pv);
    out.push({
      cricsheet_id: r.cricsheet_id,
      name: r.unique_name,
      role,
      value,
      projected_value: pv,
      base_price: base,
      vpc: pv / base,
    });
  }
  out.sort((a, b) => b.projected_value - a.projected_value);
  return out;
}

export interface SolveOpts {
  purse: number;
  squadSize: number;
  roleMins: { batter: number; bowler: number; all_rounder: number };
}

export interface SolveResult {
  selected: PoolPlayer[];
  spend: number;
  totalValue: number;
  feasible: boolean;
  note: string;
}

/** Greedy value-per-credit fill with role-minimum backfill. A fast
 * browser stand-in for the desktop MILP — good, not provably optimal. */
export function solve(pool: PoolPlayer[], opts: SolveOpts): SolveResult {
  const { purse, squadSize, roleMins } = opts;
  const picked = new Map<string, PoolPlayer>();
  let spend = 0;

  const counts = { batter: 0, bowler: 0, all_rounder: 0 };
  const canAfford = (p: PoolPlayer) => spend + p.base_price <= purse;
  const take = (p: PoolPlayer) => {
    picked.set(p.cricsheet_id, p);
    spend += p.base_price;
    counts[p.role]++;
  };

  // Phase 1 — satisfy each role minimum with the best value-per-credit.
  (["batter", "bowler", "all_rounder"] as const).forEach((role) => {
    const need = roleMins[role];
    const candidates = pool
      .filter((p) => p.role === role && !picked.has(p.cricsheet_id))
      .sort((a, b) => b.vpc - a.vpc);
    for (const c of candidates) {
      if (counts[role] >= need) break;
      if (picked.size >= squadSize) break;
      if (canAfford(c)) take(c);
    }
  });

  // Phase 2 — fill remaining slots by global value-per-credit.
  const rest = pool
    .filter((p) => !picked.has(p.cricsheet_id))
    .sort((a, b) => b.vpc - a.vpc);
  for (const c of rest) {
    if (picked.size >= squadSize) break;
    if (canAfford(c)) take(c);
  }

  const selected = [...picked.values()].sort((a, b) => b.projected_value - a.projected_value);
  const minsMet =
    counts.batter >= roleMins.batter &&
    counts.bowler >= roleMins.bowler &&
    counts.all_rounder >= roleMins.all_rounder;
  const feasible = selected.length > 0 && minsMet;

  let note = "";
  if (!minsMet) note = "Couldn't meet every role minimum within the purse — loosen a constraint.";
  else if (selected.length < squadSize)
    note = `Filled ${selected.length}/${squadSize} slots before the purse ran out.`;
  else note = "Squad complete within all constraints.";

  return {
    selected,
    spend,
    totalValue: selected.reduce((s, p) => s + p.projected_value, 0),
    feasible,
    note,
  };
}
