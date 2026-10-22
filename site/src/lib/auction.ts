import type { AuctionPoolRow } from "./data";
import { tierDiscount } from "./leagues.ts";

export type Role = "batter" | "bowler" | "all_rounder" | "keeper";

export interface PoolPlayer {
  cricsheet_id: string;
  name: string;
  role: Role;
  country: string;
  is_overseas: boolean;
  team: string | null; // current IPL franchise code, null = free agent
  value: number; // complete Bayes value (best of bat/bowl)
  projected_value: number; // his price (cr): the market price, else the on-field curve
  onfield_value: number; // the on-field curve's price (cr): what his play alone is worth
  p_bought: number | null; // chance a franchise buys him (players with an IPL record), else null
  captain: string | null; // the IPL sides he captained last season (the "Captain" badge), else null
  base_price: number; // estimated tier (cr)
  vpc: number; // value per credit
  price_cap: number; // his price ceiling (rises with IPL balls): bidding can't clear him above it
}

// All-rounders / keepers carry a small scarcity premium.
const ROLE_MULT: Record<Role, number> = {
  batter: 1.0,
  bowler: 1.0,
  all_rounder: 1.15,
  keeper: 1.05,
};
// Calibrated to real IPL crore. The Bayes `value` is in runs per 100 balls above
// the league's average ball (scoring + wickets priced in runs where he plays, or
// runs saved + wickets; pool ~ -40..+60), priced on the cautious estimate
// value − PRICE_CAUTION_SD × value_sd and amplified exponentially: 25.6 -> 27cr
// cap, 20 -> ~17.8, 10 -> ~8.5, 0 -> 4.03, -35 -> ~0.3 floor. Re-fitted when the
// value moved from population-sd units to runs (and again for the cautious
// estimate): same pool median (~1.18cr) and as many 10cr+ players (25) as the
// earlier curve, itself anchored to the 2025 auction/retention prices
// (docs/AUCTION_MATH.md).
const PV_BASE = 4.03;
const PV_SCALE = 0.0743;
const PV_MAX = 27;
// Price on a cautious estimate: value − PRICE_CAUTION_SD × value_sd (mirror of pricing.py). A
// thin-sample prodigy is "promising but unproven"; a proven star barely moves. `value` stays the
// central estimate for display and rankings.
export const PRICE_CAUTION_SD = 0.5;
// The price ceiling rises with IPL evidence in the role priced (mirror of pricing.py): 0 balls →
// half the cap (13.5 cr), 600+ balls → the full 27 cr. Applied after the cautious estimate.
export const CEILING_FULL_BALLS = 600;
export const CEILING_FLOOR_SHARE = 0.5;

/** The most a player can be priced at (cr), from his target-league balls (missing → 0). */
export function priceCeiling(targetBalls?: number | null): number {
  const b = typeof targetBalls === "number" && Number.isFinite(targetBalls) ? Math.max(targetBalls, 0) : 0;
  const share = Math.min(1, b / CEILING_FULL_BALLS);
  return PV_MAX * (CEILING_FLOOR_SHARE + (1 - CEILING_FLOOR_SHARE) * share);
}

/** The value a price is set from (a missing / non-finite sd counts as 0). */
export function pricedValue(value: number, valueSd?: number | null): number {
  const sd = typeof valueSd === "number" && Number.isFinite(valueSd) ? Math.max(valueSd, 0) : 0;
  return value - PRICE_CAUTION_SD * sd;
}

// IPL base-price set bands (cr) — what a player ENTERS the auction at.
const PRICE_TIERS = [0.3, 0.5, 0.75, 1.0, 1.5, 2.0];

export function priceTier(pv: number): number {
  if (pv < 2) return PRICE_TIERS[0];
  if (pv < 4) return PRICE_TIERS[1];
  if (pv < 7) return PRICE_TIERS[2];
  if (pv < 11) return PRICE_TIERS[3];
  if (pv < 16) return PRICE_TIERS[4];
  return PRICE_TIERS[5];
}

