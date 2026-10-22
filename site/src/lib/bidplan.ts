// Bid plan: the auction bidding-plan optimiser. EXACT mirror of
// src/cricdex/web_parity/bidplan.py — same constants, same formulas, same order of operations — so
// the page and `cricdex bidplan` show identical numbers (test_scripts/test_bidplan_parity.py runs
// both). The method in plain words: docs/METHODOLOGY.md §12.
//
// 1. Rivals: the Auction room's simulator (auction.ts `oneTrial`) runs the other nine franchises,
//    each with its own Keep-or-release plan and personality, `trials` times → for every player the
//    price we'd have to beat in each run (his base price when no rival bid).
// 2. Squad strength: the best XI's value (≤ 4 overseas, ≥ 1 keeper, 5 bowling and 6 batting
//    options; replacement-level fillers), + a smaller weight on the next four, − a penalty per
//    role need missed.
// 3. The bidding rule: in lot order, bid up to (gain in strength) / λ, within purse, squad and
//    overseas room; λ chosen to maximise the mean strength over the runs; the gain counts the
//    likely buys still to come (a lookahead iterated to a fixed point).
// 4. The plan: each target's max bid = his gain to the likely squad / λ (capped by the purse left
//    after the rest of the likely buys, and the 27 cr record), plus a fallback chain per role.
import {
  IPL_TEAMS_DEFAULT,
  PRICE_CAP,
  auctionLots,
  oneTrial,
  priceCeiling,
  priceTier,
  type FranchiseBase,
  type PoolPlayer,
  type Role,
} from "./auction.ts";
import { cr, evaluate, fmtNum, playerKey, type AssessedPlayer, type Decision, type KeepData, type KeepRules } from "./keep.ts";

// ---- the squad-strength model ----
export const XI_SIZE = 11;
export const XI_OVERSEAS = 4;
export const XI_MIN_KEEPERS = 1;
export const XI_MIN_BOWLING = 5;
export const XI_MIN_BATTING = 6;
/** Replacement level (runs per 100 balls): what a base-price buy is worth. */
export const REPLACEMENT = -15.0;
export const DEPTH_N = 4;
export const DEPTH_WEIGHT = 0.25;
export const NEED_PENALTY = 3.0;
export type Need = "keeper" | "opener" | "death" | "spinner" | "pace";
export const NEED_ORDER: Need[] = ["keeper", "opener", "death", "spinner", "pace"];
export const DEFAULT_NEEDS: Record<Need, number> = { keeper: 2, opener: 3, death: 3, spinner: 3, pace: 4 };
export const NEED_LABEL: Record<Need, string> = {
  keeper: "Wicketkeepers",
  opener: "Openers",
  death: "Death bowlers",
  spinner: "Spinners",
  pace: "Pace bowlers",
};

// ---- the auction assumptions ----
/** Every franchise's plan opens at least this many squad places (the median a team bought at the
 * 2023, 2024 and 2026 mini auctions); 0 = Keep or release's plan exactly. */
export const OPEN_SLOTS = 8;
export const TRIALS = 200;
/** 0.25 × 2^(k/4), k = 0 … 24, written out (identical to bidplan.py). */
export const LAMBDA_GRID = [
  0.25, 0.297302, 0.353553, 0.420448, 0.5, 0.594604, 0.707107, 0.840896, 1.0, 1.189207,
  1.414214, 1.681793, 2.0, 2.378414, 2.828427, 3.363586, 4.0, 4.756828, 5.656854, 6.727171,
  8.0, 9.513657, 11.313708, 13.454343, 16.0,
];
export const MIN_SLOT_PRICE = 0.3;
export const TARGET_MIN_SHARE = 0.05;
export const LIKELY_SHARE = 0.5;
export const LOOKAHEAD_ROUNDS = 4;
export type Slot = "keeper" | "opener" | "death" | "spinner" | "pace" | "batter" | "all_rounder";
export const SLOT_ORDER: Slot[] = ["keeper", "opener", "death", "spinner", "pace", "batter", "all_rounder"];
export const SLOT_LABEL: Record<Slot, string> = {
  keeper: "Wicketkeeper",
  opener: "Opener",
  death: "Death bowler",
  spinner: "Spinner",
  pace: "Pace bowler",
  batter: "Middle-order batter",
  all_rounder: "All-rounder",
};

const fsum = (xs: number[]): number => {
  let t = 0;
  for (const x of xs) t += x;
  return t;
};
const cmpStr = (a: string, b: string) => (a < b ? -1 : a > b ? 1 : 0);

// ---- pieces ----

