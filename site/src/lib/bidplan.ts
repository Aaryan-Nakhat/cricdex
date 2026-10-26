// Bid plan: the auction bidding-plan optimiser. EXACT mirror of
// src/cricdex/web_parity/bidplan.py — same constants, same formulas, same order of operations — so
// the page and `cricdex bidplan` show identical numbers (test_scripts/test_bidplan_parity.py runs
// both). The method in plain words: docs/METHODOLOGY.md §12.
//
// 1. Rivals: the Auction room's simulator (auction.ts `oneTrial`) runs the other nine franchises,
//    each with its own Keep-or-release plan, bidding by the room's fitted demand model, `trials`
//    times → for every player the price we'd have to beat in each run (the next ladder step above
//    the winning rival's bid; his base price when no rival bid).
// 2. Squad strength: the best XI's expected contribution in runs per match above replacement (batting
//    and bowling at each player's balls a match × P(plays), the XI's balls held to a side's innings;
//    ≤ 4 overseas, ≥ 1 keeper, 5 bowling and 6 batting options; replacement-level fillers), + the
//    bench filling the matches the XI misses (Σ (1 − P(plays)), best bench contribution first). Role
//    needs are reported, not scored.
// 3. The bidding rule: in lot order, bid up to (gain in strength) / λ, within purse, squad and
//    overseas room; λ chosen to maximise the mean strength over the runs; the gain counts the
//    likely buys still to come (a lookahead iterated to a fixed point).
// 4. The plan: each target's max bid = his gain to the likely squad / λ (capped by the purse left
//    after the rest of the likely buys), plus a fallback chain per role.
import {
  auctionLots,
  ladderNext,
  oneTrial,
  openSquadPlaces,
  rng,
  type Demand,
  priceTier,
  type FranchiseBase,
  type PoolPlayer,
  type Role,
} from "./auction.ts";
import { cr, evaluate, fmtNum, playerKey, purseCharged, type AssessedPlayer, type Decision, type KeepData, type KeepRules } from "./keep.ts";

// ---- the squad-strength model ----
export const XI_SIZE = 11;
export const XI_OVERSEAS = 4;
export const XI_MIN_KEEPERS = 1;
export const XI_MIN_BOWLING = 5;
export const XI_MIN_BATTING = 6;
/** Replacement level: contributions are runs per match above replacement (playing_time.py), so a
 * place the squad can't fill adds 0 and a player at or below 0 never plays. */
export const REPLACEMENT = 0.0;
/** A side's legal balls per innings (playing_time_model.json, IPL 2023-2026): an XI's expected balls
 * faced (bowled) beyond it are scaled down to it, every member alike. */
export const TEAM_BALLS = 115.0;
// Depth: an XI member counts P(plays) × his contribution; the XI's missed appearances, Σ (1 − P), go to
// the bench, best contribution a match first, at most one appearance a match each (bidplan.py
// `bench_fill`). Role needs are targets the plan reports against; they don't cost strength.
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
/** 0.05 × 2^(k/4), k = 0 … 24 (runs per match per crore), written out (identical to bidplan.py). */
export const LAMBDA_GRID = [
  0.05, 0.05946, 0.070711, 0.08409, 0.1, 0.118921, 0.141421, 0.168179, 0.2, 0.237841,
  0.282843, 0.336359, 0.4, 0.475683, 0.565685, 0.672717, 0.8, 0.951366, 1.13137, 1.34543,
  1.6, 1.90273, 2.26274, 2.69087, 3.2,
];
export const MIN_SLOT_PRICE = 0.3;
/** How a crore left unspent is valued (bidplan.py MONEY_RULES): "auction" = what it can still buy
 * from the later lots at their expected prices (`MoneyValue`), 0 at the end of the auction;
 * "market" = the rivals' runs per crore; "none" = nothing (one λ for the whole auction). */
export type MoneyRule = "auction" | "market" | "none";
export const MONEY: MoneyRule = "auction";
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
  /** P(plays) and the contribution a match he plays (v ÷ P): the bench fill */
  pp: number;
  c: number;
  /** the most bench appearances a match he can give: 1 for a squad player, an auction candidate's
   * P(plays) (set in `cands`; bidplan.py `piece` / `bench_fill`) */
  cap: number;
  /** the batting and bowling parts of v and the balls they come from (a match) */
  cb: number;
  cw: number;
  fb: number;
  wb: number;
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