// Cross-tier value discount — runs in a weaker comp aren't worth IPL crore.
// Mirrors the export-time penalty so Scout's est. prices agree with the
// Auction pool. The auction_pool `value` is already penalised at export; raw
// scout `value` is not, so callers pricing scout players pass their tier.
// In value units (runs per 100 balls). The numbers come from the league registry
// (config/leagues.toml → data/leagues.json), the same table the Python port reads.
export type PriceTier = string; // a tier key from leagues.json: "ipl" | "smat" | "bbl" | …

/** Estimated crore value from a raw Bayes value — same curve the auction uses.
 * `tier` discounts non-IPL comps so a SMAT/BBL price is comparable to IPL. */
export function estValue(
  value: number,
  role: Role,
  tier: PriceTier = "ipl",
  valueSd?: number | null,
  targetBalls?: number | null,
): number {
  const adj = pricedValue(value, valueSd) - tierDiscount(tier);
  return Math.max(0.3, Math.min(priceCeiling(targetBalls), PV_BASE * Math.exp(PV_SCALE * adj) * ROLE_MULT[role]));
}

/** A player's price on the IPL curve (no tier discount) — the pool's price; `estValue(…, "ipl", …)`
 * without needing the league registry loaded. Mirror of `est_value(value, role, "ipl", sd, balls)`. */
export function iplPrice(value: number, role: Role, valueSd?: number | null, targetBalls?: number | null): number {
  return Math.max(0.3, Math.min(priceCeiling(targetBalls), PV_BASE * Math.exp(PV_SCALE * pricedValue(value, valueSd)) * ROLE_MULT[role]));
}

// ---- market price: fitted to real IPL auction prices ----------------------------------------
//
// `iplPrice` / `estValue` above price what a player does on the field (the hand-set curve: his
// "on-field worth"). `marketPrice` is what the auction market pays for a player like him: a hurdle
// model fitted to every IPL auction 2009-2026 (scripts/ipl_price_model.py → config/price_model.json,
// exported as data/<league>/price_model.json): ln(price / purse) from his cautious value,
// nationality, international caps, age, IPL experience and the auction type, plus, for a player
// with an IPL record, the chance he's bought at all. EXACT mirror of web_parity/pricing.py
// (`market_features`, `market_price`); test_scripts/test_web_parity.py checks both.
// docs/METHODOLOGY.md §6.

export const MARKET_AGE_CENTRE = 28;
export const MARKET_PV_MIN = -40;
export const MARKET_PV_MAX = 60;
export const MARKET_GAP_MAX = 6; // years since his last IPL match, capped
// `high` = the upper quartile of what players like him fetch: the median × e^(0.674 × residual sd)
export const MARKET_HIGH_Z = 0.674;

export interface PriceModelPart {
  intercept: number;
  coef: Record<string, number>; // feature → coefficient, in the order they are summed
  calibration?: { x: number[]; y: number[] } | null; // top-end calibration knots (ln share)
  shift?: number | null; // added after the calibration
  /** per-group calibrations: the first whose `when` ({feature: [lo, hi]}) holds replaces the above */
  groups?: CalibrationGroup[] | null;
}
export interface CalibrationGroup {
  name: string;
  when: Record<string, [number, number]>;
  calibration?: { x: number[]; y: number[] } | null;
  shift?: number | null;
}
export interface PriceModel {
  schema: number;
  league: string;
  competition: { cycle: "mega" | "mini"; purse: number; key?: string };
  floor_cr: number;
  price: PriceModelPart & { resid_sd: number };
  bought: PriceModelPart;
  [k: string]: unknown;
}
export interface MarketCompetition {
  cycle: "mega" | "mini";
  purse: number;
}
/** The inputs `marketFeatures` reads (pool, squad and Scout rows carry them since the market
 * model; a row without `price_value` predates it and is priced on the on-field curve). */