export interface Piece {
  id: string;
  name: string;
  v: number;
  rated: boolean;
  role: string;
  os: boolean;
  tags: string;
  k: boolean;
  bowl: boolean;
  bat: boolean;
  needs: Need[];
  ub?: number;
  own?: boolean;
}

export function piece(id: string, name: string, value: number | null | undefined, role: string, overseas: boolean, tags: string): Piece {
  const v = value === null || value === undefined ? REPLACEMENT : Number(value);
  const t = tags || "";
  const keeper = role === "keeper" || t.includes("k");
  const bowl = role === "bowler" || role === "all_rounder";
  const flags: [Need, boolean][] = [
    ["keeper", keeper],
    ["opener", t.includes("o")],
    ["death", t.includes("d")],
    ["spinner", t.includes("s")],
    ["pace", bowl && !t.includes("s")],
  ];
  return {
    id,
    name,
    v,
    rated: !(value === null || value === undefined),
    role,
    os: !!overseas,
    tags: t,
    k: keeper,
    bowl,
    bat: role === "batter" || role === "keeper" || role === "all_rounder",
    needs: flags.filter(([, ok]) => ok).map(([n]) => n),
  };
}

const byValue = (a: Piece, b: Piece) => (a.v !== b.v ? (a.v > b.v ? -1 : 1) : cmpStr(a.id, b.id));

export function bestXi(pieces: Piece[]): { xi: number; ids: string[]; fillers: number; bench: Piece[] } {
  const cands = pieces.filter((p) => p.v > REPLACEMENT).sort(byValue);
  const chosen: Piece[] = [];
  const bench: Piece[] = [];
  let k = 0;
  let bw = 0;
  let bt = 0;
  let osN = 0;
  for (const p of cands) {
    if (chosen.length >= XI_SIZE) {
      bench.push(p);
      continue;
    }
    if (p.os && osN >= XI_OVERSEAS) {
      bench.push(p);
      continue;
    }
    const nk = k + (p.k ? 1 : 0);
    const nbw = bw + (p.bowl ? 1 : 0);
    const nbt = bt + (p.bat ? 1 : 0);
    const room = XI_SIZE - chosen.length - 1;
    const needK = Math.max(0, XI_MIN_KEEPERS - nk);
    const needBw = Math.max(0, XI_MIN_BOWLING - nbw);
    const needBt = Math.max(0, XI_MIN_BATTING - nbt);
    if (needBw + Math.max(needK, needBt) > room) {
      bench.push(p);
      continue;
    }
    chosen.push(p);
    k = nk;
    bw = nbw;
    bt = nbt;
    if (p.os) osN++;
  }
  const fillers = XI_SIZE - chosen.length;
  const xi = fsum(chosen.map((p) => p.v)) + fillers * REPLACEMENT;
  return { xi, ids: chosen.map((p) => p.id), fillers, bench };
}

export function needCounts(pieces: Piece[]): Record<Need, number> {
  const out = { keeper: 0, opener: 0, death: 0, spinner: 0, pace: 0 } as Record<Need, number>;
  for (const p of pieces) for (const n of p.needs) out[n] += 1;
  return out;
}

export interface Strength {
  total: number;
  xi: number;
  depth: number;
  short: number;
  counts: Record<Need, number>;
  ids: string[];
  fillers: number;
}

export function strength(pieces: Piece[], needs: Record<Need, number>): Strength {
  const b = bestXi(pieces);
  const depth = fsum(b.bench.slice(0, DEPTH_N).map((p) => p.v - REPLACEMENT));
  const counts = needCounts(pieces);
  let short = 0;
  for (const n of NEED_ORDER) short += Math.max(0, (needs[n] ?? 0) - counts[n]);
  const total = b.xi + DEPTH_WEIGHT * depth - NEED_PENALTY * short;
  return { total, xi: b.xi, depth, short, counts, ids: b.ids, fillers: b.fillers };
}

export const upperGain = (p: Piece) => 2 * Math.max(0, p.v - REPLACEMENT) + NEED_PENALTY * p.needs.length;

// ---- the context ----

export interface Lot {
  cricsheet_id: string;
  name: string;
  role: Role;
  is_overseas: boolean;
  value: number;
  projected_value: number;
  p_bought: number | null;
  base_price: number;
  price_cap: number;
  tags: string;
  from_team: string | null;
  /** his last IPL price (cr), when known: the simulator's reference price */
  anchor_price?: number;
}

export interface Rival {
  team: string;
  personality: string;
  kept: Piece[];
  purse_left: number;
}

