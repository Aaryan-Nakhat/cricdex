import type { AuctionPoolRow } from "./data";

export type Role = "batter" | "bowler" | "all_rounder" | "keeper";

export interface PoolPlayer {
  cricsheet_id: string;
  name: string;
  role: Role;
  country: string;
  is_overseas: boolean;
  team: string | null; // current IPL franchise code, null = free agent
  value: number; // complete Bayes value (best of bat/bowl)
  projected_value: number; // scaled to credits (cr)
  base_price: number; // estimated tier (cr)
  vpc: number; // value per credit
}

// All-rounders / keepers carry a small scarcity premium.
const ROLE_MULT: Record<Role, number> = {
  batter: 1.0,
  bowler: 1.0,
  all_rounder: 1.15,
  keeper: 1.05,
};
// Calibrated to real IPL crore: the Bayes `value` is compressed (~ -0.27..+0.48),
// so amplify exponentially. value 0.48 -> ~26cr (Klaasen/Pant tier), 0.33 -> ~11,
// 0.13 -> ~3.5, -0.27 -> floor 0.3. Anchored to the 2025 auction/retention prices.
const PV_BASE = 1.6;
const PV_SCALE = 5.8;
const PV_MAX = 27;

// IPL base-price set bands (cr) — what a player ENTERS the auction at.
const PRICE_TIERS = [0.3, 0.5, 0.75, 1.0, 1.5, 2.0];

function priceTier(pv: number): number {
  if (pv < 2) return PRICE_TIERS[0];
  if (pv < 4) return PRICE_TIERS[1];
  if (pv < 7) return PRICE_TIERS[2];
  if (pv < 11) return PRICE_TIERS[3];
  if (pv < 16) return PRICE_TIERS[4];
  return PRICE_TIERS[5];
}

/** Price the big auction pool (every ACTIVE rated IPL player). Each row
 * already carries value / role / country / team; we add crore pricing. */
export function buildPool(rows: AuctionPoolRow[]): PoolPlayer[] {
  const out: PoolPlayer[] = rows.map((r) => {
    const pv = Math.max(
      0.3,
      Math.min(PV_MAX, PV_BASE * Math.exp(PV_SCALE * r.value) * ROLE_MULT[r.role]),
    );
    const base = priceTier(pv);
    return {
      cricsheet_id: r.cricsheet_id,
      name: r.name,
      role: r.role,
      country: r.country ?? "—",
      is_overseas: r.is_overseas,
      team: r.team,
      value: r.value,
      projected_value: pv,
      base_price: base,
      vpc: pv / base,
    };
  });
  out.sort((a, b) => b.projected_value - a.projected_value);
  return out;
}

// ---- greedy single-squad optimiser (Build my squad) -----------------------

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

// ---- franchise personalities ----------------------------------------------