/** The playing-time fields a lot or squad row carries (export_site PT_KEYS). */
export interface ContribFields {
  contrib?: number | null;
  contrib_bat?: number | null;
  contrib_bowl?: number | null;
  balls_faced?: number | null;
  balls_bowled?: number | null;
  p_play?: number | null;
}
export type Parts = number[];

/** [batting part, bowling part, balls faced, balls bowled, P(plays)] of a row's contribution (a
 * missing P(plays) counts as 1); null when any of the first four is missing. Mirror of bidplan.py
 * `contrib_parts`. */
export function contribParts(r: ContribFields): Parts | null {
  const ks = [r.contrib_bat, r.contrib_bowl, r.balls_faced, r.balls_bowled];
  if (ks.some((x) => x === null || x === undefined)) return null;
  const p = r.p_play === null || r.p_play === undefined ? 1.0 : Number(r.p_play);
  return [...ks.map(Number), p];
}

export function piece(
  id: string,
  name: string,
  contrib: number | null | undefined,
  role: string,
  overseas: boolean,
  tags: string,
  parts: Parts | null = null,
): Piece {
  const rated = !(contrib === null || contrib === undefined);
  let v = rated ? Number(contrib) : REPLACEMENT;
  let cb = v;
  let cw = 0;
  let fb = 0;
  let wb = 0;
  let pp = 1.0;
  if (parts !== null && rated) {
    // expected contribution: every part and ball × P(plays) (mirror of bidplan.py `piece`)
    pp = parts.length > 4 ? parts[4] : 1.0;
    cb = pp * parts[0];
    cw = pp * parts[1];
    fb = pp * parts[2];
    wb = pp * parts[3];
    v = cb + cw;
  }
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
    pp,
    c: pp > 0 ? v / pp : 0.0,
    cap: 1.0,
    cb,
    cw,
    fb,
    wb,
    rated,
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
  const faced = fsum(chosen.map((p) => p.fb));
  const bowled = fsum(chosen.map((p) => p.wb));
  const sb = faced > TEAM_BALLS ? TEAM_BALLS / faced : 1.0;
  const sw = bowled > TEAM_BALLS ? TEAM_BALLS / bowled : 1.0;
  let xi = sb * fsum(chosen.map((p) => p.cb)) + sw * fsum(chosen.map((p) => p.cw));
  xi += fillers * REPLACEMENT;
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

/** The bench's expected runs a match: the XI's missed appearances (Σ 1 − P(plays)) filled by the bench,
 * best contribution a match first, at most `cap` appearances a match each (1 for a squad player, an
 * auction candidate's P(plays)). Mirror of bidplan.py `bench_fill`. */
export function benchFill(xiIds: string[], pieces: Piece[], bench: Piece[]): number {
  const ids = new Set(xiIds);
  let miss = fsum(pieces.filter((p) => ids.has(p.id)).map((p) => 1.0 - Math.min(1.0, Math.max(0.0, p.pp))));
  let out = 0.0;
  const order = bench.filter((q) => q.c > REPLACEMENT).sort((a, b) => (a.c !== b.c ? (a.c > b.c ? -1 : 1) : cmpStr(a.id, b.id)));
  for (const p of order) {
    if (miss <= 0.0) break;
    const cap = Math.min(1.0, Math.max(0.0, p.cap ?? 1.0)); // a piece without one is a squad player
    const a = miss < cap ? miss : cap;
    out += a * p.c;
    miss -= a;
  }
  return out;
}

export function strength(pieces: Piece[], needs: Record<Need, number>): Strength {
  const b = bestXi(pieces);
  const depth = benchFill(b.ids, pieces, b.bench);
  const counts = needCounts(pieces);
  let short = 0;
  for (const n of NEED_ORDER) short += Math.max(0, (needs[n] ?? 0) - counts[n]);
  const total = b.xi + depth;
  return { total, xi: b.xi, depth, short, counts, ids: b.ids, fillers: b.fillers };
}

export const upperGain = (p: Piece) => 2 * Math.max(0, p.c - REPLACEMENT);

// ---- the context ----

export interface Lot extends ContribFields {
  cricsheet_id: string;
  name: string;
  role: Role;
  is_overseas: boolean;
  value: number;
  projected_value: number;
  p_bought: number | null;
  base_price: number;
  tags: string;
  from_team: string | null;
  /** his last IPL price (cr), when known: the simulator's reference price */
  anchor_price?: number;
  /** his last IPL price as a share of that season's purse (the reference price when no anchor) */
  prior_share?: number | null;
  /** the set he comes up in (capped first; absent = capped) */
  capped?: boolean | null;
  /** the buy model's inputs besides the squad (bidplan.py BUY_META_KEYS) */
  age?: number | null;
  ipl_matches?: number | null;
  last_share?: number | null;
  captain_ipl_last?: number | boolean | null;
}

/** P(plays) of an auction buy in the squad that bought him (keep.json `buy_model`). */
export interface BuyModel {
  intercept: number;
  coef: Record<string, number>;
  season: number | null;
}

export interface Rival {
  team: string;
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
  /** replays only: every available player is a lot; the demand model and the lowest base price of that auction */
  all_lots?: boolean;
  demand?: Partial<Demand> | null;
  min_base?: number | null;
  /** P(plays) of a buy in the squad that bought him; null = the lots keep their free-agent P(plays) */
  buy_model?: BuyModel | null;
  /** the other franchises' own plans: {team: {player id: [max bid, share of runs his plan lands him]}} */
  rival_bids?: RivalBids;
}

export type RivalBids = Record<string, Record<string, [number, number]>>;

type BuyMeta = { age?: number | null; ipl_matches?: number | null; last_share?: number | null; captain_ipl_last?: number | boolean | null };
const buyMeta = (r: BuyMeta) => ({
  age: r.age ?? null,
  ipl_matches: r.ipl_matches ?? null,
  last_share: r.last_share ?? null,
  captain_ipl_last: r.captain_ipl_last ?? null,
});

function availRow(
  r: { cricsheet_id: string; name: string; role: Role; is_overseas: boolean; value: number; projected_value: number; p_bought?: number | null; base_price: number; capped?: boolean | null; prior_share?: number | null } & ContribFields & BuyMeta,
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
    tags: t,
    from_team: fromTeam,
    contrib: r.contrib ?? null,
    contrib_bat: r.contrib_bat ?? null,
    contrib_bowl: r.contrib_bowl ?? null,
    balls_faced: r.balls_faced ?? null,
    balls_bowled: r.balls_bowled ?? null,
    p_play: r.p_play ?? null,
    ...buyMeta(r),
  };
  const anchor = (r as { anchor_price?: number | null }).anchor_price;
  if (anchor) out.anchor_price = anchor;
  if (r.capped !== null && r.capped !== undefined) out.capped = r.capped;
  if (r.prior_share) out.prior_share = r.prior_share;
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
    contrib: p.contrib ?? null,
    contrib_bat: p.contrib_bat ?? null,
    contrib_bowl: p.contrib_bowl ?? null,
    balls_faced: p.balls_faced ?? null,
    balls_bowled: p.balls_bowled ?? null,
    p_play: p.p_play ?? null,
    ...buyMeta(p as unknown as BuyMeta),
  };
}