export interface BidContext {
  team: string;
  rules: KeepRules;
  cycle: "mega" | "mini";
  open_slots: number;
  squad: AssessedPlayer[];
  kept: Piece[];
  purse_left: number;
  salary_kept: number;
  warnings: string[];
  rivals: Rival[];
  available: Lot[];
  register: boolean;
}

function availRow(
  r: { cricsheet_id: string; name: string; role: Role; is_overseas: boolean; value: number; projected_value: number; p_bought?: number | null; base_price: number; price_cap: number },
  tags: string,
  fromTeam: string | null,
): Lot {
  let t = tags || "";
  if (r.is_overseas && !t.includes("x")) t += "x";
  const out: Lot = {
    cricsheet_id: r.cricsheet_id,
    name: r.name,
    role: r.role,
    is_overseas: !!r.is_overseas,
    value: r.value,
    projected_value: r.projected_value,
    p_bought: r.p_bought ?? null,
    base_price: r.base_price,
    price_cap: r.price_cap,
    tags: t,
    from_team: fromTeam,
  };
  const anchor = (r as { anchor_price?: number | null }).anchor_price;
  if (anchor) out.anchor_price = anchor;
  return out;
}

function squadRowAsLot(p: AssessedPlayer) {
  const price = Number(p.price);
  return {
    cricsheet_id: p.id as string,
    name: p.name,
    role: p.role,
    is_overseas: !!p.overseas,
    value: p.value as number,
    projected_value: price,
    p_bought: p.p_bought ?? null,
    base_price: priceTier(price),
    price_cap: priceCeiling(p.target_balls),
  };
}

const lotOrder = (a: Lot, b: Lot) =>
  a.projected_value !== b.projected_value ? (a.projected_value > b.projected_value ? -1 : 1) : cmpStr(a.cricsheet_id, b.cricsheet_id);

const NO_GAPS = { keeper: 0, opener: 0, death: 0, spinner: 0, overseas: 0 };

/** Open squad places the way franchises do before a mini auction: while more than `limit` players
 * are kept, release the lowest-valued kept player the user hasn't decided on (an unrated one
 * first), marked `auto_release` = "open". Mirror of bidplan.py `open_places`. */
export function openPlaces(players: AssessedPlayer[], limit: number): void {
  const kept = players.filter((p) => p.kept);
  const extra = kept.length - Math.max(0, limit);
  if (extra <= 0) return;
  const key = (p: AssessedPlayer): [number, number] => [p.value === null || p.value === undefined ? 0 : 1, p.value ?? 0];
  const movable = kept
    .filter((p) => !p.overridden)
    .sort((a, b) => {
      const [ra, va] = key(a);
      const [rb, vb] = key(b);
      if (ra !== rb) return ra - rb;
      if (va !== vb) return va < vb ? -1 : 1;
      return cmpStr(a.key, b.key);
    });
  for (const p of movable.slice(0, extra)) {
    p.kept = false;
    p.auto_release = "open";
  }
}

export interface RegisterEntry {
  id: string;
  base_price?: number | null;
}

