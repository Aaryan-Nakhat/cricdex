// Keep or release: the franchise retention calculator. EXACT mirror of
// src/cricdex/web_parity/keep.py — same constants, same formulas, same sentences — so the page
// and `cricdex keep` show identical numbers (test_scripts/test_keep_parity.py runs both).
// The method in plain words: docs/METHODOLOGY.md §10.
import { hasMarketInputs, iplPrice, marketPrice, type MarketInputs, type Role } from "./auction.ts";
import { slabCharge } from "./slabs.ts";

// The default plan keeps a player when the chance a franchise keeps a player like him is at least
// KEEP_CALL (the backtest's decision rule); within BORDER_BAND of it the call is Borderline.
export const KEEP_CALL = 0.5;
export const BORDER_BAND = 0.15;
// The cheapest a squad slot can be filled for (the lowest base-price band, cr).
export const MIN_SLOT_PRICE = 0.3;

export type Tag = "keeper" | "opener" | "death" | "spinner" | "overseas";
export const DEFAULT_NEEDS: Record<"keeper" | "opener" | "death" | "spinner", number> = {
  keeper: 2,
  opener: 3,
  death: 3,
  spinner: 3,
};
export const TAG_ORDER: Tag[] = ["keeper", "opener", "death", "spinner", "overseas"];
export const TAG_LETTER: Record<Tag, string> = { keeper: "k", opener: "o", death: "d", spinner: "s", overseas: "x" };
export const TAG_LABEL: Record<Tag, string> = {
  keeper: "Wicketkeepers",
  opener: "Openers",
  death: "Death bowlers",
  spinner: "Spinners",
  overseas: "Overseas",
};

export type Rec = "keep" | "release" | "borderline";

export interface KeepForm {
  bat?: [number, number, number]; // balls, runs, outs
  bowl?: [number, number, number]; // balls, runs conceded, wickets
}
export interface KeepPlayer {
  id: string | null;
  name: string;
  team: string;
  salary: number;
  acquired?: string | null;
  overseas: boolean;
  country?: string | null;
  role: Role;
  value: number | null;
  value_sd: number | null;
  target_balls: number;
  balls: number;
  age: number | null;
  tags: string;
  form: KeepForm | null;
  withdrawn?: string | boolean | null;
  trade?: { from: string; salary_before_cr: number | null } | null;
  profile?: string | null;
  // the market price's inputs (auction.ts `marketFeatures`); absent in exports before it
  price_value?: number | null;
  intl_caps?: number | null;
  intl_caps_2y?: number | null;
  ipl_balls?: number | null;
  ipl_seasons?: number | null;
  ipl_gap?: number | null;
  captain_ipl_last?: number | null;
  captain_ipl_seasons?: number | null;
  captain_intl_2y?: number | null;
  captain_teams?: string[] | null; // the IPL sides he captained last season
  // the market's last verdict on him (auction.ts `marketFeatures`)
  prior_share?: number | null;
  prior_years?: number | null;
  prior_retained?: boolean | null;
  /** a 2025 mega-auction retention still with his franchise, charged by the retention slabs */
  slab_holder?: "capped" | "uncapped" | null;
  // playing time (METHODOLOGY §6c; export_site PT_KEYS): runs above replacement per match he plays
  // (both roles at his expected balls), its parts and balls, P(plays a match) in his squad and the
  // expected runs over a season; absent in exports before 2026-10-22
  contrib?: number | null;
  contrib_sd?: number | null;
  contrib_bat?: number | null;
  contrib_bowl?: number | null;
  balls_faced?: number | null;
  balls_bowled?: number | null;
  p_play?: number | null;
  /** his P(plays) as a free agent (the free-agent model), for Bid plan when he is released */
  p_play_free?: number | null;
  season_value?: number | null;
  /** A hand-written note on the salary (e.g. an overseas fee cap). Display only. */
  note?: string | null;
  /** share of his value's evidence from a stale league (SMAT), and which ("SMAT data to Dec 2024") */
  stale_share?: number | null;
  stale_note?: string | null;
  /** Form forecast's 3-season outlook (export_site via scout/forecast.py `keep_outlook`). */
  forecast?: KeepForecast | null;
  /** IPL seasons he played for this franchise before the deadline (the retention model) */
  seasons_here?: number | null;
  /** his first IPL side is this franchise (the retention model) */
  home_grown?: boolean | null;
}
export interface KeepForecast {
  role: "batter" | "bowler";
  seasons: number[];
  median: number[];
  avg3: number;
  flag: string;
  p_regular_last: number;
  level?: number | null;
  text: string;
}
export interface LeagueForm {
  season: number;
  bat_sr: number;
  bowl_econ: number;
}
export interface KeepRules {
  purse: number;
  squad_min: number;
  squad_max: number;
  overseas_max: number;
  max_retained: number;
  max_overseas_retained: number;
  replacements_retainable: boolean;
  /** what a kept player costs the purse: "salary" | "slabs" (retentionCosts); absent = salary */
  retained_cost?: string;
  retention_slabs?: number[];
  uncapped_retention_slab?: number;
}