const lotOrder = (a: Lot, b: Lot) =>
  a.projected_value !== b.projected_value ? (a.projected_value > b.projected_value ? -1 : 1) : cmpStr(a.cricsheet_id, b.cricsheet_id);

const NO_GAPS = { keeper: 0, opener: 0, death: 0, spinner: 0, overseas: 0 };

/** Open squad places the way franchises do before a mini auction: while more than `limit` players
 * are kept, release the kept player with the lowest contribution per match the user hasn't decided
 * on (an unrated one first), marked `auto_release` = "open". Mirror of bidplan.py `open_places`. */
export function openPlaces(players: AssessedPlayer[], limit: number): void {
  const kept = players.filter((p) => p.kept);
  const extra = kept.length - Math.max(0, limit);
  if (extra <= 0) return;
  const key = (p: AssessedPlayer): [number, number] => [p.contrib === null || p.contrib === undefined ? 0 : 1, p.contrib ?? 0];
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
  display: Record<string, string> | null = null,
  rivalBids: RivalBids | null = null,
): BidContext {
  const compRules: KeepRules = { ...data.competition.rules };
  if (rules) for (const [k, v] of Object.entries(rules)) if (v !== null && v !== undefined) (compRules as unknown as Record<string, unknown>)[k] = v;
  if (purse !== null && purse !== undefined) compRules.purse = Number(purse);
  const form = data.form ?? null;
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
    const pieces = kept.map((p) => piece(p.key, p.name, p.contrib, p.role, !!p.overseas, p.tags || "", contribParts(p)));
    // what the kept players cost the purse (salaries; 2025 retentions by the retention slabs)
    const purseLeft = Number(compRules.purse) - purseCharged(kept, compRules);
    for (const p of res.players) if (!p.kept && p.id && p.value !== null && p.value !== undefined) released.push(p);
    if (t === team) ours = { players: res.players, kept: pieces, purse_left: purseLeft, salary_kept: salaryKept, warnings: res.warnings };
    else rivals.push({ team: t, kept: pieces, purse_left: purseLeft });
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
  // a squad player in the auction is a free agent there: the free-agent model's P(plays)
  const freeP = new Map(data.players.filter((p) => p.id).map((p) => [p.id as string, p.p_play_free]));
  for (const row of avail) {
    const fp = freeP.get(row.cricsheet_id);
    if (fp !== null && fp !== undefined) row.p_play = fp;
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
    buy_model: (data as unknown as { buy_model?: BuyModel | null }).buy_model ?? null,
    rival_bids: Object.fromEntries(Object.entries(rivalBids ?? {}).filter(([t]) => t !== team)),
  };
}

