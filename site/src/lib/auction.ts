import type { AuctionPoolRow, RetentionData } from "./data";
import { slabCharge, type SlabHolder } from "./slabs.ts";

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
  // playing time (METHODOLOGY §6c): runs above replacement per match he plays, its parts and balls,
  // P(plays a match) and the expected runs over a season; null in an export before 2026-10-22
  contrib: number | null;
  contrib_bat: number | null;
  contrib_bowl: number | null;
  balls_faced: number | null;
  balls_bowled: number | null;
  p_play: number | null;
  season_value: number | null;
  captain: string | null; // the IPL sides he captained last season (the "Captain" badge), else null
  capped?: boolean | null; // the set he comes up in (capped before uncapped; absent = capped)
  prior_share?: number | null; // his last IPL price as a share of that season's purse (reference price)
  age?: number | null; // Bid plan's P(plays) of a buy reads these (bidplan.py BUY_META_KEYS)
  ipl_matches?: number | null;
  last_share?: number | null;
  captain_ipl_last?: number | boolean | null;
  p_play_free?: number | null; // P(plays a match) as a free agent
  base_price: number; // estimated tier (cr)
  vpc: number; // value per credit
}

// The hand-set all-rounder ×1.15 / keeper ×1.05 premium was removed on 2026-10-22 (audit item 6):
// the market model's fitted role terms are the price premium, and a second discipline counts
// through the contribution per match (playing_time.py). Mirror of pricing.py.
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

// A rating from another league is put on the IPL rating scale by the fitted league translation
// (cricdex.scout.translation, per league and role) at export: the pool's `value` and Scout's `ipl_value`
// come translated, so every price here takes a value already on the IPL scale. (Until 2026-10-23: one
// hand-set discount per league, `tierDiscount`, taken off here and in pricing.py.)
export type PriceTier = string; // a tier key from leagues.json: "ipl" | "smat" | "bbl" | …

/** A player's price on the on-field curve from a value on the IPL rating scale (a rating from another
 * league must be translated first: the export does it). Mirror of `est_value(value, role, sd, balls)`. */
export function iplPrice(value: number, role: Role, valueSd?: number | null, targetBalls?: number | null): number {
  void role;
  return Math.max(0.3, Math.min(priceCeiling(targetBalls), PV_BASE * Math.exp(PV_SCALE * pricedValue(value, valueSd))));
}

// ---- market price: fitted to real IPL auction prices ----------------------------------------
//
// `iplPrice` above prices what a player does on the field (the hand-set curve: his
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
// The prior market price: prior = ln(prior_share / PRIOR_REF_SHARE), clamped (2% of the purse is about
// 2.5 cr in 2026); seasons since it capped at PRIOR_YEARS_MAX. Mirror of pricing.py.
export const PRIOR_REF_SHARE = 0.02;
export const PRIOR_MIN = -4;
export const PRIOR_MAX = 3;
export const PRIOR_YEARS_MAX = 6;