// ---- formatting (identical rounding to keep.py: half up on |x| scaled) ----

export function fmtNum(x: number, d = 1): string {
  const n = Math.floor(Math.abs(x) * 10 ** d + 0.5 + 1e-9);
  let s = String(n);
  if (d > 0) {
    s = s.padStart(d + 1, "0");
    s = s.slice(0, -d) + "." + s.slice(-d);
  }
  return (x < 0 && n !== 0 ? "-" : "") + s;
}

/** A crore amount: two decimals below 1 cr (0.30), one above (13.3), no trailing ".0". */
export function cr(x: number): string {
  let s = fmtNum(x, Math.abs(x) < 1 ? 2 : 1);
  if (s.endsWith(".0")) s = s.slice(0, -2);
  return s === "0.00" ? "0" : s;
}

/** A salary as written: up to two decimals, trailing zeros dropped (13.25, 0.3, 18). */
export function crExact(x: number): string {
  let s = fmtNum(x, 2);
  if (s.includes(".")) s = s.replace(/0+$/, "").replace(/\.$/, "");
  return s;
}

/** Left-to-right sum (keep.py's `fsum`). */
function fsum(xs: number[]): number {
  let t = 0;
  for (const x of xs) t += x;
  return t;
}

// ---- per player ----

export const hasTag = (p: { tags: string }, tag: Tag) => p.tags.includes(TAG_LETTER[tag]);

export const FORECAST_FLAG: Record<string, string> = {
  hold: "holds",
  improve: "improves",
  hold_then_decline: "holds, then declines",
  decline: "declines",
};

/** "+5" / "-3" / "0" (Math.round: half up). Mirror of keep.py `signed`. */
export function signed(x: number): string {
  const r = Math.round(x);
  return r === 0 ? "0" : r > 0 ? `+${r}` : String(r);
}

/** The "3-season outlook" (Form forecast, METHODOLOGY §11). Mirror of keep.py `forecast_note`. */
export function forecastNote(p: KeepPlayer): string {
  const f = p.forecast;
  if (!f) return "";
  const s = f.seasons;
  const meds = f.median.map(signed).join(" / ");
  const pr = Math.round(100 * f.p_regular_last);
  return `${meds} (${s[0]}-${String(s[s.length - 1]).slice(2)}) · ${FORECAST_FLAG[f.flag] ?? f.flag} · ${pr}% a regular in ${s[s.length - 1]}`;
}

/** His age and the Form forecast's shape, no rule of thumb. Mirror of keep.py `outlook`. */
export function outlook(p: KeepPlayer): string {
  const a = p.age === null || p.age === undefined ? "Age unknown" : `${Math.floor(p.age)} years old`;
  const f = p.forecast;
  if (!f) return `${a}; too few balls for a forecast.`;
  return `${a}; the Form forecast ${FORECAST_FLAG[f.flag] ?? f.flag}.`;
}

export function formNote(p: KeepPlayer, form: LeagueForm | null): string {
  const f = p.form;
  if (!f || !form) return "";
  const bits: string[] = [];
  const bat = f.bat;
  const bowl = f.bowl;
  const showBat = !!bat && bat[0] >= 30 && p.role !== "bowler";
  const showBowl = !!bowl && bowl[0] >= 30 && p.role !== "batter" && p.role !== "keeper";
  if (showBat && bat) {
    const sr = (100 * bat[1]) / bat[0];
    bits.push(`SR ${fmtNum(sr, 0)} v ${fmtNum(form.bat_sr, 0)} (${bat[0]} balls)`);
  }
  if (showBowl && bowl) {
    const econ = (6 * bowl[1]) / bowl[0];
    bits.push(`econ ${fmtNum(econ, 1)} v ${fmtNum(form.bowl_econ, 1)}, ${bowl[2]} wkts (${bowl[0]} balls)`);
  }
  if (bits.length === 0) return "";
  return `${form.season}: ` + bits.join("; ");
}