// ---- step 1: what a rival would pay ----

/** For each available player and each run: the price we'd have to beat (mirror of
 * bidplan.py `rival_prices`). */
export function rivalPrices(ctx: BidContext, trials: number = TRIALS): number[][] {
  return rivalRuns(ctx, trials).prices;
}

export interface RivalRuns {
  prices: number[][];
  /** the market's runs per crore: Σ strength the rivals' buys added to their squads ÷ Σ they paid;
   * the value of a crore we leave unspent (bidplan.py `rival_runs`) */
  rate: number;
  rival_gain: number;
  rival_spend: number;
}

/** The rivals' auction, `trials` times: the prices to beat and the market's runs per crore (mirror
 * of bidplan.py `rival_runs`). */
export function rivalRuns(ctx: BidContext, trials: number = TRIALS): RivalRuns {
  const purse = Number(ctx.rules.purse);
  const sqMax = Math.trunc(Number(ctx.rules.squad_max));
  const bases: FranchiseBase[] = ctx.rivals.map((r) => ({
    team: r.team,
    retained: r.kept.map((p) => ({ cricsheet_id: p.id, role: p.role, is_overseas: p.os, v: p.v }) as unknown as PoolPlayer),
    retainSpend: purse - r.purse_left,
    retainOverseas: r.kept.filter((p) => p.os).length,
  }));
  const avail = ctx.available;
  const index = new Map(avail.map((p, i) => [p.cricsheet_id, i]));
  const cycle = ctx.cycle ?? "mini";
  // the lots: as many as real shortlists hold for the auction's open places (ours included)
  const places = openSquadPlaces(bases, sqMax) + Math.max(0, sqMax - ctx.kept.length);
  const lots = ctx.all_lots ? (avail as unknown as PoolPlayer[]) : auctionLots(avail as unknown as PoolPlayer[], places, cycle);
  const opts = {
    purse,
    squadSize: sqMax,
    squadMin: Math.trunc(Number(ctx.rules.squad_min ?? 18)),
    overseasCap: Math.trunc(Number(ctx.rules.overseas_max)),
    mode: cycle,
    ...(ctx.demand ? { demand: ctx.demand } : {}),
    ...(ctx.min_base ? { minBase: Number(ctx.min_base) } : {}),
  };
  const out = avail.map((p) => new Array<number>(trials).fill(Number(p.base_price)));
  const lotPieces = candsOf(ctx);
  const baseTotal = ctx.rivals.map((r) => strength(r.kept, DEFAULT_NEEDS).total);
  let gainSum = 0;
  let spendSum = 0;
  for (let t = 0; t < trials; t++) {
    const buys: number[][] = bases.map(() => []);
    const paid: number[][] = bases.map(() => []);
    const onSaleT = (player: PoolPlayer, team: number, bestBid: number, price: number) => {
      const i = index.get(player.cricsheet_id) as number;
      const beat = ladderNext(bestBid);
      out[i][t] = Math.max(Number(player.base_price), beat);
      buys[team].push(i);
      paid[team].push(Number(price));
    };
    oneTrial(bases, lots, opts, 1000 + t * 7919, onSaleT);
    applyRivalPlans(ctx, avail, out, t);
    ctx.rivals.forEach((r, k) => {
      if (!buys[k].length) return;
      const after = strength([...r.kept, ...buys[k].map((i) => lotPieces[i])], DEFAULT_NEEDS).total;
      gainSum += after - baseTotal[k];
      spendSum += fsum(paid[k]);
    });
  }
  const rate = spendSum > 0 ? gainSum / spendSum : 0;
  return { prices: out, rate, rival_gain: gainSum, rival_spend: spendSum };
}