/** Calibration knots (ln share); beyond the last knot the map continues at `hi_slope` (1 when absent). */
export interface CalibrationMap {
  x: number[];
  y: number[];
  hi_slope?: number | null;
}
export interface PriceModelPart {
  intercept: number;
  coef: Record<string, number>; // feature → coefficient, in the order they are summed
  calibration?: CalibrationMap | null; // none = identity
  shift?: number | null; // added after the calibration
  /** per-group calibrations: the first whose `when` ({feature: [lo, hi]}) holds replaces the above */
  groups?: CalibrationGroup[] | null;
  /** how the linear index becomes the median ln share: "log" (itself) or "sat" (ln S + ln σ(η)) */
  link?: { kind: "log" | "sat"; cap_share?: number } | null;
  /** the priced value is held to this (the largest in the model's training rows); none = MARKET_PV_MAX */
  pv_max?: number | null;
}
export interface CalibrationGroup {
  name: string;
  when: Record<string, [number, number]>;
  calibration?: CalibrationMap | null;
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
  price_value?: number | null; // his value as the price recipe takes it (missing = unrated; pricing.value_input)
  price_value_sd?: number | null; // its sd (missing → value_sd)
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
  // the market's last verdict on him (scripts/ipl_price_model.market_verdicts)
  prior_share?: number | null; // the price a franchise last paid, as a share of that season's purse
  prior_years?: number | null; // seasons since
  prior_retained?: boolean | null; // a mega-auction retention rather than a sale
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

/** A player's market-model features (mirror of pricing.market_features). `pvMax` (the model's
 * `price.pv_max`) holds the priced value to the range the market has priced. */
export function marketFeatures(row: MarketInputs, cycle: string, pvMax?: number | null): Record<string, number> {
  const v = fin(row.price_value);
  const rated = v !== null;
  let pv = 0;
  const top = pvMax === null || pvMax === undefined ? MARKET_PV_MAX : Math.min(MARKET_PV_MAX, pvMax);
  if (rated) pv = Math.min(top, Math.max(MARKET_PV_MIN, pricedValue(v, row.price_value_sd ?? row.value_sd)));
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
  const ps = fin(row.prior_share);
  const hasPrior = ps !== null && ps > 0;
  let prior = 0;
  let pYears = 0;
  if (hasPrior) {
    prior = Math.min(PRIOR_MAX, Math.max(PRIOR_MIN, Math.log(ps / PRIOR_REF_SHARE)));
    pYears = Math.min(Math.max(fin(row.prior_years) || 0, 0), PRIOR_YEARS_MAX);
  }
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
    prior,
    no_prior: hasPrior ? 0 : 1,
    prior_years: pYears,
    prior_x_years: prior * pYears,
    prior_retained: hasPrior && row.prior_retained ? 1 : 0,
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

/** The median ln share from the linear index (mirror of pricing.link_share): "log" → η itself; "sat" →
 * ln S + ln σ(η), saturating at S = `cap_share`, the most one franchise pays for one player. */
export function linkShare(part: PriceModelPart, eta: number): number {
  const link = part.link;
  if (!link || link.kind !== "sat") return eta;
  const ls = eta >= 0 ? -Math.log1p(Math.exp(-eta)) : eta - Math.log1p(Math.exp(eta));
  return Math.log(link.cap_share as number) + ls;
}

/** The calibration of the linear predictor: a monotone piecewise-linear map through the knots,
 * continued at slope 1 below the first knot and at `hi_slope` (1 when absent) above the last, plus
 * `shift`. Mirror of pricing.calibrate. */
export function calibrate(part: PriceModelPart | CalibrationGroup, lin: number): number {
  const cal = part.calibration;
  let out = lin;
  if (cal && cal.x && cal.x.length) {
    const xs = cal.x;
    const ys = cal.y;
    const n = xs.length;
    const hi = cal.hi_slope === null || cal.hi_slope === undefined ? 1 : cal.hi_slope;
    if (lin <= xs[0]) out = lin + (ys[0] - xs[0]);
    else if (lin >= xs[n - 1]) out = ys[n - 1] + hi * (lin - xs[n - 1]);
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
 * of that (`high`), both at least the floor, and, for a player with an IPL record, the chance he's
 * bought at all. No ceiling: the fitted calibration sets the top end. `comp` defaults to the model's
 * competition. Mirror of pricing.market_price. */
export function marketPrice(
  row: MarketInputs,
  comp?: MarketCompetition | null,
  model?: PriceModel | null,
): { price: number; high: number; p_bought: number | null } {
  const m = model ?? priceModel;
  if (!m) throw new Error("no price model loaded (price_model.json)");
  const c = comp ?? m.competition;
  const f = marketFeatures(row, c.cycle, m.price.pv_max);
  const cal = calibrationPart(m.price, f);
  const raw = linkShare(m.price, linear(m.price, f));
  const lin = calibrate(cal, raw);
  const price = Math.max(m.floor_cr, c.purse * Math.exp(lin));
  // the upper quartile: a player 0.674 residual sd above him on the model's index, through the same
  // calibration (where the market's response flattens at the top, so does the spread above him)
  const high = Math.max(m.floor_cr, c.purse * Math.exp(calibrate(cal, raw + MARKET_HIGH_Z * m.price.resid_sd)));
  const p = f.never_ipl === 0 ? 1 / (1 + Math.exp(-linear(m.bought, f))) : null;
  return { price, high, p_bought: p };
}

/** True when this row can take the market price: a model is loaded and the row carries its
 * inputs (an export from before the market model doesn't). Mirror of pricing.has_market_inputs. */
export function hasMarketInputs(row: object): boolean {
  return priceModel !== null && "price_value" in row;
}

/** A mini auction's default retention order: expected season value, else (an export before it)
 * value. Mirror of auction.py `_retain_key`. */
export const retainKey = (p: PoolPlayer): number => (p.season_value !== null && p.season_value !== undefined ? p.season_value : p.value);

/** Price the big auction pool (every ACTIVE rated IPL player). Each row
 * already carries value / role / country / team; we add crore pricing: the market price when the
 * model and its inputs are there (`projected_value`), with the on-field curve alongside. */
export function buildPool(rows: AuctionPoolRow[]): PoolPlayer[] {
  const out: PoolPlayer[] = rows.map((r) => {
    const onfield = Math.max(
      0.3,
      Math.min(
        priceCeiling(r.target_balls),
        PV_BASE * Math.exp(PV_SCALE * pricedValue(r.value, r.value_sd)),
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
      contrib: r.contrib ?? null,
      contrib_bat: r.contrib_bat ?? null,
      contrib_bowl: r.contrib_bowl ?? null,
      balls_faced: r.balls_faced ?? null,
      balls_bowled: r.balls_bowled ?? null,
      p_play: r.p_play ?? null,
      season_value: r.season_value ?? null,
      captain: r.captain_teams && r.captain_teams.length ? r.captain_teams.join(" / ") : null,
      capped: r.capped ?? null,
      prior_share: r.prior_share ?? null,
      p_play_free: r.p_play_free ?? null,
      // Bid plan's P(plays) of a buy reads these (bidplan.py BUY_META_KEYS); null in older exports
      age: r.age ?? null,
      ipl_matches: r.ipl_matches ?? null,
      last_share: r.last_share ?? null,
      captain_ipl_last: r.captain_ipl_last ?? null,
      base_price: base,
      vpc: pv / base,
    };
  });
  out.sort((a, b) => b.projected_value - a.projected_value);
  return out;
}

// ---- the franchises -------------------------------------------------------

/** The ten IPL franchises. They all bid by the same fitted demand model (`DEMAND`): what sets them
 * apart at each lot is their squad by role, overseas places and purse. Mirror of auction.py. */
export const IPL_TEAMS_DEFAULT: { team: string }[] = [
  "CSK", "MI", "RCB", "KKR", "DC", "PBKS", "SRH", "GT", "RR", "LSG",
].map((team) => ({ team }));

export function rng(seed: number): () => number {
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
        .sort((a, b) => retainKey(b) - retainKey(a))
        .slice(0, MINI_RETAIN)
        .map((p) => p.cricsheet_id);
    }
  }
  return out;
}

export interface SimOpts {
  purse: number;
  squadSize: number;
  squadMin?: number; // the squad minimum (18 when absent)
  demand?: Partial<Demand> | null; // overrides of the fitted demand model (replays)
  overseasCap: number;
  trials: number;
  mode: AuctionMode;
  retentions: Record<string, string[]>; // team -> retained cricsheet_ids (editable)
  realPrices: Record<string, number>; // cricsheet_id -> real retention price (cr)
  /** Mega: the retention slabs (capped in order, uncapped): the team's retentions together cost
   * max(the slabs, their salaries) (slabs.ts `slabCharge`). Absent = each costs his salary. */
  retentionSlabs?: { capped: number[]; uncapped: number } | null;
  /** cricsheet_id -> "capped" | "uncapped" at retention (absent = capped) */
  slabHolders?: Record<string, string>;
  /** per team: real retentions outside the pool (too few balls to rate), still charged */
  fixedRetained?: Record<string, SlabHolder[]>;
}

/** The real 2025 retentions as simulator inputs: team → ids (the mega default), id → price, the
 * slab rule and who held which slab, and the real retentions outside the pool. Mirror of
 * auction.py `retention_inputs`. */
export function retentionInputs(data: RetentionData | null | undefined): {
  megaIds: Record<string, string[]>;
  realPrices: Record<string, number>;
  retentionSlabs: { capped: number[]; uncapped: number } | null;
  slabHolders: Record<string, string>;
  fixedRetained: Record<string, SlabHolder[]>;
} {
  const megaIds: Record<string, string[]> = {};
  const realPrices: Record<string, number> = {};
  const slabHolders: Record<string, string> = {};
  const fixedRetained: Record<string, SlabHolder[]> = {};
  for (const [team, rows] of Object.entries(data?.mega ?? {})) {
    megaIds[team] = rows.map((r) => r.cricsheet_id);
    for (const r of rows) {
      realPrices[r.cricsheet_id] = r.price;
      if (r.slab_holder) slabHolders[r.cricsheet_id] = r.slab_holder;
    }
  }
  for (const [team, rows] of Object.entries(data?.unpooled ?? {})) {
    fixedRetained[team] = rows.map((r) => ({ salary: r.salary, slab_holder: r.slab_holder ?? "capped" }));
  }
  return { megaIds, realPrices, retentionSlabs: data?.slabs ?? null, slabHolders, fixedRetained };
}

/** What a team's retentions cost the purse (mega; 0 in a mini auction, where the squad is already
 * paid for) and each retained player's share: with slabs, the team's charge by the slab rule and
 * each player's cost = the charge less the charge without him (keep.py `retention_costs`).
 * Mirror of auction.py `retention_spend`. */
export function retentionSpend(team: string, retained: PoolPlayer[], opts: SimOpts): { total: number; each: number[] } {
  if (opts.mode === "mini") return { total: 0, each: retained.map(() => 0) };
  const sal = retained.map((p, i) => opts.realPrices[p.cricsheet_id] ?? slabCost(i));
  const slabs = opts.retentionSlabs;
  if (!slabs) return { total: sal.reduce((a, b) => a + b, 0), each: sal };
  const hk = opts.slabHolders ?? {};
  const holders: SlabHolder[] = retained.map((p, i) => ({ salary: sal[i], slab_holder: hk[p.cricsheet_id] ?? "capped" }));
  for (const h of opts.fixedRetained?.[team] ?? []) holders.push({ salary: h.salary, slab_holder: h.slab_holder });
  const rules = { retention_slabs: slabs.capped, uncapped_retention_slab: slabs.uncapped };
  const total = holders.length ? slabCharge(holders, rules) : 0;
  const each = retained.map((_, k) => total - slabCharge(holders.filter((_h, j) => j !== k), rules));
  return { total, each };
}

export interface FranchiseBase {
  team: string;
  retained: PoolPlayer[]; // Bid plan's rivals pass squad members carrying  (their expected contribution)
  retainSpend: number;
  retainOverseas: number;
}

export interface TeamState {
  team: string;
  retained: PoolPlayer[]; // Bid plan's rivals pass squad members carrying  (their expected contribution)
  bought: PoolPlayer[];
  boughtPrices: number[]; // price paid per bought player, aligned with `bought`
  spent: number; // auction spend only
  overseas: number; // retained + bought
  counts: Record<Role, number>;
  best: Record<Role, number>; // the best expected contribution a match per role so far
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
  auctioned: number; // how many of them go under the hammer (auctionLots)
  teams: {
    team: string;
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
  teamCfg: { team: string }[],
  opts: SimOpts,
): { bases: FranchiseBase[]; auctionPool: PoolPlayer[] } {
  const byId = new Map(pool.map((p) => [p.cricsheet_id, p]));
  const retainedIds = new Set<string>();
  const bases: FranchiseBase[] = teamCfg.map(({ team }) => {
    const ids = opts.retentions[team] ?? [];
    const retained = ids.map((id) => byId.get(id)).filter((p): p is PoolPlayer => !!p);
    let retainOverseas = 0;
    retained.forEach((p) => {
      retainedIds.add(p.cricsheet_id);
      if (p.is_overseas) retainOverseas++;
    });
    // Mega: retentions draw from the purse by the slab rule. Mini: the squad is already paid for
    // (sunk): retentions are free and the team bids from a small leftover purse.
    const retainSpend = retentionSpend(team, retained, opts).total;
    return { team, retained, retainSpend, retainOverseas };
  });
  const auctionPool = pool.filter((p) => !retainedIds.has(p.cricsheet_id));
  return { bases, auctionPool };
}

// ---- the bidding: a demand model fitted on real auctions ----------------------------------------
//
// Mirror of auction.py (docs/METHODOLOGY.md §7, AUCTION_MATH Part 3; scripts/auction_demand_fit.py →
// config/auction_demand.json). For each team with a place (and an overseas place) and the purse for his
// base price: it bids at all with P = logistic(P0 + P1 ln market + P2 ln base + I_* × its needs); its bid
// is e^(mu + u + SIGMA × Gumbel), u ~ N(0, TAU²) the lot's heat shared by every team, with
// mu = A + C ln market + HINGE max(0, ln(market / 2 cr)) + BASE ln base + ANCHOR ln(last price / market) + MONEY × mean ln(purse per open
// place) + STAGE × share of open places filled + MEGA + NEED ln(1 + places short in his role) + OS ×
// (overseas lot) × open overseas / open places + PPS × (its ln purse per place − the mean) + UP × (his
// expected contribution − its best in his role, ±UP_CLIP); held to its spendable purse; the highest bid
// wins at the next ladder step above the second (the base price when nobody else reaches it).
export interface Demand {
  a: number; c: number; sigma: number; tau: number; p0: number; p1: number; p2: number; base: number;
  anchor: number; money: number; stage: number; mega: number; need: number; os: number; pps: number;
  up: number; i_need: number; i_os: number; i_pps: number; i_up: number; val: number; i_val: number; heat_q: number; tau2: number; hinge: number;
}
/** Shipped: candidate R4 (D7 + the market price above the top base price), refitted on 2019-2026
 * (config/auction_demand.json `params`, 6 decimals). */
export const DEMAND: Demand = {
  a: 0.508317, c: 0.112129, sigma: 0.464998, tau: 0.551503, p0: -1.796694,
  p1: 0.264341, p2: 0.193581, base: 0.090694, anchor: 0.015805, money: 0.655568,
  stage: -0.766261, mega: 0.0, need: 0.179662, os: 1.11955, pps: 1.106038,
  up: 0.007074, i_need: 0.38828, i_os: -0.174691, i_pps: -0.319634, i_up: 0.043653,
  val: 0.0, i_val: 0.0, heat_q: 0.0, tau2: 0.0, hinge: 0.221426,
};
/** Fitted team effects (ln bid; empty unless the fit chose them). */
export const TEAM_EFFECTS: Record<string, number> = {};
/** The squad's usual make-up (median end-of-auction count per role, real squads 2019-2024). */
export const ROLE_TARGETS: Record<Role, number> = { batter: 6.0, bowler: 11.0, all_rounder: 4.0, keeper: 3.0 };
export const UP_CLIP = 15.0;
export const VAL_CLIP = 15.0;
/** the highest base price (cr): the "hinge" term is the market price above it (ln) */
export const LN_TOP_BASE = Math.log(2.0);
const MIN_BASE = 0.3; // cheapest base price (cr) since 2025: reserved per place still needed for the squad minimum
// money within this of a base price counts as enough (a purse is a running sum of bids whose last bit
// can differ between Python and JS). Mirror of auction.py.
const PURSE_EPS = 1e-9;

/** The demand model in force: the shipped constants, overridden by `opts.demand`. */
export function demand(opts: { demand?: Partial<Demand> | null }): Demand {
  const d: Demand = { ...DEMAND };
  for (const [k, v] of Object.entries(opts.demand ?? {})) {
    if (k in d && v !== undefined && v !== null) (d as unknown as Record<string, number>)[k] = Number(v);
  }
  return d;
}

/** The IPL bid increment at a price of x cr: 5 lakh below 1 cr, 10 lakh to 2 cr, 20 lakh to 5 cr, 25 lakh
 * above. Mirror of auction.py `ladder_step`. */
export function ladderStep(x: number): number {
  if (x < 1.0) return 0.05;
  if (x < 2.0) return 0.1;
  if (x < 5.0) return 0.2;
  return 0.25;
}
/** The next ladder price above a bid of x cr. */
export function ladderNext(x: number): number {
  const s = ladderStep(x);
  return Math.round((Math.floor(x / s + 1e-9) + 1) * s * 100) / 100;
}

const fnum = (x: unknown): number | null => (typeof x === "number" && Number.isFinite(x) ? x : null);

/** A squad member's expected contribution a match: `v`, else P(plays) × contribution (0 unrated). */
export function memberValue(p: object): number {
  const r = p as Record<string, unknown>;
  const v = fnum(r.v);
  if (v !== null) return v;
  const c = fnum(r.contrib);
  if (c === null) return 0;
  const pp = fnum(r.p_play);
  return c * (pp === null ? 1 : pp);
}
/** A lot's expected contribution for the upgrade term: P(plays as a free agent) × contribution; null unrated. */
function lotValue(p: object): number | null {
  const r = p as Record<string, unknown>;
  const v = fnum(r.v);
  if (v !== null) return v;
  const c = fnum(r.contrib);
  if (c === null) return null;
  let pp = fnum(r.p_play_free);
  if (pp === null) pp = fnum(r.p_play);
  return c * (pp === null ? 1 : pp);
}

function freshState(b: FranchiseBase): TeamState {
  const counts: Record<Role, number> = { batter: 0, bowler: 0, all_rounder: 0, keeper: 0 };
  const best: Record<Role, number> = { batter: 0, bowler: 0, all_rounder: 0, keeper: 0 };
  for (const p of b.retained) {
    counts[p.role]++;
    best[p.role] = Math.max(best[p.role], memberValue(p));
  }
  return { team: b.team, retained: b.retained, bought: [], boughtPrices: [], spent: 0, overseas: b.retainOverseas, counts, best };
}

/** The order the lots come up in: capped (a row without `capped` counts as capped), then uncapped,
 * each by market price. Mirror of auction.py `lot_sequence`. */
export function lotSequence(lots: PoolPlayer[]): PoolPlayer[] {
  const cmp = (a: PoolPlayer, b: PoolPlayer) =>
    a.projected_value !== b.projected_value ? (a.projected_value > b.projected_value ? -1 : 1) : a.cricsheet_id < b.cricsheet_id ? -1 : a.cricsheet_id > b.cricsheet_id ? 1 : 0;
  const capped = lots.filter((p) => p.capped !== false).sort(cmp);
  const uncapped = lots.filter((p) => p.capped === false).sort(cmp);
  return [...capped, ...uncapped];
}

/** A standard normal draw (Marsaglia's polar method on the seeded uniforms). */
function normal(rand: () => number): number {
  for (;;) {
    const u = 2.0 * rand() - 1.0;
    const v = 2.0 * rand() - 1.0;
    const s = u * u + v * v;
    if (s > 0.0 && s < 1.0) return u * Math.sqrt((-2.0 * Math.log(s)) / s);
  }
}

export type TrialOpts = Pick<SimOpts, "purse" | "squadSize" | "overseasCap"> & {
  mode?: AuctionMode;
  squadMin?: number;
  minBase?: number;
  demand?: Partial<Demand> | null;
};

/** One mock auction. `onSale(player, team index, winning bid, price)` is called for each sale when
 * given (Bid plan reads the winning bid: the price a rival would have paid); a sale in the final
 * squad-minimum pass reports his base price as the bid. Mirror of auction.py `one_trial`. */
export function oneTrial(
  bases: FranchiseBase[],
  auctionPool: PoolPlayer[],
  opts: TrialOpts,
  seed: number,
  onSale?: (player: PoolPlayer, team: number, bestBid: number, price: number) => void,
): TeamState[] {
  const rand = rng(seed);
  const states = bases.map(freshState);
  const dm = demand(opts);
  const sqMax = opts.squadSize;
  const sqMin = opts.squadMin ?? 18;
  const osCap = opts.overseasCap;
  const minBase = opts.minBase ?? MIN_BASE;
  const mega = (opts.mode ?? "mini") === "mega" ? 1.0 : 0.0;
  const teamFx = states.map((st) => TEAM_EFFECTS[st.team] ?? 0.0);
  const filledOf = (st: TeamState) => st.retained.length + st.bought.length;
  const remPurseOf = (i: number) => opts.purse - bases[i].retainSpend - states[i].spent;
  const buy = (i: number, player: PoolPlayer, price: number) => {
    const st = states[i];
    st.bought.push(player);
    st.boughtPrices.push(price);
    st.spent += price;
    st.counts[player.role]++;
    const lv = lotValue(player);
    if (lv !== null) st.best[player.role] = Math.max(st.best[player.role], lv);
    if (player.is_overseas) st.overseas++;
  };

  const order = lotSequence(auctionPool);
  let open0 = 0;
  for (const st of states) open0 += Math.max(0, sqMax - filledOf(st));
  open0 = Math.max(open0, 1);
  const sold = new Set<string>();
  const heat = new Map<string, number>();
  let filled = 0;

  const offer = (player: PoolPlayer) => {
    const pid = player.cricsheet_id;
    if (!heat.has(pid)) {
      // the lot's heat: a bidding war (sd TAU2) with probability HEAT_Q, else quiet (sd TAU)
      const war = rand() < dm.heat_q;
      heat.set(pid, (war ? dm.tau2 : dm.tau) * normal(rand));
    }
    const u = heat.get(pid) as number;
    const base = player.base_price;
    const mk = Math.max(player.projected_value, 1e-6);
    let anchor = fnum((player as PoolPlayer & { anchor_price?: number | null }).anchor_price);
    if (!anchor && player.prior_share) anchor = player.prior_share * opts.purse;
    const lv = lotValue(player);
    const role = player.role;
    const osLot = !!player.is_overseas;
    const elig: number[] = [];
    const spend: number[] = [];
    const lpps: number[] = [];
    for (let i = 0; i < states.length; i++) {
      const st = states[i];
      const open = sqMax - filledOf(st);
      if (open <= 0) continue;
      if (osLot && st.overseas >= osCap) continue;
      const left = remPurseOf(i);
      const sp = left - Math.max(0, sqMin - filledOf(st) - 1) * minBase;
      if (sp < base - PURSE_EPS) continue;
      elig.push(i);
      spend.push(sp);
      lpps.push(Math.log(Math.max(left, minBase) / open));
    }
    if (!elig.length) return;
    let money = 0;
    for (const x of lpps) money += x;
    money = money / lpps.length;
    const lmk = Math.log(mk);
    const lb = Math.log(Math.max(base, 1e-6));
    let lotMu = dm.a + dm.c * lmk + dm.base * lb;
    if (anchor) lotMu += dm.anchor * Math.log(anchor / mk);
    lotMu += dm.money * money + dm.stage * (filled / open0) + dm.mega * mega;
    const val = lv === null ? 0.0 : Math.max(-VAL_CLIP, Math.min(VAL_CLIP, lv));
    lotMu += dm.val * val + dm.hinge * Math.max(0.0, lmk - LN_TOP_BASE);
    const lotI = dm.p0 + dm.p1 * lmk + dm.p2 * lb + dm.i_val * val;
    let bestI = -1;
    let bestBid = 0.0;
    let second = 0.0;
    for (let k = 0; k < elig.length; k++) {
      const i = elig[k];
      const st = states[i];
      const open = sqMax - filledOf(st);
      const xNeed = Math.log1p(Math.max(0.0, ROLE_TARGETS[role] - st.counts[role]));
      const xOs = osLot ? Math.min(osCap - st.overseas, open) / open : 0.0;
      const xPps = lpps[k] - money;
      const xUp = lv === null ? 0.0 : Math.max(-UP_CLIP, Math.min(UP_CLIP, lv - st.best[role]));
      const rIn = rand(); // does it bid at all
      const rE = rand(); // its own view
      const z = lotI + dm.i_need * xNeed + dm.i_os * xOs + dm.i_pps * xPps + dm.i_up * xUp;
      if (rIn >= 1.0 / (1.0 + Math.exp(-z))) continue;
      const mu = lotMu + dm.need * xNeed + dm.os * xOs + dm.pps * xPps + dm.up * xUp + teamFx[i];
      const e = -Math.log(-Math.log(rE > 0.0 ? rE : 1e-12));
      const bid = Math.min(Math.exp(mu + u + dm.sigma * e), spend[k]);
      if (bid > bestBid) {
        second = bestBid;
        bestBid = bid;
        bestI = i;
      } else if (bid > second) {
        second = bid;
      }
    }
    if (bestI < 0 || bestBid < base - PURSE_EPS) return;
    let price = second < base ? base : Math.min(ladderNext(second), bestBid);
    price = Math.max(base, price);
    buy(bestI, player, price);
    sold.add(pid);
    filled++;
    if (onSale) onSale(player, bestI, bestBid, price);
  };

  for (const player of order) offer(player); // the sets
  for (const player of order) if (!sold.has(player.cricsheet_id)) offer(player); // the accelerated round

  // The squad minimum is a rule: a team still short buys the cheapest leftovers at base price.
  const leftovers = order.filter((p) => !sold.has(p.cricsheet_id)).sort((a, b) => a.base_price - b.base_price);
  for (const player of leftovers) {
    let pick = -1;
    let fewest = Infinity;
    for (let i = 0; i < states.length; i++) {
      if (filledOf(states[i]) >= sqMin) continue;
      if (player.is_overseas && states[i].overseas >= osCap) continue;
      if (remPurseOf(i) < player.base_price - PURSE_EPS) continue;
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

/** Lots per open squad place on the real shortlists 2018-2024 (mini: median of 4.56, 4.63, 4.66, 4.32;
 * mega: mean of 3.18, 2.76) and their overseas share (median 0.357). Mirror of auction.py. */
export const LOTS_PER_PLACE: Record<AuctionMode, number> = { mega: 3.0, mini: 4.6 };
export const OVERSEAS_SHARE = 0.357;

/** The lots: the most valuable unretained players (pool order), LOTS_PER_PLACE[mode] × the open squad
 * places of them, at most OVERSEAS_SHARE of those overseas. Mirror of auction.py `auction_lots`. */
export function auctionLots(auctionPool: PoolPlayer[], openPlaces: number, mode: AuctionMode = "mini"): PoolPlayer[] {
  const n = Math.max(1, Math.round((LOTS_PER_PLACE[mode] ?? LOTS_PER_PLACE.mini) * Math.max(openPlaces, 0)));
  const maxOs = Math.round(n * OVERSEAS_SHARE);
  const out: PoolPlayer[] = [];
  let nOs = 0;
  for (const p of auctionPool) {
    if (out.length >= n) break;
    if (p.is_overseas) {
      if (nOs >= maxOs) continue;
      nOs++;
    }
    out.push(p);
  }
  return out;
}

/** The auction's open squad places: squad maximum less the retained, summed over the teams. */
export function openSquadPlaces(bases: { retained: unknown[] }[], squadSize: number): number {
  let t = 0;
  for (const b of bases) t += Math.max(0, squadSize - b.retained.length);
  return t;
}

export function simulateAuction(pool: PoolPlayer[], teamCfg: { team: string }[], opts: SimOpts): SimResult {
  const { bases, auctionPool } = buildFranchises(pool, teamCfg, opts);
  const usePool = auctionLots(auctionPool, openSquadPlaces(bases, opts.squadSize), opts.mode);
  const agg = bases.map((b) => ({
    team: b.team,
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
    const ret = b.retained;
    const costs = retentionSpend(b.team, ret, opts).each;
    ret.forEach((p, i) => {
      outcomes.push({
        cricsheet_id: p.cricsheet_id,
        name: p.name,
        role: p.role,
        is_overseas: p.is_overseas,
        status: "retained",
        team: b.team,
        soldPct: 0,
        avgPrice: costs[i],
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

type ScoutPriced = MarketInputs & {
  value: number;
  value_sd?: number | null;
  ipl_value?: number | null;
  ipl_value_sd?: number | null;
  target_balls?: number | null;
};

/** A Scout row's value on the IPL rating scale and its sd: `ipl_value` / `ipl_value_sd` (the export
 * translates every league's row), else — a row exported before 2026-10-23 — its own `value` /
 * `value_sd`. Mirror of pricing.scout_ipl_value. */
export function scoutIplValue(p: ScoutPriced): [number, number | null | undefined] {
  if (p.ipl_value !== null && p.ipl_value !== undefined) return [p.ipl_value, p.ipl_value_sd];
  return [p.value, p.value_sd];
}

/** A Scout row's estimated IPL price: the market price when the model and the row's market inputs are
 * there (on the row's `price_value` / `price_value_sd`, the value the price recipe takes, which the
 * export sets; else on his value on the IPL scale), else the on-field curve on his value on the IPL
 * scale. Mirror of pricing.scout_price. */
export function scoutPrice(p: ScoutPriced): number {
  const [v, sd] = scoutIplValue(p);
  if (priceModel !== null && "intl_caps" in p) {
    const row = p.price_value === null || p.price_value === undefined ? { ...p, price_value: v, price_value_sd: sd } : p;
    return marketPrice(row).price;
  }
  return iplPrice(v, p.role, sd, p.target_balls);
}