export interface Assessment {
  /** market price on the cautious estimate (the on-field curve when no market model / inputs) */
  price: number | null;
  price_central: number | null;
  /** the on-field curve's price: what his play alone is worth (cautious estimate) */
  onfield: number | null;
  /** chance a franchise buys him if released (market model), else null */
  p_bought: number | null;
  /** the IPL sides he captained last season, else null (the "Captain" badge) */
  captain: string | null;
  surplus: number | null;
  /** the chance a franchise keeps a player like him (the retention model), null without one */
  p_keep: number | null;
  /** the default plan keeps him (p_keep ≥ KEEP_CALL; true without a model) */
  default_keep: boolean;
  /** no ball-by-ball record: `price` is the market model's prior (NO_DATA_LABEL), not a rating */
  no_data: boolean;
  outlook: string;
  form_note: string;
  /** the 3-season outlook line ("" without a forecast) and its three-season average */
  forecast_note: string;
  forecast_avg3: number | null;
  rec: Rec;
  reason: string;
  /** what keeping him costs the purse (his salary, or for a slab holder what releasing him frees) */
  cost: number;
}

/** The IPL sides he captained last season ("RCB"), from the export's `captain_teams`, or null
 * (the "Captain" badge; captaincy is in the market price). Mirror of keep.py `captain_label`. */
export function captainLabel(p: { captain_teams?: string[] | null }): string | null {
  const teams = p.captain_teams ?? [];
  return teams.length ? teams.join(" / ") : null;
}

// A rating that rests at least this much on a league whose data has stopped (SMAT on Cricsheet ends
// in Dec 2024) says so in the reason (issue I7). Mirror of keep.py.
export const STALE_REASON_MIN = 0.1;

/** " 85% of his rating rests on SMAT data to Dec 2024 (stale)." or "". Mirror of keep.py `stale_sentence`. */
export function staleSentence(p: { stale_share?: number | null; stale_note?: string | null }): string {
  const share = p.stale_share ?? 0;
  if (!p.stale_note || share < STALE_REASON_MIN) return "";
  return ` ${Math.round(100 * share)}% of his rating rests on ${p.stale_note} (stale).`;
}

// A squad player with no ball-by-ball record anywhere (no Cricsheet match): shown in place of his
// value, and his price is the market model's prior for a player like him (issue I6). Mirror of keep.py.
export const NO_DATA_LABEL = "no match data — priced from the market";

/** Who the market prior is for, in words. Mirror of keep.py `no_data_kind`. */
export function noDataKind(p: { overseas: boolean; intl_caps?: number | null }): string {
  if (p.overseas) return "an overseas player";
  return (p.intl_caps ?? 0) > 0 ? "a capped Indian" : "an uncapped Indian";
}

// ---- what keeping a player costs the purse (keep.py: `retained_cost`, the retention slabs) ----

export const usesSlabs = (rules: Partial<KeepRules>) => rules.retained_cost === "slabs";

// `slabCharge` lives in slabs.ts (the Auction room charges retentions the same way).
export { slabCharge };

/** What the kept players cost the purse. Mirror of keep.py `purse_charged`. */
export function purseCharged(kept: Pick<KeepPlayer, "salary" | "slab_holder">[], rules: Partial<KeepRules>): number {
  if (!usesSlabs(rules)) return fsum(kept.map((p) => Number(p.salary)));
  const holders = kept.filter((p) => p.slab_holder);
  const rest = fsum(kept.filter((p) => !p.slab_holder).map((p) => Number(p.salary)));
  return rest + (holders.length ? slabCharge(holders, rules) : 0);
}

/** player key → what keeping him costs the purse: his salary, or for a slab holder what releasing
 * him alone would free. Mirror of keep.py `retention_costs`. */
export function retentionCosts(squad: KeepPlayer[], rules: Partial<KeepRules>): Record<string, number> {
  const out: Record<string, number> = {};
  for (const p of squad) out[playerKey(p)] = Number(p.salary);
  if (!usesSlabs(rules)) return out;
  const holders = squad.filter((p) => p.slab_holder);
  if (!holders.length) return out;
  const full = slabCharge(holders, rules);
  for (const p of holders) {
    const k = playerKey(p);
    out[k] = full - slabCharge(holders.filter((q) => playerKey(q) !== k), rules);
  }
  return out;
}

export function costSentence(p: KeepPlayer, cost: number): string {
  const salary = Number(p.salary);
  if (!p.slab_holder || Math.abs(cost - salary) < 0.005) return "";
  return ` One of ${p.team}'s 2025 retentions, charged to the purse at the retention slabs: keeping him costs ${cr(cost)} cr, not his ${crExact(salary)} cr salary.`;
}

// ---- the chance a franchise keeps him (keep.py: `keep_features`, `keep_probability`) ----

export interface KeepModel {
  intercept: number;
  coef: Record<string, number>; // feature → coefficient, in the order they are summed
  fitted?: string;
  trained_on?: number[];
}
let keepModel: KeepModel | null = null;
/** Install the fitted retention model (data.ts `getKeep` does this from keep.json; so do the parity
 * harnesses). */