// ---- P(plays) of a buy, in the squad that bought him (bidplan.py, ROADMAP I18) ----
const PT_XI_SIZE = 11;
const PT_XI_OVERSEAS = 4;
interface Member {
  cid: string;
  c: number;
  os: number;
  k: number;
  bowl: number;
  bat: number;
}

/** playing_time.projected_xi (bidplan.py `projected_xi`). */
export function projectedXi(squad: Member[]): Map<string, { in_xi: boolean; margin: number; rank: number; os_rank: number }> {
  const order = [...squad].sort((a, b) => (a.c !== b.c ? (a.c > b.c ? -1 : 1) : cmpStr(a.cid, b.cid)));
  const chosen: Member[] = [];
  const outList: Member[] = [];
  let k = 0;
  let bw = 0;
  let bt = 0;
  let osN = 0;
  for (const p of order) {
    if (chosen.length >= PT_XI_SIZE || (p.os && osN >= PT_XI_OVERSEAS)) {
      outList.push(p);
      continue;
    }
    const nk = k + p.k;
    const nbw = bw + p.bowl;
    const nbt = bt + p.bat;
    const room = PT_XI_SIZE - chosen.length - 1;
    if (Math.max(0, 5 - nbw) + Math.max(Math.max(0, 1 - nk), Math.max(0, 6 - nbt)) > room) {
      outList.push(p);
      continue;
    }
    chosen.push(p);
    k = nk;
    bw = nbw;
    bt = nbt;
    osN += p.os;
  }
  let lastIn = 0;
  if (chosen.length) {
    lastIn = chosen[0].c;
    for (const p of chosen) if (p.c < lastIn) lastIn = p.c;
  }
  let firstOut = lastIn;
  if (outList.length) {
    firstOut = outList[0].c;
    for (const p of outList) if (p.c > firstOut) firstOut = p.c;
  }
  const line = 0.5 * (lastIn + firstOut);
  const ids = new Set(chosen.map((p) => p.cid));
  const res = new Map<string, { in_xi: boolean; margin: number; rank: number; os_rank: number }>();
  let osRank = 0;
  order.forEach((p, i) => {
    if (p.os) osRank += 1;
    res.set(p.cid, { in_xi: ids.has(p.cid), margin: p.c - line, rank: i + 1, os_rank: p.os ? osRank : 0 });
  });
  return res;
}

/** playing_time.play_features (bidplan.py `play_features`). */
export function playFeatures(r: {
  contrib: number; in_xi: boolean; margin: number; rank: number; overseas: boolean; os_rank: number;
  age: number | null; ipl_matches: number | null; last_share: number | null; keeper: boolean; captain: boolean; season: number | null;
}): Record<string, number> {
  const a = r.age !== null && r.age !== undefined ? r.age - 28.0 : 0.0;
  const m = Math.max(-6.0, Math.min(6.0, r.margin));
  const ov = r.overseas ? 1.0 : 0.0;
  const ls = r.last_share;
  return {
    contrib: Math.max(-6.0, Math.min(12.0, r.contrib)),
    in_xi: r.in_xi ? 1.0 : 0.0,
    margin: m,
    rank_log: Math.log(Math.max(r.rank, 1)),
    overseas: ov,
    os_out: ov * (r.os_rank > PT_XI_OVERSEAS ? 1.0 : 0.0),
    os_rank_gt4: ov * Math.max(0.0, r.os_rank - PT_XI_OVERSEAS),
    ipl_exp: Math.log1p(Math.max(r.ipl_matches || 0.0, 0.0)),
    never_ipl: !r.ipl_matches ? 1.0 : 0.0,
    age: a / 5.0,
    age_gt32: Math.max(0.0, a - 4.0) / 5.0,
    last_share: ls !== null && ls !== undefined ? ls : 0.0,
    no_last: ls !== null && ls !== undefined ? 0.0 : 1.0,
    keeper: r.keeper ? 1.0 : 0.0,
    captain: r.captain ? 1.0 : 0.0,
    impact_era: (r.season || 0) >= 2023 ? 1.0 : 0.0,
  };
}

const memberOf = (pc: Piece): Member => ({ cid: pc.id, c: pc.c, os: pc.os ? 1 : 0, k: pc.k ? 1 : 0, bowl: pc.bowl ? 1 : 0, bat: pc.bat ? 1 : 0 });