export interface MarketInputs {
  price_value?: number | null; // blended value before the IPL-relevance discount (missing = unrated)
  value_sd?: number | null;
  role: Role;
  is_overseas?: boolean | null;
  overseas?: boolean | null;
  intl_caps?: number | null; // men's T20I + ODI + Test matches
  intl_caps_2y?: number | null; // ... in the two years before the auction
  age?: number | null;
  ipl_balls?: number | null;
  ipl_seasons?: number | null;
  ipl_gap?: number | null; // years since his last IPL match (missing = never played it)
  target_balls?: number | null;
  // captaincy known before the auction (scout/identity/captains.py)
  captain_ipl_last?: number | null; // captained an IPL side the season before
  captain_ipl_seasons?: number | null; // IPL seasons as captain
  captain_intl_2y?: number | null; // captained his country in the two calendar years before
}

let priceModel: PriceModel | null = null;

/** Install the fitted model (data.ts `getAuctionPool` does this; so do the parity harnesses). */
export function registerPriceModel(m: PriceModel | null): void {
  priceModel = m;
}
export function priceModelLoaded(): boolean {
  return priceModel !== null;
}
export function getPriceModel(): PriceModel | null {
  return priceModel;
}

const fin = (x: unknown): number | null => (typeof x === "number" && Number.isFinite(x) ? x : null);

/** A player's market-model features (mirror of pricing.market_features). */
export function marketFeatures(row: MarketInputs, cycle: string): Record<string, number> {
  const v = fin(row.price_value);
  const rated = v !== null;
  let pv = 0;
  if (rated) pv = Math.min(MARKET_PV_MAX, Math.max(MARKET_PV_MIN, pricedValue(v, row.value_sd)));
  const ovRaw = row.is_overseas !== undefined ? row.is_overseas : row.overseas;
  const ov = ovRaw ? 1 : 0;
  const capsN = fin(row.intl_caps) || 0;
  const caps = Math.log1p(Math.max(capsN, 0));
  const recent = Math.log1p(Math.max(fin(row.intl_caps_2y) || 0, 0));
  const cappedInd = (capsN > 0 ? 1 : 0) * (1 - ov);
  const age = fin(row.age);
  const a = age !== null ? age - MARKET_AGE_CENTRE : 0;
  const gap = fin(row.ipl_gap);
  const pvPos = Math.max(pv, 0);
  return {
    pv,
    pv_pos_sq: (pvPos * pvPos) / 100,
    unrated: rated ? 0 : 1,
    overseas: ov,
    pv_x_overseas: pv * ov,
    caps,
    caps_x_indian: caps * (1 - ov),
    pv_x_capped_indian: pv * cappedInd,
    recent_caps: recent,
    recent_caps_x_indian: recent * (1 - ov),
    age: a,
    age_sq: (a * a) / 10,
    age_missing: age !== null ? 0 : 1,
    ipl_balls: Math.log1p(Math.max(fin(row.ipl_balls) || 0, 0)),
    ipl_seasons: Math.min(fin(row.ipl_seasons) || 0, 15),
    never_ipl: gap === null ? 1 : 0,
    ipl_gap: gap === null ? 0 : Math.min(Math.max(gap, 0), MARKET_GAP_MAX),
    all_rounder: row.role === "all_rounder" ? 1 : 0,
    keeper: row.role === "keeper" ? 1 : 0,
    bowler: row.role === "bowler" ? 1 : 0,
    mega: cycle === "mega" ? 1 : 0,
    captain_ipl: (fin(row.captain_ipl_last) || 0) > 0 ? 1 : 0,
    captain_seasons: Math.log1p(Math.max(fin(row.captain_ipl_seasons) || 0, 0)),
    captain_intl: (fin(row.captain_intl_2y) || 0) > 0 ? 1 : 0,
  };
}

function linear(part: PriceModelPart, f: Record<string, number>): number {
  let t = part.intercept;
  for (const [k, c] of Object.entries(part.coef)) {
    const x = f[k];
    if (x === undefined) throw new Error(`price model feature "${k}" is unknown`);
    t += c * x;
  }
  return t;
}

/** The top-end calibration of the linear predictor: a monotone piecewise-linear map through the
 * knots (continued at slope 1 beyond the end knots) plus `shift`. Mirror of pricing.calibrate. */
