import type { PlayerRow, RatingRow } from "./data";

export type Role = "batter" | "bowler" | "all_rounder" | "keeper";

export interface PoolPlayer {
  cricsheet_id: string;
  name: string;
  role: Role;
  country: string;
  is_overseas: boolean;
  value: number; // complete Bayes value (best of bat/bowl)
  projected_value: number; // scaled to credits (cr)
  base_price: number; // estimated tier (cr)
  vpc: number; // value per credit
}

const ROLE_FLOOR: Record<Role, number> = {
  batter: 0.5,
  bowler: 0.5,
  all_rounder: 0.8,
  keeper: 0.6,
};
const PRICE_TIERS = [0.3, 0.5, 0.75, 1.0, 1.5, 2.0];

function priceTier(pv: number): number {
  if (pv < 2) return PRICE_TIERS[0];
  if (pv < 3) return PRICE_TIERS[1];
  if (pv < 5) return PRICE_TIERS[2];
  if (pv < 7) return PRICE_TIERS[3];
  if (pv < 10) return PRICE_TIERS[4];
  return PRICE_TIERS[5];
}

function roleOf(p: PlayerRow): Role {
  // Prefer Gemini taxonomy; fall back to ball counts.
  switch (p.primary_role) {
    case "wk_batter":
      return "keeper";
    case "allrounder":
      return "all_rounder";
    case "bowler":
      return "bowler";
    case "batter":
      return "batter";
  }
  if (p.balls_faced > 200 && p.balls_bowled > 200) return "all_rounder";
  return p.balls_bowled > p.balls_faced ? "bowler" : "batter";
}

/** Priced auction pool from ratings + ball counts + taxonomy (country,
 * role). Mirrors the CLI real_pool calibration. */
export function buildPool(players: PlayerRow[], ratings: RatingRow[]): PoolPlayer[] {
  const ratByKey = new Map<string, RatingRow>();
  for (const r of ratings) ratByKey.set(`${r.cricsheet_id}:${r.role}`, r);
  const byId = new Map<string, PlayerRow>();
  for (const p of players) byId.set(p.cricsheet_id, p);

  const out: PoolPlayer[] = [];
  const seen = new Set<string>();
  for (const r of ratings) {
    if (seen.has(r.cricsheet_id)) continue;
    seen.add(r.cricsheet_id);
    const p = byId.get(r.cricsheet_id);
    if (!p) continue;
    const bat = ratByKey.get(`${r.cricsheet_id}:batter`);
    const bowl = ratByKey.get(`${r.cricsheet_id}:bowler`);
    const value = Math.max(bat?.value ?? -99, bowl?.value ?? -99);
    if (!Number.isFinite(value) || value < -90) continue;

    const role = roleOf(p);
    const country = p.country ?? "—";
    const pv = Math.max(0.5, Math.min(14, Math.exp(value) * ROLE_FLOOR[role] * 4));
    const base = priceTier(pv);
    out.push({
      cricsheet_id: r.cricsheet_id,
      name: r.unique_name,
      role,
      country,
      is_overseas: !!p.country && p.country !== "IND",
      value,
      projected_value: pv,
      base_price: base,
      vpc: pv / base,
    });
  }
  out.sort((a, b) => b.projected_value - a.projected_value);
  return out;
}

// ---- greedy single-squad optimiser (unchanged behaviour) ------------------

export interface SolveOpts {
  purse: number;
  squadSize: number;
  roleMins: { batter: number; bowler: number; all_rounder: number; keeper: number };
  overseasCap: number;
}

export interface SolveResult {
  selected: PoolPlayer[];
  spend: number;
  totalValue: number;
  overseas: number;
  feasible: boolean;
  note: string;
}