/** P(plays) for a lot once this team has bought him at `price` (bidplan.py `buy_p`). */
export function buyP(row: Lot, squad: Piece[], model: BuyModel, price: number, purse: number): number {
  const me: Member = {
    cid: row.cricsheet_id,
    c: Number(row.contrib),
    os: row.is_overseas ? 1 : 0,
    k: row.role === "keeper" ? 1 : 0,
    bowl: row.role === "bowler" || row.role === "all_rounder" ? 1 : 0,
    bat: row.role === "batter" || row.role === "keeper" || row.role === "all_rounder" ? 1 : 0,
  };
  const sq = [...squad.filter((pc) => pc.id !== me.cid).map(memberOf), me];
  const x = projectedXi(sq).get(me.cid) as { in_xi: boolean; margin: number; rank: number; os_rank: number };
  const f = playFeatures({
    contrib: me.c, in_xi: x.in_xi, margin: x.margin, rank: x.rank, os_rank: x.os_rank, overseas: !!row.is_overseas,
    age: row.age ?? null, ipl_matches: row.ipl_matches ?? null, last_share: row.last_share ?? null,
    keeper: row.role === "keeper", captain: !!row.captain_ipl_last, season: model.season ?? null,
  });
  f.price_share = Math.log(Math.max(price, 1e-6) / Math.max(purse, 1e-6));
  let t = Number(model.intercept);
  for (const [k, c] of Object.entries(model.coef)) t += Number(c) * f[k];
  return 1.0 / (1.0 + Math.exp(-Math.max(-30.0, Math.min(30.0, t))));
}

/** Each lot's P(plays) if this team buys him at his expected price; null without a buy model
 * (bidplan.py `lot_p`). */
export function lotP(ctx: BidContext, expected: number[]): (number | null)[] | null {
  const bm = ctx.buy_model;
  if (!bm) return null;
  const purse = Number(ctx.rules.purse);
  return ctx.available.map((r, i) => (r.contrib !== null && r.contrib !== undefined ? buyP(r, ctx.kept, bm, expected[i], purse) : null));
}

const RIVAL_PLAN_SEED = 50021;

/** The other franchises' own plans in run t (bidplan.py `_apply_rival_plans`): in the share of runs
 * his plan lands him, a rival chases each target up to his max bid. */
function applyRivalPlans(ctx: BidContext, avail: Lot[], out: number[][], t: number): void {
  const rb = ctx.rival_bids ?? {};
  if (!Object.keys(rb).length) return;
  const rand = rng(RIVAL_PLAN_SEED + t * 7919);
  for (const r of ctx.rivals) {
    const bids = rb[r.team];
    if (!bids || !Object.keys(bids).length) continue;
    avail.forEach((p, i) => {
      const b = bids[p.cricsheet_id];
      if (!b) return;
      if (rand() < Number(b[1])) {
        const beat = Math.max(Number(p.base_price), ladderNext(Number(b[0])));
        if (beat > out[i][t]) out[i][t] = beat;
      }
    });
  }
}