export function calibrate(part: PriceModelPart | CalibrationGroup, lin: number): number {
  const cal = part.calibration;
  let out = lin;
  if (cal && cal.x && cal.x.length) {
    const xs = cal.x;
    const ys = cal.y;
    const n = xs.length;
    if (lin <= xs[0]) out = lin + (ys[0] - xs[0]);
    else if (lin >= xs[n - 1]) out = lin + (ys[n - 1] - xs[n - 1]);
    else {
      let i = 0;
      while (i < n - 2 && lin > xs[i + 1]) i++;
      out = ys[i] + ((lin - xs[i]) * (ys[i + 1] - ys[i])) / (xs[i + 1] - xs[i]);
    }
  }
  return out + (part.shift ?? 0);
}

/** The calibration that applies to a player: the first group whose `when` holds, else the part
 * itself. Mirror of pricing.calibration_part. */
export function calibrationPart(part: PriceModelPart, f: Record<string, number>): PriceModelPart | CalibrationGroup {
  for (const g of part.groups ?? []) {
    if (Object.entries(g.when).every(([k, [lo, hi]]) => lo <= f[k] && f[k] <= hi)) return g;
  }
  return part;
}

/** What the auction market pays for this player (the model's median, cr) and the upper quartile
 * of that (`high`), clamped to [floor, the IPL-evidence ceiling], and, for a player with an IPL record, the chance he's bought at all.
 * `comp` defaults to the model's competition. Mirror of pricing.market_price. */
export function marketPrice(
  row: MarketInputs,
  comp?: MarketCompetition | null,
  model?: PriceModel | null,
): { price: number; high: number; p_bought: number | null } {
  const m = model ?? priceModel;
  if (!m) throw new Error("no price model loaded (price_model.json)");
  const c = comp ?? m.competition;
  const f = marketFeatures(row, c.cycle);
  const cal = calibrationPart(m.price, f);
  const lin = calibrate(cal, linear(m.price, f));
  const cap = priceCeiling(row.target_balls);
  const price = Math.max(m.floor_cr, Math.min(cap, c.purse * Math.exp(lin)));
  // the upper quartile: the calibrated prediction (group shift included) + 0.674 residual sd
  const high = Math.max(m.floor_cr, Math.min(cap, c.purse * Math.exp(lin + MARKET_HIGH_Z * m.price.resid_sd)));
  const p = f.never_ipl === 0 ? 1 / (1 + Math.exp(-linear(m.bought, f))) : null;
  return { price, high, p_bought: p };
}

/** True when this row can take the market price: a model is loaded and the row carries its
 * inputs (an export from before the market model doesn't). Mirror of pricing.has_market_inputs. */
export function hasMarketInputs(row: object): boolean {
  return priceModel !== null && "price_value" in row;
}

/** Price the big auction pool (every ACTIVE rated IPL player). Each row
 * already carries value / role / country / team; we add crore pricing: the market price when the
 * model and its inputs are there (`projected_value`), with the on-field curve alongside. */
export function buildPool(rows: AuctionPoolRow[]): PoolPlayer[] {
  const out: PoolPlayer[] = rows.map((r) => {
    const onfield = Math.max(
      0.3,
      Math.min(
        priceCeiling(r.target_balls),
        PV_BASE * Math.exp(PV_SCALE * pricedValue(r.value, r.value_sd)) * ROLE_MULT[r.role],
      ),
    );
    const mk = hasMarketInputs(r) ? marketPrice(r as MarketInputs) : null;
    const pv = mk ? mk.price : onfield;
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
      onfield_value: onfield,
      p_bought: mk ? mk.p_bought : null,
      captain: r.captain_teams && r.captain_teams.length ? r.captain_teams.join(" / ") : null,
      base_price: base,
      vpc: pv / base,
      price_cap: priceCeiling(r.target_balls),
    };
  });
  out.sort((a, b) => b.projected_value - a.projected_value);
  return out;
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
// keep most of the squad (release only a few), so only a handful are auctioned.
export const MINI_RETAIN = 18;
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