export function solve(pool: PoolPlayer[], opts: SolveOpts): SolveResult {
  const { purse, squadSize, roleMins, overseasCap } = opts;
  const picked = new Map<string, PoolPlayer>();
  let spend = 0;
  let overseas = 0;
  const counts: Record<Role, number> = { batter: 0, bowler: 0, all_rounder: 0, keeper: 0 };
  const canAfford = (p: PoolPlayer) =>
    spend + p.base_price <= purse && (!p.is_overseas || overseas < overseasCap);
  const take = (p: PoolPlayer) => {
    picked.set(p.cricsheet_id, p);
    spend += p.base_price;
    counts[p.role]++;
    if (p.is_overseas) overseas++;
  };

  (Object.keys(roleMins) as Role[]).forEach((role) => {
    const need = roleMins[role];
    const cands = pool
      .filter((p) => p.role === role && !picked.has(p.cricsheet_id))
      .sort((a, b) => b.vpc - a.vpc);
    for (const c of cands) {
      if (counts[role] >= need || picked.size >= squadSize) break;
      if (canAfford(c)) take(c);
    }
  });
  for (const c of pool.filter((p) => !picked.has(p.cricsheet_id)).sort((a, b) => b.vpc - a.vpc)) {
    if (picked.size >= squadSize) break;
    if (canAfford(c)) take(c);
  }

  const selected = [...picked.values()].sort((a, b) => b.projected_value - a.projected_value);
  const minsMet = (Object.keys(roleMins) as Role[]).every((r) => counts[r] >= roleMins[r]);
  return {
    selected,
    spend,
    overseas,
    totalValue: selected.reduce((s, p) => s + p.projected_value, 0),
    feasible: selected.length > 0 && minsMet,
    note: !minsMet
      ? "Couldn't meet every role minimum within purse/overseas cap — loosen a constraint."
      : selected.length < squadSize
        ? `Filled ${selected.length}/${squadSize} slots before the purse ran out.`
        : "Squad complete within all constraints.",
  };
}

// ---- franchise personalities + Monte-Carlo auction ------------------------

export interface Archetype {
  id: string;
  blurb: string;
  aggression: number; // bid multiplier on perceived value
  risk: number; // jitter
  overseasAppetite: number; // 0..1 bias toward overseas
  roleMins: Record<Role, number>;
}

export const ARCHETYPES: Archetype[] = [
  { id: "MarqueeChaser", blurb: "Overpays for stars; empties the purse early.", aggression: 1.35, risk: 0.2, overseasAppetite: 0.6, roleMins: { batter: 6, bowler: 4, all_rounder: 4, keeper: 2 } },
  { id: "ValueHunter", blurb: "Disciplined; hunts bargains, walks away from bidding wars.", aggression: 0.85, risk: 0.3, overseasAppetite: 0.45, roleMins: { batter: 5, bowler: 5, all_rounder: 3, keeper: 2 } },
  { id: "OverseasHeavy", blurb: "Loads up on overseas talent up to the cap.", aggression: 1.15, risk: 0.18, overseasAppetite: 0.9, roleMins: { batter: 5, bowler: 5, all_rounder: 3, keeper: 2 } },
  { id: "IndianFocus", blurb: "Builds a local core; sparing on overseas slots.", aggression: 1.05, risk: 0.15, overseasAppetite: 0.2, roleMins: { batter: 7, bowler: 5, all_rounder: 3, keeper: 2 } },
  { id: "AllRounderStack", blurb: "Hoards all-rounders for balance.", aggression: 1.1, risk: 0.22, overseasAppetite: 0.55, roleMins: { batter: 4, bowler: 4, all_rounder: 6, keeper: 2 } },
  { id: "Balanced", blurb: "Even spread, steady cap management.", aggression: 1.0, risk: 0.15, overseasAppetite: 0.5, roleMins: { batter: 5, bowler: 5, all_rounder: 3, keeper: 2 } },
];

export const ARCH_BY_ID: Record<string, Archetype> = Object.fromEntries(
  ARCHETYPES.map((a) => [a.id, a]),
);

export const IPL_TEAMS_DEFAULT: { team: string; personality: string }[] = [
  { team: "CSK", personality: "Balanced" },
  { team: "MI", personality: "MarqueeChaser" },
  { team: "RCB", personality: "MarqueeChaser" },
  { team: "KKR", personality: "AllRounderStack" },
  { team: "DC", personality: "IndianFocus" },
  { team: "PBKS", personality: "ValueHunter" },
  { team: "SRH", personality: "OverseasHeavy" },
  { team: "GT", personality: "Balanced" },
  { team: "RR", personality: "ValueHunter" },
  { team: "LSG", personality: "OverseasHeavy" },
];

// deterministic-per-index PRNG (no Math.random — keeps runs reproducible
// and avoids the workflow ban; varies by trial+player index)
function rng(seed: number): () => number {
  let s = seed >>> 0;
  return () => {
    s = (s * 1664525 + 1013904223) >>> 0;
    return s / 4294967296;
  };
}

export interface SimOpts {
  purse: number;
  squadSize: number;
  overseasCap: number;
  trials: number;
}

export interface TeamState {
  team: string;
  personality: string;
  spend: number;
  overseas: number;
  squad: PoolPlayer[];
  counts: Record<Role, number>;
}