/** Everything the plan needs, from Keep or release's data (mirror of bidplan.py `build_context`). */
export function buildContext(
  data: KeepData,
  pool: PoolPlayer[],
  team: string,
  decisions: Record<string, Decision> = {},
  purse: number | null = null,
  openSlots: number = OPEN_SLOTS,
  rules: Partial<KeepRules> | null = null,
  register: RegisterEntry[] | null = null,
  personalities: { team: string; personality: string }[] | null = null,
  display: Record<string, string> | null = null,
): BidContext {
  const compRules: KeepRules = { ...data.competition.rules };
  if (rules) for (const [k, v] of Object.entries(rules)) if (v !== null && v !== undefined) (compRules as unknown as Record<string, unknown>)[k] = v;
  if (purse !== null && purse !== undefined) compRules.purse = Number(purse);
  const form = data.form ?? null;
  const pers: Record<string, string> = Object.fromEntries((personalities ?? IPL_TEAMS_DEFAULT).map((c) => [c.team, c.personality]));
  const poolById = new Map(pool.map((r) => [r.cricsheet_id, r]));
  const tagsOf = data.pool_tags ?? {};

  let ours: { players: AssessedPlayer[]; kept: Piece[]; purse_left: number; salary_kept: number; warnings: string[] } | null = null;
  const rivals: Rival[] = [];
  const released: AssessedPlayer[] = [];
  for (const t of data.teams) {
    const squad = data.players.filter((p) => p.team === t);
    // no role targets here: Bid plan has its own needs, so Keep's gap warnings stay out
    const res = evaluate(squad, [], compRules, t === team ? decisions : {}, NO_GAPS, form);
    openPlaces(res.players, Number(compRules.squad_max) - Number(openSlots));
    const kept = res.players.filter((p) => p.kept);
    const salaryKept = fsum(kept.map((p) => Number(p.salary)));
    const pieces = kept.map((p) => piece(p.key, p.name, p.value, p.role, !!p.overseas, p.tags || ""));
    const purseLeft = Number(compRules.purse) - salaryKept;
    for (const p of res.players) if (!p.kept && p.id && p.value !== null && p.value !== undefined) released.push(p);
    if (t === team) ours = { players: res.players, kept: pieces, purse_left: purseLeft, salary_kept: salaryKept, warnings: res.warnings };
    else rivals.push({ team: t, personality: pers[t] ?? "Balanced", kept: pieces, purse_left: purseLeft });
  }
  if (!ours) throw new Error(`unknown team ${team}`);

  const avail: Lot[] = [];
  const seen = new Set<string>();
  if (register) {
    const relById = new Map(released.map((p) => [p.id as string, p]));
    const squadById = new Map(data.players.filter((p) => p.id).map((p) => [p.id as string, p]));
    for (const e of register) {
      const pid = e.id;
      if (seen.has(pid)) continue;
      let row: Lot | null = null;
      const pr = poolById.get(pid);
      if (pr) {
        const src = squadById.get(pid);
        row = availRow(pr, (src ? src.tags : tagsOf[pid] ?? "") || "", src ? src.team : null);
      } else if (relById.has(pid)) {
        const p = relById.get(pid) as AssessedPlayer;
        row = availRow(squadRowAsLot(p), p.tags || "", p.team);
      }
      const sq = squadById.get(pid);
      if (row !== null && sq && sq.salary) row.anchor_price = Number(sq.salary);
      if (row === null) continue;
      if (e.base_price !== null && e.base_price !== undefined) row.base_price = Number(e.base_price);
      seen.add(pid);
      avail.push(row);
    }
  } else {
    for (const r of pool) {
      if (r.team) continue;
      seen.add(r.cricsheet_id);
      avail.push(availRow(r, tagsOf[r.cricsheet_id] ?? "", null));
    }
    for (const p of released) {
      const pid = p.id as string;
      if (seen.has(pid)) continue;
      seen.add(pid);
      const src = poolById.get(pid);
      const row = availRow(src ? src : squadRowAsLot(p), p.tags || "", p.team);
      row.anchor_price = Number(p.salary); // rivals remember what he was paid
      avail.push(row);
    }
  }
  const shown = display ?? {};
  const squadNames = new Map(data.players.filter((p) => p.id).map((p) => [p.id as string, p.name]));
  for (const row of avail) {
    const pid = row.cricsheet_id;
    row.name = (Object.prototype.hasOwnProperty.call(shown, pid) && shown[pid]) || squadNames.get(pid) || row.name;
  }
  avail.sort(lotOrder);
  return {
    team,
    rules: compRules,
    cycle: data.competition.cycle ?? "mini",
    open_slots: Math.trunc(Number(openSlots)),
    squad: ours.players,
    kept: ours.kept,
    purse_left: ours.purse_left,
    salary_kept: ours.salary_kept,
    warnings: ours.warnings,
    rivals,
    available: avail,
    register: register !== null,
  };
}

// ---- step 1: what a rival would pay ----

/** For each available player and each run: the price we'd have to beat (mirror of
 * bidplan.py `rival_prices`). */
export function rivalPrices(ctx: BidContext, trials: number = TRIALS): number[][] {
  const purse = Number(ctx.rules.purse);
  const bases: FranchiseBase[] = ctx.rivals.map((r) => ({
    team: r.team,
    personality: r.personality,
    retained: r.kept.map((p) => ({ cricsheet_id: p.id, role: p.role, is_overseas: p.os }) as unknown as PoolPlayer),
    retainSpend: purse - r.purse_left,
    retainOverseas: r.kept.filter((p) => p.os).length,
  }));
  const avail = ctx.available;
  const index = new Map(avail.map((p, i) => [p.cricsheet_id, i]));
  const lots = auctionLots(avail as unknown as PoolPlayer[]);
  const opts = {
    purse,
    squadSize: Number(ctx.rules.squad_max),
    overseasCap: Number(ctx.rules.overseas_max),
    mode: ctx.cycle ?? "mini", // the calibrated bid level for this auction type
  };
  const out = avail.map((p) => new Array<number>(trials).fill(Number(p.base_price)));
  for (let t = 0; t < trials; t++) {
    oneTrial(bases, lots, opts, 1000 + t * 7919, (player, _team, bestBid) => {
      const i = index.get(player.cricsheet_id) as number;
      const beat = Math.min(PRICE_CAP, player.price_cap, bestBid * 1.02);
      out[i][t] = Math.max(Number(player.base_price), beat);
    });
  }
  return out;
}