export interface FranchiseBase {
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
  boughtPrices: number[]; // price paid per bought player, aligned with `bought`
  spent: number; // auction spend only
  overseas: number; // retained + bought
  counts: Record<Role, number>;
}

// Per-player landing summary across all trials — powers the "where did X go?"
// search after a run.
export interface PlayerOutcome {
  cricsheet_id: string;
  name: string;
  role: Role;
  is_overseas: boolean;
  status: "retained" | "sold" | "unsold";
  team: string | null; // retained team, or most-likely buyer, else null
  soldPct: number; // % of trials bought (0 for retained/unsold)
  avgPrice: number; // avg price across trials bought (retention cost if retained)
  winners: { team: string; pct: number }[]; // top buyers by trial-share
}

export interface SimResult {
  mode: AuctionMode;
  bases: FranchiseBase[]; // retentions (constant across trials)
  poolSize: number; // unretained players in the pool
  auctioned: number; // how many of them go under the hammer (the most valuable, up to AUCTION_LOTS)
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
  outcomes: PlayerOutcome[]; // every retained + auctioned player's landing
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
      // Mega: retentions draw from the 120cr purse via slabs (or real price).
      // Mini: the squad is already paid for (sunk) — retentions are free and
      // the team bids from a small leftover purse.
      if (opts.mode !== "mini") retainSpend += opts.realPrices[p.cricsheet_id] ?? slabCost(i);
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
    boughtPrices: [],
    spent: 0,
    overseas: b.retainOverseas,
    counts,
  };
}

// Rival willingness to pay, calibrated to real auctions (scripts/auction_calibrate.py; docs/AUCTION_MATH.md
// Part 3b): lot value = BID_LEVEL[cycle] × BID_PIVOT × (projected / BID_PIVOT) ^ BID_CURVE × e^(LOT_HYPE_SD × z),
// z drawn once per lot per run and shared by every team. Neutral (1, 1, 1, 0) = the uncalibrated room.
// Fitted 2026-10-22 on the 2022 mega and 2023 / 2024 mini auctions (out of time: 2025, 2026).
export const BID_LEVEL: Record<AuctionMode, number> = { mega: 0.864, mini: 1.0368 };
export const BID_CURVE = 0.75;
export const BID_PIVOT = 1.0;
export const LOT_HYPE_SD = 1.0;
/** Market tightness on (1) or off (0): bids × (money left with teams that have places ÷ market value of the best
 * unsold players filling them), clamped to TIGHT_MIN … TIGHT_MAX. */
export const TIGHTNESS = 1;
/** Reference price: a row's `anchor_price` (his last IPL price, cr) pulls his lot value to
 * value^(1 − ANCHOR) × (level × last price)^ANCHOR. 0 = off. */
export const ANCHOR = 0.3;
/** Team taste: each team's view of each lot varies by e^(TASTE_SD × z), z per team per lot. 0 = off. */
export const TASTE_SD = 0.0;
export const TIGHT_MIN = 0.2;
export const TIGHT_MAX = 10.0;
const SQRT3 = 1.7320508075688772;
export interface Calibration {
  level_mega: number;
  level_mini: number;
  curve: number;
  sd: number;
  tight: number;
  anchor: number;
  taste: number;
}
/** The calibration in force: the shipped constants, overridden by `opts.calib` (mirror of auction.py). */
export function calibration(opts: { calib?: Partial<Calibration> | null }): Calibration {
  const c = opts.calib ?? {};
  return {
    level_mega: Number(c.level_mega ?? BID_LEVEL.mega),
    level_mini: Number(c.level_mini ?? BID_LEVEL.mini),
    curve: Number(c.curve ?? BID_CURVE),
    sd: Number(c.sd ?? LOT_HYPE_SD),
    tight: Number(c.tight ?? TIGHTNESS),
    anchor: Number(c.anchor ?? ANCHOR),
    taste: Number(c.taste ?? TASTE_SD),
  };
}