export interface SimResult {
  teams: { team: string; personality: string; avgSpend: number; avgValue: number; avgOverseas: number; avgSize: number }[];
  // per marquee player: win share by team
  marquee: { player: PoolPlayer; winners: { team: string; pct: number }[] }[];
  // one representative final draft (the median-ish trial)
  sampleDraft: TeamState[];
}

function oneTrial(pool: PoolPlayer[], teamCfg: { team: string; personality: string }[], opts: SimOpts, seed: number): TeamState[] {
  const rand = rng(seed);
  const states: TeamState[] = teamCfg.map((t) => ({
    team: t.team,
    personality: t.personality,
    spend: 0,
    overseas: 0,
    squad: [],
    counts: { batter: 0, bowler: 0, all_rounder: 0, keeper: 0 },
  }));

  // marquee-first order with small jitter so the draft varies per trial
  const order = [...pool]
    .map((p) => ({ p, k: p.projected_value * (1 + (rand() - 0.5) * 0.1) }))
    .sort((a, b) => b.k - a.k)
    .map((x) => x.p);

  for (const player of order) {
    let bestTeam = -1;
    let bestBid = 0;
    let secondBid = player.base_price;
    for (let i = 0; i < states.length; i++) {
      const st = states[i];
      const arc = ARCH_BY_ID[st.personality] ?? ARCH_BY_ID.Balanced;
      if (st.squad.length >= opts.squadSize) continue;
      if (player.is_overseas && st.overseas >= opts.overseasCap) continue;
      if (st.spend + player.base_price > opts.purse) continue;
      // willingness to pay
      const need = st.counts[player.role] < arc.roleMins[player.role] ? 1.5 : 0.7;
      const overseasBias = player.is_overseas ? arc.overseasAppetite * 1.4 : 1;
      const jitter = 1 + (rand() - 0.5) * 2 * arc.risk;
      let wtp = player.projected_value * arc.aggression * need * overseasBias * jitter;
      wtp = Math.min(wtp, opts.purse - st.spend); // can't exceed remaining purse
      if (wtp < player.base_price) continue;
      if (wtp > bestBid) {
        secondBid = bestBid > 0 ? bestBid : player.base_price;
        bestBid = wtp;
        bestTeam = i;
      } else if (wtp > secondBid) {
        secondBid = wtp;
      }
    }
    if (bestTeam >= 0) {
      const st = states[bestTeam];
      const price = Math.max(player.base_price, Math.min(bestBid, secondBid * 1.02));
      st.squad.push(player);
      st.spend += price;
      st.counts[player.role]++;
      if (player.is_overseas) st.overseas++;
    }
  }
  return states;
}

export function simulateAuction(
  pool: PoolPlayer[],
  teamCfg: { team: string; personality: string }[],
  opts: SimOpts,
): SimResult {
  // cap pool size for browser speed — the marquee + mid tiers decide it
  const usePool = pool.slice(0, 160);
  const agg = teamCfg.map((t) => ({ team: t.team, personality: t.personality, spend: 0, value: 0, overseas: 0, size: 0 }));
  const marqueeWins = new Map<string, Map<string, number>>(); // cid -> team -> count
  const top = usePool.slice(0, 20);
  for (const p of top) marqueeWins.set(p.cricsheet_id, new Map());

  let sampleDraft: TeamState[] = [];
  for (let t = 0; t < opts.trials; t++) {
    const states = oneTrial(usePool, teamCfg, opts, 1000 + t * 7919);
    if (t === Math.floor(opts.trials / 2)) sampleDraft = states;
    states.forEach((st, i) => {
      agg[i].spend += st.spend;
      agg[i].value += st.squad.reduce((s, p) => s + p.projected_value, 0);
      agg[i].overseas += st.overseas;
      agg[i].size += st.squad.length;
      for (const p of st.squad) {
        const m = marqueeWins.get(p.cricsheet_id);
        if (m) m.set(st.team, (m.get(st.team) ?? 0) + 1);
      }
    });
  }
  const n = opts.trials;
  return {
    teams: agg.map((a) => ({
      team: a.team,
      personality: a.personality,
      avgSpend: a.spend / n,
      avgValue: a.value / n,
      avgOverseas: a.overseas / n,
      avgSize: a.size / n,
    })),
    marquee: top.map((p) => {
      const m = marqueeWins.get(p.cricsheet_id)!;
      const winners = [...m.entries()]
        .map(([team, c]) => ({ team, pct: (c / n) * 100 }))
        .sort((a, b) => b.pct - a.pct)
        .slice(0, 3);
      return { player: p, winners };
    }),
    sampleDraft,
  };
}