// ---- step 2: the bidding rule ----

interface GainState {
  pieces: Piece[];
  total: number;
  g: Map<number, number>;
}

class Gains {
  memo = new Map<string, GainState>();
  kept: Piece[];
  cands: Piece[];
  needs: Record<Need, number>;
  constructor(kept: Piece[], cands: Piece[], needs: Record<Need, number>) {
    this.kept = kept;
    this.cands = cands;
    this.needs = needs;
  }
  state(idx: number[]): GainState {
    const sorted = [...idx].sort((a, b) => a - b);
    const key = sorted.join(",");
    let st = this.memo.get(key);
    if (!st) {
      const pieces = [...this.kept, ...sorted.map((i) => this.cands[i])];
      st = { pieces, total: strength(pieces, this.needs).total, g: new Map() };
      this.memo.set(key, st);
    }
    return st;
  }
  gain(st: GainState, i: number): number {
    let g = st.g.get(i);
    if (g === undefined) {
      g = strength([...st.pieces, this.cands[i]], this.needs).total - st.total;
      st.g.set(i, g);
    }
    return g;
  }
}

interface Run {
  bought: number[];
  paid: number[];
  spend: number;
  total: number;
  st: GainState;
}

function replay(ctx: BidContext, cands: Piece[], prices: number[], lam: number, overrides: Record<string, number>, gains: Gains, future: number[]): Run {
  const sqMax = Number(ctx.rules.squad_max);
  const sqMin = Number(ctx.rules.squad_min);
  const osMax = Number(ctx.rules.overseas_max);
  let n = ctx.kept.length;
  let osN = ctx.kept.filter((p) => p.os).length;
  let left = Number(ctx.purse_left);
  const bought: number[] = [];
  const paid: number[] = [];
  for (let i = 0; i < cands.length; i++) {
    const c = cands[i];
    if (n >= sqMax) break;
    if (c.os && osN >= osMax) continue;
    if (c.own && !Object.prototype.hasOwnProperty.call(overrides, c.id)) continue; // never bought back (see `reconsider`)
    const r = prices[i];
    const reserve = Math.max(0, sqMin - n - 1) * MIN_SLOT_PRICE;
    if (r > left - reserve) continue;
    let cap: number;
    if (Object.prototype.hasOwnProperty.call(overrides, c.id)) cap = overrides[c.id];
    else {
      if ((c.ub as number) < lam * r) continue;
      const ahead = [...bought, ...future.filter((j) => j > i)];
      cap = gains.gain(gains.state(ahead), i) / lam;
    }
    if (cap >= r && cap > 0) {
      bought.push(i);
      paid.push(r);
      left -= r;
      n += 1;
      if (c.os) osN += 1;
    }
  }
  const st = gains.state(bought);
  return { bought, paid, spend: fsum(paid), total: st.total, st };
}

function search(ctx: BidContext, cands: Piece[], byRun: number[][], over: Record<string, number>, gains: Gains, future: number[]): [number, { lam: number; strength: number }[]] {
  const trials = byRun.length;
  let bestLam = LAMBDA_GRID[LAMBDA_GRID.length - 1];
  let bestMean = -Infinity;
  const curve: { lam: number; strength: number }[] = [];
  for (const lam of [...LAMBDA_GRID].reverse()) {
    const tot = fsum(byRun.map((pr) => replay(ctx, cands, pr, lam, over, gains, future).total));
    const mean = trials ? tot / trials : 0;
    curve.push({ lam, strength: mean });
    if (mean > bestMean) {
      bestMean = mean;
      bestLam = lam;
    }
  }
  curve.reverse();
  return [bestLam, curve];
}

function likelyOf(ctx: BidContext, cands: Piece[], land: number[], priceSum: number[], trials: number): number[] {
  const out: number[] = [];
  let nSq = ctx.kept.length;
  let osN = ctx.kept.filter((p) => p.os).length;
  let left = Number(ctx.purse_left);
  for (let i = 0; i < cands.length; i++) {
    const c = cands[i];
    if (trials === 0 || land[i] / trials < LIKELY_SHARE) continue;
    const expPaid = priceSum[i] / land[i];
    if (nSq >= Number(ctx.rules.squad_max) || (c.os && osN >= Number(ctx.rules.overseas_max))) continue;
    if (expPaid > left) continue;
    out.push(i);
    nSq += 1;
    left -= expPaid;
    if (c.os) osN += 1;
  }
  return out;
}