/** The auction candidates as strength pieces (bidplan.py `_cands`); `pp` = each lot's P(plays) if bought. */
function candsOf(ctx: BidContext, pp: (number | null)[] | null = null): Piece[] {
  return ctx.available.map((r, i) => {
    let parts = contribParts(r);
    if (parts !== null && pp !== null && pp[i] !== null) parts = [...parts.slice(0, 4), pp[i] as number];
    const p = piece(r.cricsheet_id, r.name, r.contrib, r.role, r.is_overseas, r.tags, parts);
    // a candidate gives the bench at most his P(plays) appearances a match (`benchFill`)
    p.cap = p.pp;
    p.ub = upperGain(p);
    p.own = r.from_team !== null && r.from_team !== undefined && r.from_team === ctx.team;
    return p;
  });
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

/** What a crore and a squad place are still worth at each lot: the later lots ranked by gain on
 * the likely squad ÷ expected price, filled within the money and places left. Money runs out first:
 * λ = the ratio of the first lot it no longer covers, a place costs nothing. Places run out first:
 * λ = 0, a place is worth the smallest gain among the lots that fill them. Neither: both 0
 * (mirror of bidplan.py `_MoneyValue`). */
class MoneyValue {
  items: [number, number, number, number][] = [];
  suffix = new Map<number, [number[], number[], number[]]>();
  constructor(cands: Piece[], gains: Gains, future: number[], expected: number[]) {
    const base = gains.state(future);
    const fut = new Set(future);
    cands.forEach((c, j) => {
      if (c.own || (c.ub as number) <= 0 || expected[j] <= 0) return;
      const g = fut.has(j) ? gains.gain(gains.state(future.filter((k) => k !== j)), j) : gains.gain(base, j);
      if (g > 0) this.items.push([g / expected[j], j, expected[j], g]);
    });
    this.items.sort((a, b) => (a[0] !== b[0] ? (a[0] > b[0] ? -1 : 1) : a[1] - b[1]));
  }
  suf(i: number): [number[], number[], number[]] {
    let got = this.suffix.get(i);
    if (!got) {
      const cum: number[] = [];
      const rat: number[] = [];
      const gmin: number[] = [];
      let t = 0;
      let m = Infinity;
      for (const [r, j, e, g] of this.items) {
        if (j > i) {
          t += e;
          m = m < g ? m : g;
          cum.push(t);
          rat.push(r);
          gmin.push(m);
        }
      }
      got = [cum, rat, gmin];
      this.suffix.set(i, got);
    }
    return got;
  }
  /** [λ, slot] after lot i given `money` crores and `room` places (bidplan.py `value`). */
  value(i: number, money: number, room: number, skip: Set<number> | null = null): [number, number] {
    if (skip && skip.size) {
      if (room <= 0) return [0, 0];
      let t = 0;
      let k = 0;
      let m = Infinity;
      for (const [r, j, e, g] of this.items) {
        if (j <= i || skip.has(j)) continue;
        if (t + e > money + 1e-9) return [r, 0];
        t += e;
        k += 1;
        m = m < g ? m : g;
        if (k >= room) return [0, m];
      }
      return [0, 0];
    }
    if (room <= 0) return [0, 0];
    const [cum, rat, gmin] = this.suf(i);
    // bisect_right(cum, money + 1e-9)
    let lo = 0;
    let hi = cum.length;
    const x = money + 1e-9;
    while (lo < hi) {
      const mid = (lo + hi) >> 1;
      if (x < cum[mid]) hi = mid;
      else lo = mid + 1;
    }
    if (lo >= room && room <= cum.length) return [0, gmin[room - 1]];
    if (lo < cum.length) return [rat[lo], 0];
    return [0, 0];
  }
}

/** (gain − a place's worth) ÷ a crore's worth; the purse when a crore is worth nothing (bidplan.py `_cap`). */
function capOf(g: number, lam: number, slot: number): number {
  const net = g - slot;
  if (net <= 0) return 0;
  return lam > 0 ? net / lam : Infinity;
}

function replay(ctx: BidContext, cands: Piece[], prices: number[], lam: number, overrides: Record<string, number>, gains: Gains, future: number[], mv: MoneyValue | null = null): Run {
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
      const [lamI, slotI] = mv === null ? [lam, 0] : mv.value(i, left - reserve, sqMax - n - 1);
      if ((c.ub as number) <= slotI || (c.ub as number) < lamI * r + slotI) continue;
      const ahead = [...bought, ...future.filter((j) => j > i)];
      cap = capOf(gains.gain(gains.state(ahead), i), lamI, slotI);
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

export interface CurvePoint {
  lam: number;
  strength: number;
  /** strength + the purse left unspent × the market's runs per crore */
  value: number;
}

/** λ maximising the mean value over the runs: strength plus the unspent purse at the market's runs
 * per crore `rate` (bidplan.py `_search`). */
function search(ctx: BidContext, cands: Piece[], byRun: number[][], over: Record<string, number>, gains: Gains, future: number[], rate: number): [number, CurvePoint[]] {
  const trials = byRun.length;
  let bestLam = LAMBDA_GRID[LAMBDA_GRID.length - 1];
  let bestMean = -Infinity;
  const curve: CurvePoint[] = [];
  const left = Number(ctx.purse_left);
  for (const lam of [...LAMBDA_GRID].reverse()) {
    const runs = byRun.map((pr) => replay(ctx, cands, pr, lam, over, gains, future));
    const tot = fsum(runs.map((r) => r.total));
    const val = fsum(runs.map((r) => r.total + rate * (left - r.spend)));
    const mean = trials ? tot / trials : 0;
    const mval = trials ? val / trials : 0;
    curve.push({ lam, strength: mean, value: mval });
    if (mval > bestMean) {
      bestMean = mval;
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
  curve: CurvePoint[];
  /** the market's runs per crore: the value of a crore left unspent (`rivalRuns`) */
  purse_rate: number;
  money: MoneyRule;
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
  rateIn: number | null = null,
  money: MoneyRule = MONEY,
): BidPlan {
  const tgt: Record<Need, number> = { ...DEFAULT_NEEDS };
  for (const [k, v] of Object.entries(needs)) {
    if (k in tgt && typeof v === "number" && v >= 0) tgt[k as Need] = Math.trunc(v);
  }
  const over: Record<string, number> = {};
  for (const [k, v] of Object.entries(overrides)) if (v !== null && v !== undefined && v >= 0) over[k] = Number(v);
  let prices: number[][];
  let rate: number | null = rateIn;
  if (pricesIn === null) {
    const rr0 = rivalRuns(ctx, trials);
    prices = rr0.prices;
    rate = rr0.rate;
  } else prices = pricesIn;
  const nTrials = prices.length ? prices[0].length : trials;
  if (money === "none") rate = 0;
  else if (money === "market" && rate === null) rate = rivalRuns(ctx, nTrials).rate;
  const marketRate: number = rate ?? 0;
  const expected = prices.map((ps) => median(ps));
  const cands = candsOf(ctx, lotP(ctx, expected));
  const sqMax = Number(ctx.rules.squad_max);
  const sqMin = Number(ctx.rules.squad_min);
  const reserve0 = Math.max(0, sqMin - ctx.kept.length) * MIN_SLOT_PRICE;
  const gains = new Gains(ctx.kept, cands, tgt);
  const byRun: number[][] = [];
  for (let t = 0; t < nTrials; t++) byRun.push(cands.map((_, i) => prices[i][t]));

  let future: number[] = [];
  let rounds = 0;
  let lam = 0;
  let curve: CurvePoint[] = [];
  let land: number[] = [];
  let priceSum: number[] = [];
  let runs: Run[] = [];
  let likely: number[] = [];
  const same = (a: number[], b: number[]) => a.length === b.length && a.every((x, i) => x === b[i]);
  for (;;) {
    rounds += 1;
    let mv: MoneyValue | null = null;
    if (money === "auction") {
      mv = new MoneyValue(cands, gains, future, expected);
      lam = mv.value(-1, Number(ctx.purse_left) - reserve0, sqMax - ctx.kept.length)[0];
      curve = [];
    } else [lam, curve] = search(ctx, cands, byRun, over, gains, future, marketRate);
    land = new Array(cands.length).fill(0);
    priceSum = new Array(cands.length).fill(0);
    runs = [];
    for (let t = 0; t < nTrials; t++) {
      const rr = replay(ctx, cands, byRun[t], lam, over, gains, future, mv);
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

  const osMax = Number(ctx.rules.overseas_max);
  const likelySet = new Set(likely);
  // the money value on the final likely squad (bidplan.py `mv_final`)
  const mvFinal = money === "auction" ? new MoneyValue(cands, gains, likely, expected) : null;
  const likelyPieces = [...ctx.kept, ...likely.map((i) => cands[i])];
  const expPaid = new Map(likely.map((i) => [i, priceSum[i] / land[i]]));

  const gainWithout = (drop: Set<number>, i: number) => {
    const base = [...ctx.kept, ...likely.filter((j) => !drop.has(j)).map((j) => cands[j])];
    return strength([...base, cands[i]], tgt).total - strength(base, tgt).total;
  };
  const budgetOf = (rest: number[]) => {
    const reserve = Math.max(0, sqMin - ctx.kept.length - rest.length - 1) * MIN_SLOT_PRICE;
    return Number(ctx.purse_left) - fsum(rest.map((j) => expPaid.get(j) as number)) - reserve;
  };
  const lamAt = (drop: Set<number>, i: number): [number, number] => {
    if (mvFinal === null) return [lam, 0];
    const rest = likely.filter((j) => !drop.has(j));
    const room = sqMax - ctx.kept.length - rest.length - 1;
    return mvFinal.value(i, budgetOf(rest), room, new Set([...rest, ...drop]));
  };
  const maxBid = (drop: Set<number>, i: number): [number, number, boolean] => {
    const g = gainWithout(drop, i);
    const rest = likely.filter((j) => !drop.has(j));
    const budget = budgetOf(rest);
    const [li, slot] = lamAt(drop, i);
    const byValue = capOf(g, li, slot);
    const mb = Math.min(Math.max(0, budget), byValue);
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
      net: pLe * (g - lamAt(new Set([i]), i)[1] - lamAt(new Set([i]), i)[0] * meanUnder),
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
    const [worth, g] = maxBid(new Set([i]), i);
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
    purse_rate: money === "auction" ? lam : marketRate,
    money,
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