const MIN_BASE = 0.3; // cheapest base price (cr) — reserve this per unfilled slot
const MIN_SQUAD = 20; // every team fills to at least 20 (max = squadSize, ≤25)
// No player clears above the real IPL record (Pant, 27 cr, 2025 mega auction).
export const PRICE_CAP = 27;
// Budget pressure: a team with more purse per open slot than the league bids
// harder (and a stretched one softer) — (ratio ** EXP), clamped.
const PRESSURE_EXP = 0.5;
const PRESSURE_MIN = 0.75;
const PRESSURE_MAX = 1.6;

/** One mock auction. `onSale(player, team index, winning max bid, price)` is called for each sale
 * when given (Bid plan reads the winning bid: the price a rival would have paid); a sale in the
 * final base-price pass reports his base price as the bid. Mirror of auction.py `one_trial`. */
export function oneTrial(
  bases: FranchiseBase[],
  auctionPool: PoolPlayer[],
  opts: Pick<SimOpts, "purse" | "squadSize" | "overseasCap"> & { mode?: AuctionMode; calib?: Partial<Calibration> | null },
  seed: number,
  onSale?: (player: PoolPlayer, team: number, bestBid: number, price: number) => void,
): TeamState[] {
  const rand = rng(seed);
  const states = bases.map(freshState);
  const filledOf = (st: TeamState) => st.retained.length + st.bought.length;
  const remPurseOf = (i: number) => opts.purse - bases[i].retainSpend - states[i].spent;
  const buy = (i: number, player: PoolPlayer, price: number) => {
    const st = states[i];
    st.bought.push(player);
    st.boughtPrices.push(price);
    st.spent += price;
    st.counts[player.role]++;
    if (player.is_overseas) st.overseas++;
  };

  const order = [...auctionPool]
    .map((p) => ({ p, k: p.projected_value * (1 + (rand() - 0.5) * 0.1) }))
    .sort((a, b) => b.k - a.k)
    .map((x) => x.p);
  const sold = new Set<string>();
  // each lot's value to a bidder this run (calibrated level and curve × the shared demand shock)
  const cal = calibration(opts);
  const level = (opts.mode ?? "mini") === "mega" ? cal.level_mega : cal.level_mini;
  const lotValue = new Map<string, number>();
  for (const p of order) {
    const pv = p.projected_value;
    let v = cal.curve === 1.0 ? level * pv : level * BID_PIVOT * Math.pow(pv / BID_PIVOT, cal.curve);
    const a = (p as PoolPlayer & { anchor_price?: number | null }).anchor_price;
    if (cal.anchor > 0 && a) v = Math.pow(v, 1.0 - cal.anchor) * Math.pow(level * Number(a), cal.anchor);
    if (cal.sd > 0) {
      const z = (rand() + rand() + rand() + rand() - 2.0) * SQRT3;
      v = v * Math.exp(cal.sd * z);
    }
    lotValue.set(p.cricsheet_id, v);
  }
  const tight = cal.tight > 0;
  const byValue = tight
    ? [...order].sort((a, b) =>
        a.projected_value !== b.projected_value ? (a.projected_value > b.projected_value ? -1 : 1) : a.cricsheet_id < b.cricsheet_id ? -1 : a.cricsheet_id > b.cricsheet_id ? 1 : 0,
      )
    : [];
  // money left with the teams that have places ÷ market value of the best unsold players filling them (clamped)
  const tightness = (): number => {
    let money = 0;
    let nOpen = 0;
    for (let i = 0; i < states.length; i++) {
      const slots = opts.squadSize - filledOf(states[i]);
      if (slots > 0) {
        nOpen += slots;
        money += Math.max(0, remPurseOf(i));
      }
    }
    let value = 0;
    let k = 0;
    for (const p of byValue) {
      if (k >= nOpen) break;
      if (sold.has(p.cricsheet_id)) continue;
      value += p.projected_value;
      k++;
    }
    if (value <= 0) return 1;
    return Math.min(TIGHT_MAX, Math.max(TIGHT_MIN, money / value));
  };

  // One bidding round over the pool, with teams capped at `target` squad size.
  // Run it first to MIN_SQUAD (so every team gets its minimum before anyone
  // tops up) and again to the full squadSize cap.
  const perSlotOf = (i: number) => {
    const slotsLeft = opts.squadSize - filledOf(states[i]);
    return slotsLeft > 0 ? remPurseOf(i) / slotsLeft : 0;
  };
  const bidRound = (target: number) => {
    for (const player of order) {
      if (sold.has(player.cricsheet_id)) continue;
      // league purse-per-open-slot, for budget pressure
      const openSlots: number[] = [];
      for (let i = 0; i < states.length; i++) {
        if (filledOf(states[i]) < opts.squadSize) openSlots.push(perSlotOf(i));
      }
      let leaguePerSlot = 0;
      for (const v of openSlots) leaguePerSlot += v;
      leaguePerSlot = openSlots.length ? leaguePerSlot / openSlots.length : 0;
      const market = tight ? tightness() : 1;
      let bestTeam = -1;
      let bestBid = 0;
      let secondBid = player.base_price;
      for (let i = 0; i < states.length; i++) {
        const st = states[i];
        const arc = ARCH_BY_ID[st.personality] ?? ARCH_BY_ID.Balanced;
        if (filledOf(st) >= target) continue;
        if (player.is_overseas && st.overseas >= opts.overseasCap) continue;
        // reserve enough to fill remaining slots (toward the full cap) cheaply
        const slotsLeft = opts.squadSize - filledOf(st);
        const spendable = remPurseOf(i) - (slotsLeft - 1) * MIN_BASE;
        if (spendable < player.base_price) continue;
        const need = st.counts[player.role] < arc.roleMins[player.role] ? 1.5 : 0.7;
        const overseasBias = player.is_overseas ? arc.overseasAppetite * 1.4 : 1;
        let jitter = 1 + (rand() - 0.5) * 2 * arc.risk;
        if (cal.taste > 0) jitter = jitter * Math.exp(cal.taste * (rand() + rand() + rand() + rand() - 2.0) * SQRT3);
        let pressure = 1;
        if (leaguePerSlot > 0) {
          pressure = Math.min(
            PRESSURE_MAX,
            Math.max(PRESSURE_MIN, (perSlotOf(i) / leaguePerSlot) ** PRESSURE_EXP),
          );
        }
        let wtp = (lotValue.get(player.cricsheet_id) as number) * market * arc.aggression * need * overseasBias * jitter * pressure;
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
        const price = Math.min(PRICE_CAP, player.price_cap, bestBid, secondBid * 1.02);
        buy(bestTeam, player, Math.max(player.base_price, price));
        sold.add(player.cricsheet_id);
        if (onSale) onSale(player, bestTeam, bestBid, Math.max(player.base_price, price));
      }
    }
  };

  bidRound(MIN_SQUAD); // everyone reaches the minimum first
  bidRound(opts.squadSize); // then top up toward the cap

  // Safety: any team still under MIN gets the cheapest leftovers at base price.
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
      if (onSale) onSale(player, pick, player.base_price, player.base_price);
    }
  }
  return states;
}