const median = (xs: number[]) => {
  const s = [...xs].sort((a, b) => a - b);
  return s[Math.floor((s.length - 1) / 2)];
};
/** The price that is enough in 9 runs of 10 (90th percentile, nearest rank; bidplan.py `_q90`). */
const q90 = (xs: number[]) => {
  const s = [...xs].sort((a, b) => a - b);
  return s[Math.max(0, Math.ceil(0.9 * s.length) - 1)];
};
const shareLe = (xs: number[], cap: number) => (xs.length ? xs.filter((x) => x <= cap).length / xs.length : 0);

function slotOf(p: Piece): Slot {
  for (const n of ["keeper", "opener", "death", "spinner"] as const) if (p.needs.includes(n)) return n;
  if (p.role === "bowler") return "pace";
  if (p.role === "all_rounder") return "all_rounder";
  return "batter";
}

export interface Target {
  id: string;
  name: string;
  role: string;
  overseas: boolean;
  tags: string;
  value: number;
  price: number;
  p_bought: number | null;
  base_price: number;
  from_team: string | null;
  slot: Slot;
  gain: number;
  max_bid: number;
  purse_bound: boolean;
  override: boolean;
  expected_price: number;
  /** the rivals' price that is enough in 9 runs of 10 */
  enough_90: number;
  p_le_max: number;
  p_land: number;
  avg_paid: number;
  likely: boolean;
  net: number;
  priority: number;
}
export interface ChainStep {
  id: string;
  name: string;
  max_bid: number;
  p_le_max: number;
}
export interface Chain {
  slot: Slot;
  label: string;
  steps: ChainStep[];
}
export interface StrengthSummary {
  total: number;
  xi: number;
  depth: number;
  short: number;
  counts: Record<Need, number>;
  xi_ids: string[];
  fillers: number;
}
export interface BidPlan {
  team: string;
  lam: number;
  curve: { lam: number; strength: number }[];
  rounds: number;
  converged: boolean;
  trials: number;
  needs: Record<Need, number>;
  purse_left: number;
  slots_open: number;
  overseas_open: number;
  targets: Target[];
  chains: Chain[];
  likely: { id: string; name: string; price: number }[];
  likely_spend: number;
  before: StrengthSummary;
  after_likely: StrengthSummary;
  mean_strength: number;
  mean_xi: number;
  mean_spend: number;
  mean_squad: number;
  need_met: Record<Need, number>;
  missing: { need: Need; label: string; target: number; have: number }[];
  /** our releases worth more to the likely squad than their salary (never bought back by the plan) */
  reconsider: { id: string; name: string; salary: number; worth: number; gain: number; auto_release: string | null }[];
}

const summary = (s: Strength): StrengthSummary => ({
  total: s.total,
  xi: s.xi,
  depth: s.depth,
  short: s.short,
  counts: s.counts,
  xi_ids: s.ids,
  fillers: s.fillers,
});