export interface Archetype {
  id: string;
  blurb: string;
  aggression: number;
  risk: number;
  overseasAppetite: number;
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

function rng(seed: number): () => number {
  let s = seed >>> 0;
  return () => {
    s = (s * 1664525 + 1013904223) >>> 0;
    return s / 4294967296;
  };
}

// ---- retentions + mega/mini auction ---------------------------------------

export type AuctionMode = "mega" | "mini";

// How many a team keeps by default. Mega ≈ real 2025 retention size; Mini =
// keep most of the squad (only a few slots auctioned).
export const MINI_RETAIN = 12;
// Cost (cr) for a retained player with no known real price: IPL slabs for the
// first few, then a floor — used for Mini defaults / user-added retentions.
const SLABS = [18, 14, 11, 18, 14];
function slabCost(i: number): number {
  return SLABS[i] ?? 4;
}

/** Default retentions per team. Mega = the real 2025 lists (passed in as
 * megaIds); Mini = each team's top-{MINI_RETAIN} active players by value. */
export function defaultRetentions(
  pool: PoolPlayer[],
  teamCfg: { team: string }[],
  mode: AuctionMode,
  megaIds: Record<string, string[]>,
): Record<string, string[]> {
  const out: Record<string, string[]> = {};
  for (const { team } of teamCfg) {
    if (mode === "mega") {
      out[team] = (megaIds[team] ?? []).filter((id) => pool.some((p) => p.cricsheet_id === id));
    } else {
      out[team] = pool
        .filter((p) => p.team === team)
        .sort((a, b) => b.value - a.value)
        .slice(0, MINI_RETAIN)
        .map((p) => p.cricsheet_id);
    }
  }
  return out;
}

export interface SimOpts {
  purse: number;
  squadSize: number;
  overseasCap: number;
  trials: number;
  mode: AuctionMode;
  retentions: Record<string, string[]>; // team -> retained cricsheet_ids (editable)
  realPrices: Record<string, number>; // cricsheet_id -> real retention price (cr)
}

interface FranchiseBase {
  team: string;
  personality: string;
  retained: PoolPlayer[];
  retainSpend: number;
  retainOverseas: number;
}

export interface TeamState {
  team: string;
  personality: string;
  retained: PoolPlayer[];
  bought: PoolPlayer[];
  spent: number; // auction spend only
  overseas: number; // retained + bought
  counts: Record<Role, number>;
}

export interface SimResult {
  mode: AuctionMode;
  bases: FranchiseBase[]; // retentions (constant across trials)
  poolSize: number;
  teams: {
    team: string;
    personality: string;
    retained: number;
    avgBought: number;
    avgSpend: number;
    avgValue: number; // retained + bought projected value
    avgOverseas: number;
  }[];
  marquee: { player: PoolPlayer; winners: { team: string; pct: number }[] }[];
  sampleDraft: TeamState[];
}

function buildFranchises(
  pool: PoolPlayer[],
  teamCfg: { team: string; personality: string }[],
  opts: SimOpts,
): { bases: FranchiseBase[]; auctionPool: PoolPlayer[] } {
  const byId = new Map(pool.map((p) => [p.cricsheet_id, p]));
  const retainedIds = new Set<string>();
  const bases: FranchiseBase[] = teamCfg.map(({ team, personality }) => {
    const ids = opts.retentions[team] ?? [];
    const retained = ids.map((id) => byId.get(id)).filter((p): p is PoolPlayer => !!p);
    let retainSpend = 0;
    let retainOverseas = 0;
    retained.forEach((p, i) => {
      retainedIds.add(p.cricsheet_id);
      // real retention price if known, else an IPL slab estimate
      retainSpend += opts.realPrices[p.cricsheet_id] ?? slabCost(i);
      if (p.is_overseas) retainOverseas++;
    });
    return { team, personality, retained, retainSpend, retainOverseas };
  });
  const auctionPool = pool.filter((p) => !retainedIds.has(p.cricsheet_id));
  return { bases, auctionPool };
}

function freshState(b: FranchiseBase): TeamState {
  const counts: Record<Role, number> = { batter: 0, bowler: 0, all_rounder: 0, keeper: 0 };
  for (const p of b.retained) counts[p.role]++;
  return {
    team: b.team,
    personality: b.personality,
    retained: b.retained,
    bought: [],
    spent: 0,
    overseas: b.retainOverseas,
    counts,
  };
}

const MIN_BASE = 0.3; // cheapest base price (cr) — reserve this per unfilled slot
const MIN_SQUAD = 18; // IPL rule: every team must end with ≥18

function oneTrial(
  bases: FranchiseBase[],
  auctionPool: PoolPlayer[],
  opts: SimOpts,
  seed: number,
): TeamState[] {
  const rand = rng(seed);
  const states = bases.map(freshState);
  const filledOf = (st: TeamState) => st.retained.length + st.bought.length;
  const remPurseOf = (i: number) => opts.purse - bases[i].retainSpend - states[i].spent;
  const buy = (i: number, player: PoolPlayer, price: number) => {
    const st = states[i];
    st.bought.push(player);
    st.spent += price;
    st.counts[player.role]++;
    if (player.is_overseas) st.overseas++;
  };

  const order = [...auctionPool]
    .map((p) => ({ p, k: p.projected_value * (1 + (rand() - 0.5) * 0.1) }))
    .sort((a, b) => b.k - a.k)
    .map((x) => x.p);
  const sold = new Set<string>();

  // Phase 1 — personality-driven bidding, marquee first.
  for (const player of order) {
    let bestTeam = -1;
    let bestBid = 0;
    let secondBid = player.base_price;
    for (let i = 0; i < states.length; i++) {
      const st = states[i];
      const arc = ARCH_BY_ID[st.personality] ?? ARCH_BY_ID.Balanced;
      const open = opts.squadSize - filledOf(st);
      if (open <= 0) continue;
      if (player.is_overseas && st.overseas >= opts.overseasCap) continue;
      // reserve enough to fill remaining slots at the floor price
      const spendable = remPurseOf(i) - (open - 1) * MIN_BASE;
      if (spendable < player.base_price) continue;
      const need = st.counts[player.role] < arc.roleMins[player.role] ? 1.5 : 0.7;
      const overseasBias = player.is_overseas ? arc.overseasAppetite * 1.4 : 1;
      const jitter = 1 + (rand() - 0.5) * 2 * arc.risk;
      let wtp = player.projected_value * arc.aggression * need * overseasBias * jitter;
      wtp = Math.min(wtp, spendable);
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
      buy(bestTeam, player, Math.max(player.base_price, Math.min(bestBid, secondBid * 1.02)));
      sold.add(player.cricsheet_id);
    }
  }

  // Phase 2 — must-fill: every team needs ≥ MIN_SQUAD. Hand the cheapest
  // remaining bodies to whoever's shortest, at base price.
  const leftovers = order.filter((p) => !sold.has(p.cricsheet_id)).sort((a, b) => a.base_price - b.base_price);
  for (const player of leftovers) {
    let pick = -1;
    let fewest = Infinity;
    for (let i = 0; i < states.length; i++) {
      if (filledOf(states[i]) >= MIN_SQUAD) continue;
      if (player.is_overseas && states[i].overseas >= opts.overseasCap) continue;
      if (remPurseOf(i) < player.base_price) continue;
      if (filledOf(states[i]) < fewest) {
        fewest = filledOf(states[i]);
        pick = i;
      }
    }
    if (pick >= 0) {
      buy(pick, player, player.base_price);
      sold.add(player.cricsheet_id);
    }
  }
  return states;
}

export function simulateAuction(
  pool: PoolPlayer[],
  teamCfg: { team: string; personality: string }[],
  opts: SimOpts,
): SimResult {
  const { bases, auctionPool } = buildFranchises(pool, teamCfg, opts);
  const usePool = auctionPool.slice(0, 200);
  const agg = bases.map((b) => ({
    team: b.team,
    personality: b.personality,
    retained: b.retained.length,
    retVal: b.retained.reduce((s, p) => s + p.projected_value, 0),
    bought: 0,
    spend: 0,
    value: 0,
    overseas: 0,
  }));
  const marqueeWins = new Map<string, Map<string, number>>();
  const top = usePool.slice(0, 20);
  for (const p of top) marqueeWins.set(p.cricsheet_id, new Map());

  let sampleDraft: TeamState[] = [];
  for (let t = 0; t < opts.trials; t++) {
    const states = oneTrial(bases, usePool, opts, 1000 + t * 7919);
    if (t === Math.floor(opts.trials / 2)) sampleDraft = states;
    states.forEach((st, i) => {
      agg[i].bought += st.bought.length;
      agg[i].spend += st.spent;
      agg[i].value += agg[i].retVal + st.bought.reduce((s, p) => s + p.projected_value, 0);
      agg[i].overseas += st.overseas;
      for (const p of st.bought) {
        const m = marqueeWins.get(p.cricsheet_id);
        if (m) m.set(st.team, (m.get(st.team) ?? 0) + 1);
      }
    });
  }
  const n = opts.trials;
  return {
    mode: opts.mode,
    bases,
    poolSize: auctionPool.length,
    teams: agg.map((a) => ({
      team: a.team,
      personality: a.personality,
      retained: a.retained,
      avgBought: a.bought / n,
      avgSpend: a.spend / n,
      avgValue: a.value / n,
      avgOverseas: a.overseas / n,
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