export function registerKeepModel(m: KeepModel | null): void {
  keepModel = m;
}
export function getKeepModel(): KeepModel | null {
  return keepModel;
}

/** The retention model's inputs. Mirror of keep.py `keep_features`. */
export function keepFeatures(
  market: number,
  cost: number,
  mega: boolean,
  forecastAvg3: number | null | undefined,
  forecastPRegular: number | null | undefined,
  captainHere: boolean,
  seasonsHere: number,
  homeGrown: boolean,
  cappedIndian: boolean,
  overseas: boolean,
  age: number | null | undefined,
  iplBalls: number | null | undefined,
  boughtPrev: boolean,
  pPlay: number | null | undefined = null,
  contrib: number | null | undefined = null,
): Record<string, number> {
  const c = cost && cost > 0 ? cost : 1e-3;
  const lr = Math.log(Math.max(market, 1e-3) / c);
  const mg = mega ? 1 : 0;
  const hasAge = age !== null && age !== undefined;
  const hasPlay = pPlay !== null && pPlay !== undefined && contrib !== null && contrib !== undefined;
  return {
    log_ratio: lr,
    mega: mg,
    forecast: forecastAvg3 !== null && forecastAvg3 !== undefined ? forecastAvg3 / 10 : 0,
    forecast_regular: forecastPRegular !== null && forecastPRegular !== undefined ? forecastPRegular : 0,
    no_forecast: forecastAvg3 !== null && forecastAvg3 !== undefined ? 0 : 1,
    captain_here: captainHere ? 1 : 0,
    seasons_here: Math.log1p(Math.max(seasonsHere || 0, 0)),
    home_grown: homeGrown ? 1 : 0,
    capped_indian: cappedIndian ? 1 : 0,
    overseas: overseas ? 1 : 0,
    age: hasAge ? ((age as number) - 28) / 5 : 0,
    age_over_33: hasAge ? Math.max(0, (age as number) - 33) / 3 : 0,
    ipl_balls: Math.log1p(Math.max(iplBalls || 0, 0)) / 5,
    bought_prev: boughtPrev ? 1 : 0,
    log_cost: Math.log(c),
    mega_x_log_ratio: mg * lr,
    p_play: hasPlay ? (pPlay as number) : 0,
    play_value: hasPlay ? (pPlay as number) * (contrib as number) : 0,
    no_play: hasPlay ? 0 : 1,
  };
}

/** σ(intercept + Σ coef × feature). Mirror of keep.py `keep_probability`. */
export function keepProbability(f: Record<string, number>, model: KeepModel): number {
  let t = model.intercept;
  for (const [k, c] of Object.entries(model.coef)) {
    const x = f[k];
    if (x === undefined) throw new Error(`keep model feature "${k}" is unknown`);
    t += c * x;
  }
  return 1 / (1 + Math.exp(-t));
}

/** Keep / Borderline / Release from the chance he is kept. Mirror of keep.py `call_of`. */
export function callOf(pKeep: number): Rec {
  if (pKeep >= KEEP_CALL + BORDER_BAND) return "keep";
  if (pKeep < KEEP_CALL - BORDER_BAND) return "release";
  return "borderline";
}

function ties(p: KeepPlayer): string[] {
  const team = p.team || "";
  const out: string[] = [];
  if (team && (p.captain_teams ?? []).includes(team)) out.push(`captained ${team} last season`);
  if (p.home_grown) out.push("home-grown");
  const n = Math.trunc(p.seasons_here ?? 0);
  if (n >= 1) out.push(`${n} season${n === 1 ? "" : "s"} with ${team}`);
  return out;
}