/** Lots per auction: the most valuable unretained players (a real auction lists far more, most go unsold). */
export const AUCTION_LOTS = 200;
// At most this share of the lots is overseas, as on a real shortlist (2024: 119 overseas of 333,
// Wikipedia's 2024 personnel page). The market price values overseas players higher, so without it
// the top 200 would be two-thirds overseas and the eight-per-squad cap would leave squads unfilled.
export const AUCTION_OVERSEAS_SHARE = 0.36;

/** The lots: the most valuable unretained players (pool order), at most AUCTION_LOTS of them and at
 * most AUCTION_OVERSEAS_SHARE of those overseas. Mirror of auction.py `auction_lots`. */
export function auctionLots(auctionPool: PoolPlayer[]): PoolPlayer[] {
  const maxOs = Math.round(AUCTION_LOTS * AUCTION_OVERSEAS_SHARE);
  const out: PoolPlayer[] = [];
  let nOs = 0;
  for (const p of auctionPool) {
    if (out.length >= AUCTION_LOTS) break;
    if (p.is_overseas) {
      if (nOs >= maxOs) continue;
      nOs++;
    }
    out.push(p);
  }
  return out;
}

export function simulateAuction(
  pool: PoolPlayer[],
  teamCfg: { team: string; personality: string }[],
  opts: SimOpts,
): SimResult {
  const { bases, auctionPool } = buildFranchises(pool, teamCfg, opts);
  const usePool = auctionLots(auctionPool);
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
  // per-player landing accumulators (every auctioned player)
  const buys = new Map<string, { count: number; priceSum: number; teams: Map<string, number> }>();
  for (const p of usePool) buys.set(p.cricsheet_id, { count: 0, priceSum: 0, teams: new Map() });

  let sampleDraft: TeamState[] = [];
  for (let t = 0; t < opts.trials; t++) {
    const states = oneTrial(bases, usePool, opts, 1000 + t * 7919);
    if (t === Math.floor(opts.trials / 2)) sampleDraft = states;
    states.forEach((st, i) => {
      agg[i].bought += st.bought.length;
      agg[i].spend += st.spent;
      agg[i].value += agg[i].retVal + st.bought.reduce((s, p) => s + p.projected_value, 0);
      agg[i].overseas += st.overseas;
      st.bought.forEach((p, k) => {
        const m = marqueeWins.get(p.cricsheet_id);
        if (m) m.set(st.team, (m.get(st.team) ?? 0) + 1);
        const b = buys.get(p.cricsheet_id);
        if (b) {
          b.count++;
          b.priceSum += st.boughtPrices[k];
          b.teams.set(st.team, (b.teams.get(st.team) ?? 0) + 1);
        }
      });
    });
  }
  const n = opts.trials;
  const topWinners = (tm: Map<string, number>) =>
    [...tm.entries()]
      .map(([team, c]) => ({ team, pct: (c / n) * 100 }))
      .sort((a, b) => b.pct - a.pct)
      .slice(0, 3);
  // outcomes = retained (in team order) then every auctioned player (pool order)
  const outcomes: PlayerOutcome[] = [];
  bases.forEach((b) => {
    b.retained.forEach((p, i) => {
      const cost = opts.mode !== "mini" ? (opts.realPrices[p.cricsheet_id] ?? slabCost(i)) : 0;
      outcomes.push({
        cricsheet_id: p.cricsheet_id,
        name: p.name,
        role: p.role,
        is_overseas: p.is_overseas,
        status: "retained",
        team: b.team,
        soldPct: 0,
        avgPrice: cost,
        winners: [],
      });
    });
  });
  for (const p of usePool) {
    const b = buys.get(p.cricsheet_id)!;
    const winners = topWinners(b.teams);
    outcomes.push({
      cricsheet_id: p.cricsheet_id,
      name: p.name,
      role: p.role,
      is_overseas: p.is_overseas,
      status: b.count > 0 ? "sold" : "unsold",
      team: winners.length ? winners[0].team : null,
      soldPct: (b.count / n) * 100,
      avgPrice: b.count > 0 ? b.priceSum / b.count : 0,
      winners,
    });
  }
  return {
    mode: opts.mode,
    bases,
    poolSize: auctionPool.length,
    auctioned: usePool.length,
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
    outcomes,
    sampleDraft,
  };
}

/** A Scout row's estimated price in `tier`: the market price on his value less the tier's
 * discount when the model and the row's market inputs are there, else the on-field curve
 * (`estValue`). Mirror of pricing.scout_price. */
export function scoutPrice(
  p: MarketInputs & { value: number; value_sd?: number | null; target_balls?: number | null },
  tier: PriceTier,
): number {
  if (priceModel !== null && "intl_caps" in p) {
    return marketPrice({ ...p, price_value: p.value - tierDiscount(tier) }).price;
  }
  return estValue(p.value, p.role, tier, p.value_sd, p.target_balls);
}