/** The bidding plan for ctx.team (mirror of bidplan.py `plan`). */
export function plan(
  ctx: BidContext,
  needs: Partial<Record<Need, number>> = {},
  overrides: Record<string, number> = {},
  trials: number = TRIALS,
  pricesIn: number[][] | null = null,
): BidPlan {
  const tgt: Record<Need, number> = { ...DEFAULT_NEEDS };
  for (const [k, v] of Object.entries(needs)) {
    if (k in tgt && typeof v === "number" && v >= 0) tgt[k as Need] = Math.trunc(v);
  }
  const over: Record<string, number> = {};
  for (const [k, v] of Object.entries(overrides)) if (v !== null && v !== undefined && v >= 0) over[k] = Number(v);
  const prices = pricesIn ?? rivalPrices(ctx, trials);
  const nTrials = prices.length ? prices[0].length : trials;
  const cands = ctx.available.map((r) => {
    const p = piece(r.cricsheet_id, r.name, r.value, r.role, r.is_overseas, r.tags);
    p.ub = upperGain(p);
    p.own = r.from_team !== null && r.from_team !== undefined && r.from_team === ctx.team;
    return p;
  });
  const gains = new Gains(ctx.kept, cands, tgt);
  const byRun: number[][] = [];
  for (let t = 0; t < nTrials; t++) byRun.push(cands.map((_, i) => prices[i][t]));

  let future: number[] = [];
  let rounds = 0;
  let lam = 0;
  let curve: { lam: number; strength: number }[] = [];
  let land: number[] = [];
  let priceSum: number[] = [];
  let runs: Run[] = [];
  let likely: number[] = [];
  const same = (a: number[], b: number[]) => a.length === b.length && a.every((x, i) => x === b[i]);
  for (;;) {
    rounds += 1;
    [lam, curve] = search(ctx, cands, byRun, over, gains, future);
    land = new Array(cands.length).fill(0);
    priceSum = new Array(cands.length).fill(0);
    runs = [];
    for (let t = 0; t < nTrials; t++) {
      const rr = replay(ctx, cands, byRun[t], lam, over, gains, future);
      runs.push(rr);
      rr.bought.forEach((i, k) => {
        land[i] += 1;
        priceSum[i] += rr.paid[k];
      });
    }
    likely = likelyOf(ctx, cands, land, priceSum, nTrials);
    if (same(likely, future) || rounds >= LOOKAHEAD_ROUNDS) break;
    future = likely;
  }
  const converged = same(likely, future);

  const spends: number[] = [];
  const totals: number[] = [];
  const xis: number[] = [];
  const sizes: number[] = [];
  const needMet = { keeper: 0, opener: 0, death: 0, spinner: 0, pace: 0 } as Record<Need, number>;
  for (const rr of runs) {
    spends.push(rr.spend);
    totals.push(rr.total);
    const s = strength(rr.st.pieces, tgt);
    xis.push(s.xi);
    sizes.push(rr.st.pieces.length);
    for (const n of NEED_ORDER) if (s.counts[n] >= tgt[n]) needMet[n] += 1;
  }

  const sqMax = Number(ctx.rules.squad_max);
  const osMax = Number(ctx.rules.overseas_max);
  const sqMin = Number(ctx.rules.squad_min);
  const likelySet = new Set(likely);
  const likelyPieces = [...ctx.kept, ...likely.map((i) => cands[i])];
  const expPaid = new Map(likely.map((i) => [i, priceSum[i] / land[i]]));

  const gainWithout = (drop: Set<number>, i: number) => {
    const base = [...ctx.kept, ...likely.filter((j) => !drop.has(j)).map((j) => cands[j])];
    return strength([...base, cands[i]], tgt).total - strength(base, tgt).total;
  };
  const maxBid = (drop: Set<number>, i: number): [number, number, boolean] => {
    const g = gainWithout(drop, i);
    const rest = likely.filter((j) => !drop.has(j));
    const reserve = Math.max(0, sqMin - ctx.kept.length - rest.length - 1) * MIN_SLOT_PRICE;
    const budget = Number(ctx.purse_left) - fsum(rest.map((j) => expPaid.get(j) as number)) - reserve;
    const byValue = Math.max(0, g / lam);
    const mb = Math.min(PRICE_CAP, Math.max(0, budget), byValue);
    return [mb, g, mb < byValue];
  };

  const targets: (Target & { i: number })[] = [];
  cands.forEach((c, i) => {
    const share = nTrials ? land[i] / nTrials : 0;
    const has = Object.prototype.hasOwnProperty.call(over, c.id);
    if (share < TARGET_MIN_SHARE && !(has && over[c.id] > 0)) return;
    let [mb, g, bound] = maxBid(new Set([i]), i);
    if (has) {
      mb = over[c.id];
      bound = false;
    }
    const ps = prices[i];
    const under = ps.filter((x) => x <= mb);
    const pLe = nTrials ? under.length / nTrials : 0;
    const meanUnder = under.length ? fsum(under) / under.length : 0;
    const a = ctx.available[i];
    targets.push({
      i,
      id: c.id,
      name: c.name,
      role: c.role,
      overseas: c.os,
      tags: c.tags,
      value: a.value,
      price: a.projected_value,
      p_bought: a.p_bought ?? null,
      base_price: a.base_price,
      from_team: a.from_team ?? null,
      slot: slotOf(c),
      gain: g,
      max_bid: mb,
      purse_bound: bound,
      override: has,
      expected_price: median(ps),
      enough_90: q90(ps),
      p_le_max: pLe,
      p_land: share,
      avg_paid: land[i] ? priceSum[i] / land[i] : 0,
      likely: likelySet.has(i),
      net: pLe * (g - lam * meanUnder),
      priority: 0,
    });
  });
  targets.sort((a, b) => (a.net !== b.net ? (a.net > b.net ? -1 : 1) : cmpStr(a.id, b.id)));
  targets.forEach((x, k) => (x.priority = k + 1));

  const chains: Chain[] = [];
  for (const slot of SLOT_ORDER) {
    const members = targets.filter((x) => x.slot === slot);
    if (!members.length) continue;
    const steps: ChainStep[] = [];
    const lost = new Set<number>();
    for (const x of members) {
      lost.add(x.i);
      const cap = x.override ? x.max_bid : maxBid(lost, x.i)[0];
      steps.push({ id: x.id, name: x.name, max_bid: cap, p_le_max: shareLe(prices[x.i], cap) });
    }
    chains.push({ slot, label: SLOT_LABEL[slot], steps });
  }

  const salaryOf = new Map(ctx.squad.filter((p) => p.id).map((p) => [p.id as string, p]));
  const reconsider: BidPlan["reconsider"] = [];
  cands.forEach((c, i) => {
    if (!c.own || !salaryOf.has(c.id) || !c.rated) return;
    const g = gainWithout(new Set([i]), i);
    const worth = Math.min(PRICE_CAP, Math.max(0, g / lam));
    const sq = salaryOf.get(c.id) as AssessedPlayer;
    const sal = Number(sq.salary);
    if (worth >= sal) reconsider.push({ id: c.id, name: sq.name, salary: sal, worth, gain: g, auto_release: sq.auto_release ?? null });
  });
  reconsider.sort((a, b) => {
    const da = a.worth - a.salary;
    const db = b.worth - b.salary;
    return da !== db ? (da > db ? -1 : 1) : cmpStr(a.id, b.id);
  });

  const before = strength(ctx.kept, tgt);
  const after = strength(likelyPieces, tgt);
  const missing: BidPlan["missing"] = [];
  for (const n of NEED_ORDER) {
    const have = after.counts[n];
    if (have < tgt[n]) missing.push({ need: n, label: NEED_LABEL[n], target: tgt[n], have });
  }
  const outTargets: Target[] = targets.map(({ i: _i, ...rest }) => rest);
  return {
    team: ctx.team,
    lam,
    curve,
    rounds,
    converged,
    trials: nTrials,
    needs: tgt,
    purse_left: ctx.purse_left,
    slots_open: sqMax - ctx.kept.length,
    overseas_open: osMax - ctx.kept.filter((p) => p.os).length,
    targets: outTargets,
    chains,
    likely: likely.map((i) => ({ id: cands[i].id, name: cands[i].name, price: priceSum[i] / land[i] })),
    likely_spend: fsum(likely.map((i) => priceSum[i] / land[i])),
    before: summary(before),
    after_likely: summary(after),
    mean_strength: nTrials ? fsum(totals) / nTrials : before.total,
    mean_xi: nTrials ? fsum(xis) / nTrials : before.xi,
    mean_spend: nTrials ? fsum(spends) / nTrials : 0,
    mean_squad: nTrials ? fsum(sizes) / nTrials : ctx.kept.length,
    need_met: Object.fromEntries(NEED_ORDER.map((n) => [n, nTrials ? needMet[n] / nTrials : 0])) as Record<Need, number>,
    missing,
    reconsider,
  };
}