export function assess(p: KeepPlayer, form: LeagueForm | null = null, cost: number | null = null): Assessment {
  const salary = cost === null ? Number(p.salary) : Number(cost);
  const base = {
    outlook: outlook(p),
    form_note: formNote(p, form),
    forecast_note: forecastNote(p),
    forecast_avg3: p.forecast?.avg3 ?? null,
    captain: captainLabel(p),
    cost: salary,
  };
  const mkt = hasMarketInputs(p);
  let lead = "";
  let price: number;
  let central: number;
  let onfield: number | null;
  let pBought: number | null = null;
  let noData = false;
  if (p.value === null || p.value === undefined) {
    if (!mkt) {
      return {
        ...base,
        price: null,
        price_central: null,
        onfield: null,
        p_bought: null,
        surplus: null,
        p_keep: null,
        default_keep: true,
        no_data: false,
        rec: "borderline",
        reason: `Not enough balls in our data to rate him: decide on scouting (he costs ${crExact(salary)} cr).${costSentence(p, salary)}`,
      };
    }
    // no ball-by-ball record at all: a sourced prior, never a made-up rating (keep.py)
    const mk = marketPrice(p as unknown as MarketInputs);
    price = mk.price;
    central = mk.high;
    onfield = null;
    noData = true;
    // an auction price well above the prior is market evidence our data can't see: say so
    const above = p.acquired === "auction" && Number(p.salary) > central;
    lead = `${NO_DATA_LABEL[0].toUpperCase()}${NO_DATA_LABEL.slice(1)}: ${noDataKind(p)} with no match record fetches about ${cr(price)} cr (${cr(central)} in the top quarter) against ${crExact(salary)}${above ? "; franchises bid him well above that at the auction, so they saw something our data can't." : "."}`;
  } else {
    onfield = iplPrice(p.value, p.role, p.value_sd, p.target_balls);
    price = onfield;
    central = iplPrice(p.value, p.role, 0, p.target_balls);
    if (mkt) {
      // median market price; the upper figure is the upper quartile of what players like him fetch,
      // on his central value
      const mk = marketPrice(p as unknown as MarketInputs);
      price = mk.price;
      pBought = mk.p_bought;
      central = marketPrice({ ...(p as unknown as MarketInputs), value_sd: 0, price_value_sd: 0 }).high;
    }
  }
  const model = keepModel;
  const fc = p.forecast;
  const t = ties(p);
  const tieText = t.length ? ` (${t.join(", ")})` : "";
  let rec: Rec;
  let reason: string;
  let pKeep: number | null;
  if (model === null) {
    rec = "borderline";
    reason = `${lead ? lead + " " : ""}Worth about ${cr(price)} cr at auction against ${crExact(salary)} to keep; no retention model is loaded, so no call.`;
    pKeep = null;
  } else {
    const f = keepFeatures(
      price,
      salary,
      false,
      fc?.avg3,
      fc?.p_regular_last,
      (p.captain_teams ?? []).includes(p.team || ""),
      Math.trunc(p.seasons_here ?? 0),
      !!p.home_grown,
      (p.intl_caps ?? 0) > 0 && !p.overseas,
      !!p.overseas,
      p.age,
      p.ipl_balls,
      p.acquired === "auction",
      p.p_play,
      p.contrib,
    );
    pKeep = keepProbability(f, model);
    rec = callOf(pKeep);
    const pct = Math.floor(100 * pKeep + 0.5);
    reason = `${lead ? lead + " " : ""}Worth about ${cr(price)} cr at auction against ${crExact(salary)} to keep${tieText}: franchises kept ${pct}% of players like him at their retention deadlines (2018-2026).`;
  }
  reason += staleSentence(p);
  reason += costSentence(p, salary);
  return {
    ...base,
    price,
    price_central: central,
    onfield,
    p_bought: pBought,
    surplus: price - salary,
    p_keep: pKeep,
    default_keep: pKeep === null ? true : pKeep >= KEEP_CALL,
    no_data: noData,
    rec,
    reason,
  };
}

export const playerKey = (p: { id: string | null; team: string; name: string }) => p.id || `name:${p.team}:${p.name}`;

// ---- squad ----

export interface MarketPlayer {
  id: string;
  name: string;
  value: number;
  /** runs above replacement per match (null in an export before it) */
  contrib: number | null;
  price: number;
  overseas: boolean;
  tags: string;
  /** null = a free agent; else the team our call releases him from */
  from_team: string | null;
}

/** How good a player is for a role gap: his contribution per match, else (an export before it) his
 * value. Mirror of keep.py `level`. */
export function level(p: { contrib?: number | null; value?: number | null }): number | null {
  if (p.contrib !== null && p.contrib !== undefined) return Number(p.contrib);
  return p.value ?? null;
}

/** The replacement market: priced auction-pool players with no franchise, with their tags.
 * `pool` = buildPool(auction_pool.json) rows (projected_value = the price). */
export function freeAgents(
  pool: { cricsheet_id: string; name: string; value: number; contrib?: number | null; projected_value: number; is_overseas: boolean; team: string | null }[],
  tags: Record<string, string>,
): MarketPlayer[] {
  const out: MarketPlayer[] = [];
  for (const r of pool) {
    if (r.team) continue;
    let t = tags[r.cricsheet_id] ?? "";
    if (r.is_overseas && !t.includes("x")) t += "x";
    out.push({ id: r.cricsheet_id, name: r.name, value: r.value, contrib: r.contrib ?? null, price: r.projected_value, overseas: !!r.is_overseas, tags: t, from_team: null });
  }
  return out;
}

/** The auction pool a team will shop in: today's free agents plus the players our calls send back
 * from the other squads (their Release recommendations), each at our estimated price. */
export function marketFor(
  team: string,
  players: KeepPlayer[],
  pool: Parameters<typeof freeAgents>[0],
  tags: Record<string, string>,
  form: LeagueForm | null = null,
  rules: Partial<KeepRules> | null = null,
): MarketPlayer[] {
  const out = freeAgents(pool, tags);
  const costs: Record<string, number> = {};
  if (rules !== null) {
    const teams: Record<string, KeepPlayer[]> = {};
    for (const p of players) (teams[p.team || ""] ??= []).push(p);
    for (const t of Object.keys(teams).sort()) Object.assign(costs, retentionCosts(teams[t], rules));
  }
  for (const p of players) {
    if (p.team === team || p.value === null || p.value === undefined) continue;
    const k = playerKey(p);
    const a = assess(p, form, Object.prototype.hasOwnProperty.call(costs, k) ? costs[k] : null);
    if (a.default_keep) continue;
    let t = p.tags || "";
    if (p.overseas && !t.includes("x")) t += "x";
    out.push({ id: playerKey(p), name: p.name, value: p.value, contrib: p.contrib ?? null, price: a.price as number, overseas: !!p.overseas, tags: t, from_team: p.team });
  }
  return out;
}

export type Decision = "keep" | "release";
export interface AssessedPlayer extends KeepPlayer, Assessment {
  key: string;
  kept: boolean;
  overridden: boolean;
  /** released by the default plan to fit the squad limit or overseas cap, else null */
  auto_release: AutoRelease | null;
}
export interface Gap {
  tag: Tag;
  label: string;
  target: number;
  kept: number;
  gap: number;
  ref_value: number;
  ref_from_release: boolean;
  picks: { id: string; name: string; price: number; value: number; from_team: string | null }[];
  cost: number;
  short: number;
}
export interface SquadResult {
  players: AssessedPlayer[];
  kept: number;
  released: number;
  overseas_kept: number;
  salary_kept: number;
  /** what the kept players cost the purse (salaries, or retention slabs; purseCharged) */
  purse_charged: number;
  salary_released: number;
  purse: number;
  purse_left: number;
  slots_left: number;
  overseas_slots_left: number;
  gaps: Gap[];
  replacement_cost: number;
  purse_after_replacements: number;
  to_min_after_replacements: number;
  warnings: string[];
}

/** Who goes first when the default plan is over a limit: Borderline before Keep, then the lowest
 * chance a franchise keeps him (an unpriced player first), then the key. Mirror of keep.py `_fit_order`. */
function fitOrder(a: AssessedPlayer, b: AssessedPlayer): number {
  const ta = a.rec === "borderline" ? 0 : 1;
  const tb = b.rec === "borderline" ? 0 : 1;
  if (ta !== tb) return ta - tb;
  const r = (p: AssessedPlayer) => (p.p_keep === null ? -Infinity : p.p_keep);
  const ra = r(a);
  const rb = r(b);
  if (ra !== rb) return ra < rb ? -1 : 1;
  return a.key < b.key ? -1 : a.key > b.key ? 1 : 0;
}

/** Make the default plan legal (mirror of keep.py `fit_to_rules`): release kept overseas Borderline
 * players, lowest chance kept first (a Keep only once no Borderline is left), until the overseas
 * cap holds; then the same for the squad maximum. A player the user decided on is never moved. */
export function fitToRules(players: AssessedPlayer[], rules: KeepRules): void {
  let sqMax = rules.squad_max;
  if (rules.max_retained) sqMax = Math.min(sqMax, rules.max_retained);
  let osMax = rules.overseas_max;
  if (rules.max_overseas_retained) osMax = Math.min(osMax, rules.max_overseas_retained);
  const passes: [AutoRelease, number, boolean][] = [
    ["overseas", osMax, true],
    ["squad", sqMax, false],
  ];
  for (const [kind, limit, osOnly] of passes) {
    let count = players.filter((p) => p.kept && (!osOnly || p.overseas)).length;
    if (count <= limit) continue;
    const cands = players
      .filter((p) => p.kept && !p.overridden && (p.rec === "borderline" || p.rec === "keep") && (!osOnly || p.overseas))
      .sort(fitOrder);
    for (const p of cands) {
      if (count <= limit) break;
      p.kept = false;
      p.auto_release = kind;
      p.reason +=
        kind === "overseas" ? ` Released to fit the ${limit}-overseas cap.` : ` Released to fit the ${limit}-player squad limit.`;
      count--;
    }
  }
}

export type AutoRelease = "overseas" | "squad" | "open";