// ---- output helpers ----

/** "Phil Salt up to 14 cr → if Phil Salt goes above that: Ryan Rickelton up to 8 cr → …". */
export function chainText(chain: Chain): string {
  return chain.steps
    .map((s, k) =>
      k === 0 ? `${s.name} up to ${cr(s.max_bid)} cr` : `if ${chain.steps[k - 1].name} goes above that: ${s.name} up to ${cr(s.max_bid)} cr`,
    )
    .join(" → ");
}

/** The targets table as CSV rows (same columns as bidplan.py `to_csv_rows`). */
export function toCsvRows(res: BidPlan): string[][] {
  const head = [
    "priority", "player", "role", "slot", "overseas", "from_team", "value", "market_price_cr",
    "p_bought", "expected_price_cr", "enough_90_cr", "max_bid_cr", "your_max_bid", "p_land_at_max_bid",
    "p_land_in_plan", "gain_runs", "likely",
  ];
  const rows = [head];
  for (const x of res.targets) {
    rows.push([
      String(x.priority),
      x.name,
      x.role,
      SLOT_LABEL[x.slot],
      x.overseas ? "yes" : "no",
      x.from_team ?? "",
      fmtNum(x.value, 1),
      fmtNum(x.price, 2),
      x.p_bought === null || x.p_bought === undefined ? "" : fmtNum(x.p_bought, 2),
      fmtNum(x.expected_price, 2),
      fmtNum(x.enough_90, 2),
      fmtNum(x.max_bid, 2),
      x.override ? "yes" : "no",
      fmtNum(x.p_le_max, 2),
      fmtNum(x.p_land, 2),
      fmtNum(x.gain, 1),
      x.likely ? "yes" : "no",
    ]);
  }
  return rows;
}

export { playerKey };