export function evaluate(
  squad: KeepPlayer[],
  market: MarketPlayer[],
  rules: KeepRules,
  decisions: Record<string, Decision> = {},
  needs: Partial<Record<Tag, number>> = {},
  form: LeagueForm | null = null,
): SquadResult {
  const costs = retentionCosts(squad, rules);
  const players: AssessedPlayer[] = squad.map((p) => {
    const key = playerKey(p);
    const a = assess(p, form, costs[key]);
    const d = Object.prototype.hasOwnProperty.call(decisions, key) ? decisions[key] : undefined;
    const ok = d === "keep" || d === "release";
    const kept = ok ? d === "keep" : a.default_keep;
    return { ...p, ...a, key, kept, overridden: ok, auto_release: null };
  });
  fitToRules(players, rules);
  const kept = players.filter((p) => p.kept);
  const released = players.filter((p) => !p.kept);
  const salaryKept = fsum(kept.map((p) => Number(p.salary)));
  const charged = purseCharged(kept, rules);
  const overseasKept = kept.filter((p) => p.overseas).length;
  const purse = Number(rules.purse);
  const purseLeft = purse - charged;
  const slotsLeft = rules.squad_max - kept.length;
  const overseasSlots = rules.overseas_max - overseasKept;

  const overseasNow = players.filter((p) => p.overseas).length;
  const target: Record<Tag, number> = { ...DEFAULT_NEEDS, overseas: Math.min(rules.overseas_max, overseasNow) };
  for (const [k, v] of Object.entries(needs)) {
    if (k in target && typeof v === "number" && v >= 0) target[k as Tag] = Math.trunc(v);
  }

  const have: Record<Tag, number> = Object.fromEntries(
    TAG_ORDER.map((t) => [t, kept.filter((p) => hasTag(p, t)).length]),
  ) as Record<Tag, number>;
  const picked = new Set<string>();
  let room = Math.max(slotsLeft, 0);
  let osRoom = Math.max(overseasSlots, 0);
  const gaps: Gap[] = [];
  for (const tag of TAG_ORDER) {
    const need = Math.max(0, target[tag] - have[tag]);
    // the bar: the best player the team released with this tag, by contribution per match
    const relVals = released.filter((p) => hasTag(p, tag) && level(p) !== null).map((p) => level(p) as number);
    const ref = relVals.length ? Math.max(...relVals) : 0.0;
    const picks: MarketPlayer[] = [];
    if (need > 0) {
      const lv = (c: MarketPlayer) => level(c) ?? -Infinity;
      const cands = market.filter((c) => c.tags.includes(TAG_LETTER[tag]) && lv(c) >= ref && !picked.has(c.id));
      cands.sort((a, b) => a.price - b.price || (level(b) ?? 0) - (level(a) ?? 0) || (a.id < b.id ? -1 : a.id > b.id ? 1 : 0));
      for (const c of cands) {
        if (picks.length >= need || room <= 0) break;
        if (c.overseas && osRoom <= 0) continue;
        picks.push(c);
        picked.add(c.id);
        room -= 1;
        if (c.overseas) osRoom -= 1;
        for (const t of TAG_ORDER) if (c.tags.includes(TAG_LETTER[t])) have[t] += 1;
      }
    }
    gaps.push({
      tag,
      label: TAG_LABEL[tag],
      target: target[tag],
      kept: kept.filter((p) => hasTag(p, tag)).length,
      gap: need,
      ref_value: ref,
      ref_from_release: relVals.length > 0,
      picks: picks.map((c) => ({ id: c.id, name: c.name, price: c.price, value: c.value, from_team: c.from_team })),
      cost: fsum(picks.map((c) => c.price)),
      short: need - picks.length,
    });
  }
  const replacementCost = fsum(gaps.map((g) => g.cost));
  const nPicks = gaps.reduce((s, g) => s + g.picks.length, 0);
  const toMin = Math.max(0, rules.squad_min - kept.length - nPicks);

  const warnings: string[] = [];
  if (kept.length > rules.squad_max) warnings.push(`Keeping ${kept.length}: over the ${rules.squad_max}-player squad limit.`);
  if (overseasKept > rules.overseas_max)
    warnings.push(`Keeping ${overseasKept} overseas players: over the cap of ${rules.overseas_max}.`);
  const mr = rules.max_retained || 0;
  if (mr && kept.length > mr) warnings.push(`Keeping ${kept.length}: the rules allow ${mr}.`);
  const mo = rules.max_overseas_retained || 0;
  if (mo && overseasKept > mo) warnings.push(`Keeping ${overseasKept} overseas: the rules allow ${mo}.`);
  if (purseLeft < 0) warnings.push(`Kept players cost more than the ${cr(purse)} cr purse by ${cr(-purseLeft)} cr.`);
  else if (purseLeft - replacementCost < toMin * MIN_SLOT_PRICE)
    warnings.push(
      `After the replacements there isn't enough purse to reach ${rules.squad_min} players at ${cr(MIN_SLOT_PRICE)} cr each.`,
    );
  for (const g of gaps)
    if (g.short > 0)
      warnings.push(
        `${g.label}: only ${g.picks.length} of ${g.gap} found in the pool at that level (or no squad / overseas room left).`,
      );

  return {
    players,
    kept: kept.length,
    released: released.length,
    overseas_kept: overseasKept,
    salary_kept: salaryKept,
    purse_charged: charged,
    salary_released: fsum(released.map((p) => Number(p.salary))),
    purse,
    purse_left: purseLeft,
    slots_left: slotsLeft,
    overseas_slots_left: overseasSlots,
    gaps,
    replacement_cost: replacementCost,
    purse_after_replacements: purseLeft - replacementCost,
    to_min_after_replacements: toMin,
    warnings,
  };
}

/** The table as CSV rows (same columns as keep.py's `to_csv_rows`). */
export function toCsvRows(res: SquadResult): string[][] {
  const head = [
    "player", "team", "role", "overseas", "age", "acquired", "salary_cr", "value", "value_sd",
    "cost_cr", "price_cr", "onfield_cr", "p_bought", "surplus_cr", "p_keep", "recommendation", "decision", "auto_release",
    "reason", "outlook", "form", "outlook_3y_avg", "outlook_3y",
  ];
  const rows = [head];
  for (const p of res.players) {
    rows.push([
      p.name,
      p.team,
      p.role,
      p.overseas ? "yes" : "no",
      p.age === null || p.age === undefined ? "" : String(Math.floor(p.age)),
      p.acquired || "",
      fmtNum(Number(p.salary), 2),
      p.value === null || p.value === undefined ? "" : fmtNum(p.value, 1),
      p.value_sd === null || p.value_sd === undefined ? "" : fmtNum(p.value_sd, 1),
      fmtNum(Number(p.cost), 2),
      p.price === null ? "" : fmtNum(p.price, 2),
      p.onfield === null ? "" : fmtNum(p.onfield, 2),
      p.p_bought === null ? "" : fmtNum(p.p_bought, 2),
      p.surplus === null ? "" : fmtNum(p.surplus, 2),
      p.p_keep === null ? "" : fmtNum(p.p_keep, 2),
      p.rec,
      p.kept ? "keep" : "release",
      p.auto_release ?? "",
      p.reason,
      p.outlook,
      p.form_note,
      p.forecast_avg3 === null ? "" : fmtNum(p.forecast_avg3, 1),
      p.forecast_note,
    ]);
  }
  return rows;
}

/** CSV text (RFC 4180 quoting). */
export function toCsv(rows: string[][]): string {
  const q = (s: string) => (/[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s);
  return rows.map((r) => r.map(q).join(",")).join("\n") + "\n";
}

// ---- exported data (keep.json) ----

export interface CompetitionSource {
  about: string;
  status: "official" | "reported";
  title: string;
  url: string;
  date: string | null;
  note: string;
}
export interface CompetitionInfo {
  key: string;
  name: string;
  league: string;
  season: number;
  cycle: "mega" | "mini";
  currency: string;
  unit: string;
  retention_deadline: string;
  auction_date: string;
  auction_venue: string;
  purse: number;
  squad_min: number;
  squad_max: number;
  overseas_max: number;
  max_retained: number;
  max_overseas_retained: number;
  rtm_cards: number;
  retained_cost: string;
  retention_slabs?: number[];
  uncapped_retention_slab?: number;
  replacements_retainable: boolean;
  overseas_fee_cap: number;
  min_purse_spend_share: number;
  assumed: string[];
  source: CompetitionSource[];
  rules: KeepRules;
}
export interface KeepData {
  competition: CompetitionInfo;
  squads_source: string | null;
  salary_source: string | null;
  changes_source: string | null;
  changes: { kind: string; name: string; from?: string; to?: string; team?: string; salary_cr?: number; date?: string }[];
  purse_check: {
    source: string | null;
    /** the source for `slab` (2025 retention slabs the purse still counts; issue I6) */
    slab_source?: string | null;
    teams: Record<string, { published: number; ours: number; slab?: number }>;
  };
  unmatched: { team: string; name: string }[];
  form: LeagueForm | null;
  death_rule: { share: number; min_balls: number };
  teams: string[];
  players: KeepPlayer[];
  pool_tags: Record<string, string>;
  /** the retention model (config/keep_model.json); absent in older exports (no calls then) */
  keep_model?: KeepModel | null;
}
