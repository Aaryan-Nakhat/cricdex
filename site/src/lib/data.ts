// Data layer — fetches the pre-cooked JSON tree under public/data.
// Everything the UI shows is computed offline by scripts/export_site.py
// and refreshed on demand by the GitHub Action; the browser only displays.

import { registerLeagues, type LeagueRegistry } from "./leagues";
import { registerPriceModel, type PriceModel } from "./auction";
import { registerKeepModel, type KeepData } from "./keep";

const DATA_ROOT = `${import.meta.env.BASE_URL}data`;

// A cache-buster token. Bumped by the Refresh button so a manual refresh
// re-pulls JSON past the CDN/browser cache without a hard reload.
let bust = "";
export function bumpCacheBust() {
  bust = `?t=${Date.now()}`;
  cache.clear();
}

/** A file that isn't in this collection's export (e.g. a page with no data for a league yet). */
export class NotAvailableError extends Error {
  constructor(public rel: string) {
    super("Not available for this league yet.");
    this.name = "NotAvailableError";
  }
}

// One promise per file: concurrent callers share a request, and a missing file isn't re-fetched on every mount.
const cache = new Map<string, Promise<unknown>>();

function getJSON<T>(rel: string): Promise<T> {
  const hit = cache.get(rel);
  if (hit) return hit as Promise<T>;
  const p = (async () => {
    let res: Response;
    try {
      res = await fetch(`${DATA_ROOT}/${rel}${bust}`);
    } catch {
      cache.delete(rel); // offline / blocked — let the next attempt retry
      throw new Error("Couldn't reach the data — check your connection and press Refresh.");
    }
    if (res.status === 404) throw new NotAvailableError(rel);
    if (!res.ok) {
      cache.delete(rel);
      throw new Error(`Couldn't load the data (HTTP ${res.status}) — press Refresh to try again.`);
    }
    return (await res.json()) as T;
  })();
  cache.set(rel, p);
  return p;
}

// ---- types ----------------------------------------------------------------

export interface CollectionMeta {
  collection: string;
  data_as_of: string | null;
  /** True when this league's data has stopped updating (e.g. SMAT); show a "stale" badge. */
  stale?: boolean;
  newest_data_anywhere?: string | null;
  n_matches: number;
  n_balls: number;
  n_players: number;
  n_active?: number;
  windows?: string[]; // recomputed time windows available, e.g. ["last3y","last1y","era_impact"]
  window_labels?: Record<string, string>; // window → label, incl. the league's eras ("Impact Player era")
}

/** Identity fields the player-data pass adds (players.json rows, profiles' `identity`). All optional:
 * older exports don't carry them, and every surface falls back gracefully. */
export interface PlayerIdentity {
  display_name?: string | null; // how fans say it ("Virat Kohli")
  full_name?: string | null; // legal full name
  aliases?: string[] | null; // other spellings / scorecard names, all searchable
  capped?: boolean | null; // has played international cricket
  active?: boolean | null;
  retired?: boolean | null;
  country?: string | null; // ISO-3
  team?: string | null;
  batting_hand?: string | null;
  bowling_arm?: string | null;
  bowling_category?: "seam" | "spin" | string | null;
  bowling_style?: string | null;
  primary_role?: string | null;
  /** IPL and international captaincy (data/curated/ipl_captains.json), newest first */
  captaincy?: {
    ipl: { team: string; from: number; to: number; matches: number | null }[];
    international: { country: string; format: string; from: number; to: number }[];
  } | null;
}

/** The name to show a fan: display name when the export has one, else the scorecard name. */
export function displayName(p: { name: string; display_name?: string | null } | null | undefined): string {
  if (!p) return "";
  return (p.display_name && p.display_name.trim()) || p.name;
}

export interface PlayerRow {
  cricsheet_id: string;
  name: string;
  full_name: string;
  display_name?: string | null;
  aliases?: string[] | null;
  capped?: boolean | null;
  retired?: boolean | null;
  batting_hand?: string | null;
  bowling_arm?: string | null;
  bowling_style?: string | null;
  balls_faced: number;
  balls_bowled: number;
  matches: number;
  role: "batter" | "bowler";
  // LLM taxonomy (null until enriched)
  primary_role: string | null;
  bowling_category: string | null;
  batting_position: string | null;
  country: string | null;
  // data-driven activity (per collection = per format)
  first_match_date: string | null;
  last_match_date: string | null;
  active: boolean;
  team: string | null; // current IPL franchise code (null = free agent / non-IPL)
}

export interface RatingRow {
  cricsheet_id: string;
  unique_name: string;
  role: "batter" | "bowler";
  skill: number | null;
  skill_sd: number | null;
  survival_skill: number | null;
  survival_skill_sd: number | null;
  strike_skill: number | null;
  strike_skill_sd: number | null;
  value: number | null;
  /** Posterior sd of `value` — absent in rating files written before it existed. */
  value_sd?: number | null;
  balls: number;
  runs: number;
  display_name?: string | null;
  aliases?: string[] | null;
}

export type LeaderboardRow = Record<string, string | number | null>;

export interface Profile {
  name: string;
  collection: string;
  ids: Record<string, unknown>;
  cricsheet_id: string;
  wikidata: Record<string, unknown> | null;
  bayes: Record<string, unknown> | null;
  career: Record<string, unknown> | null;
  metrics: Record<string, unknown> | null;
  style_twins_batter: Record<string, unknown>[] | null;
  style_twins_bowler: Record<string, unknown>[] | null;
  dismissal_fingerprint: Record<string, unknown> | null;
  taxonomy?: Record<string, string> | null;
  identity?: PlayerIdentity | null;
  activity?: { first_match_date: string | null; last_match_date: string | null; active: boolean } | null;
}

export interface Cohorts {
  co_faced: Record<string, unknown>[];
}

// ---- fetchers -------------------------------------------------------------

export const getCollections = () => getJSON<CollectionMeta[]>("collections.json");

/** The league registry (config/leagues.toml, exported as leagues.json): labels, Scout pools,
 * pricing discounts. Installed for the sync helpers in `./leagues` as soon as it arrives. */
export const getLeagues = () =>
  getJSON<LeagueRegistry>("leagues.json").then((reg) => {
    registerLeagues(reg);
    return reg;
  });
export const getPlayers = (c: string) => getJSON<PlayerRow[]>(`${c}/players.json`);
export const getRatings = (c: string) => getJSON<RatingRow[]>(`${c}/ratings.json`);
export const getLeaderboard = (c: string, slug: string, window?: string) =>
  getJSON<LeaderboardRow[]>(
    `${c}/leaderboards/${slug}${window && window !== "all" ? `.${window}` : ""}.json`,
  );
export const getRecords = (c: string) =>
  getJSON<Record<string, Record<string, unknown>[]>>(`${c}/records.json`);
/** One ground: its condition tables plus `aliases` — other names it has had (spellings, former names). */
export type VenueData = Record<string, Record<string, unknown>[]> & { aliases?: string[] };
export const getVenues = (c: string) => getJSON<Record<string, VenueData>>(`${c}/venues.json`);
export const getProfile = (c: string, cid: string) =>
  getJSON<Profile>(`${c}/profiles/${cid}.json`);

export interface RetentionData {
  mega: Record<string, { cricsheet_id: string; name: string; price: number; slab_holder?: string }[]>;
  /** real retentions outside the pool (too few balls to rate): still charged to the purse */
  unpooled?: Record<string, { name: string; salary: number; slab_holder?: string }[]>;
  /** the cycle's retention slabs (config/competitions.toml); absent in older exports */
  slabs?: { capped: number[]; uncapped: number } | null;
  competition?: string;
}
export const getRetentions = (c: string) => getJSON<RetentionData>(`${c}/retentions.json`);

/** Each rated player's value for the coming season per role, [value, sd] (the auction target only:
 * `<c>/value_now.json`; missing elsewhere and in older exports). */
export type ValueNow = Record<string, { bat?: [number, number]; bowl?: [number, number] }>;
export const getValueNow = (c: string) => getJSON<ValueNow>(`${c}/value_now.json`).catch(() => null);

export interface AuctionPoolRow {
  cricsheet_id: string;
  name: string;
  /** an open eligibility question for the auction's season (ipl_availability.json "unconfirmed") */
  eligibility?: string | null;
  display_name?: string | null;
  aliases?: string[] | null;
  capped?: boolean | null;
  /** League where this player's profile lives. */
  profile_collection?: string | null;
  stale?: boolean;
  /** share of his value's evidence from a stale league (SMAT), and which ("SMAT data to Dec 2024"). */
  stale_share?: number | null;
  stale_note?: string | null;
  value: number; // on the IPL rating scale: his IPL rating and every other league (translated) blended
  /** sd of that value (sources blended by precision, translation uncertainty included); the
   * on-field price uses value − PRICE_CAUTION_SD × value_sd. Absent in older exports (= 0). */
  value_sd?: number | null;
  /** his value for the coming season (the headline): each role moved from the career level by the
   * time-aware model and shrunk by the season-ahead calibration, his better role now (METHODOLOGY
   * §4b / §4c). `value` is the career rating. Absent in older exports. */
  value_now?: number | null;
  value_now_sd?: number | null;
  value_now_role?: "batter" | "bowler" | null;
  /** IPL balls in the role priced: sets the price ceiling (priceCeiling). Absent → 0. */
  target_balls?: number | null;
  role: "batter" | "bowler" | "all_rounder" | "keeper";
  country: string | null;
  is_overseas: boolean;
  team: string | null;
  // cross-league activity (so "active in SA20 but not IPL" is visible)
  last_match_date?: string | null;
  last_ipl?: string | null;
  home_league?: string | null;
  age?: number | null;
  // playing time (METHODOLOGY §6c): runs above replacement per match he plays (both roles at his
  // expected balls), its sd and parts, his expected balls a match, P(plays a match | in a squad) and
  // the expected runs over a season (P × contribution × 14); absent in exports before 2026-10-22
  contrib?: number | null;
  contrib_sd?: number | null;
  contrib_bat?: number | null;
  contrib_bowl?: number | null;
  balls_faced?: number | null;
  balls_bowled?: number | null;
  p_play?: number | null;
  season_value?: number | null;
  // the market price's inputs (auction.ts `marketFeatures`); absent in exports before it
  price_value?: number | null; // his better role's value as the price recipe takes it (pricing.value_input)
  price_value_sd?: number | null; // its sd (missing → value_sd)
  intl_caps?: number | null; // men's T20I + ODI + Test matches
  intl_caps_2y?: number | null; // ... in the two years before the auction
  ipl_balls?: number | null; // IPL balls faced + bowled
  ipl_seasons?: number | null;
  ipl_gap?: number | null; // years from his last IPL match to the auction (null = never)
  // captaincy known before the auction (market-price inputs) and the sides he led last season
  captain_ipl_last?: number | null;
  captain_ipl_seasons?: number | null;
  captain_intl_2y?: number | null;
  captain_teams?: string[] | null;
  /** P(plays a match) as a free agent (playing_time free-agent model) */
  p_play_free?: number | null;
  /** his last IPL price as a share of that season's purse (the bidders' reference price) */
  prior_share?: number | null;
  /** the buy model's inputs (Bid plan, ROADMAP I18) */
  ipl_matches?: number | null;
  last_share?: number | null;
}
/** The auction pool, with the fitted market-price model (`<c>/price_model.json`) installed for
 * `buildPool` / `marketPrice` before the rows arrive (a missing model leaves the on-field curve). */
export const getAuctionPool = (c: string) =>
  Promise.all([
    getJSON<AuctionPoolRow[]>(`${c}/auction_pool.json`),
    getJSON<PriceModel>(`${c}/price_model.json`).catch(() => null),
  ]).then(([rows, model]) => {
    if (model) registerPriceModel(model);
    return rows;
  });

// Per-player cross-league activity, keyed by cricsheet_id, with the chance he plays a match
// (P(plays), METHODOLOGY §6c). Any surface can join on it.
export interface ActivityRow {
  leagues: { league: string; last: string }[];
  last_ipl: string | null;
  last_any: string | null;
  home_league: string | null;
  age: number | null;
  p_play: number | null;
}
export const getActivityIndex = (c: string) =>
  getJSON<Record<string, ActivityRow>>(`${c}/activity_index.json`);

export interface ScoutPlayer {
  cricsheet_id: string;
  name: string;
  display_name?: string | null;
  capped?: boolean | null; // international appearances (absent in older exports)
  /** League where this player's profile lives (non-IPL players have no IPL profile). */
  profile_collection?: string | null;
  data_as_of?: string | null;
  stale?: boolean;
  role: "batter" | "bowler" | "all_rounder" | "keeper";
  bowling_category: string | null;
  batting_position: string | null;
  country: string | null;
  value: number; // his rating in this league on the price-basis side (the better one on the IPL scale)
  /** sd of that rating; absent in older exports (= 0). */
  value_sd?: number | null;
  /** which side `value` is ("bat" | "bowl"); absent in exports before 2026-10-23 */
  value_side?: "bat" | "bowl" | null;
  /** that side on the IPL rating scale (the fitted league translation) and its sd: the price basis
   * (auction.ts `scoutPrice`); absent in exports before 2026-10-23 (then `value` is used). */
  ipl_value?: number | null;
  ipl_value_sd?: number | null;
  /** the market price's value input and its sd (the blend the price recipe was fitted on) */
  price_value?: number | null;
  price_value_sd?: number | null;
  /** IPL balls in the role priced (the better side): sets the price ceiling. Absent → 0. */
  target_balls?: number | null;
  z: number; // standing on own role among the shown players of that role in the tier (mean 0, sd 1)
  balls: number; // exposure in this tier — powers the uncapped-gem flag
  last_match_date: string | null;
  // the market price's inputs (auction.ts `scoutPrice`); absent in exports before it
  is_overseas?: boolean | null;
  age?: number | null;
  intl_caps?: number | null;
  intl_caps_2y?: number | null;
  ipl_balls?: number | null;
  ipl_seasons?: number | null;
  ipl_gap?: number | null;
}
// One list per Scout pool, keyed by the pool's tier (leagues.json: "ipl", "smat", "bbl", …).
export type ScoutIndex = Record<string, ScoutPlayer[]>;
export const getScoutIndex = (c: string) => getJSON<ScoutIndex>(`${c}/scout_index.json`);
export const getCohorts = (c: string, cid: string) =>
  getJSON<Cohorts>(`${c}/cohorts/${cid}.json`);

// ---- matchups (batter vs bowler) + pace/spin splits ------------------------
export interface BatterMatchup {
  bowler: string;
  balls: number;
  runs: number;
  sr: number;
  dot_pct: number;
  outs: number;
}
export interface BowlerMatchup {
  batter: string;
  balls: number;
  runs: number;
  sr: number;
  dot_pct: number;
  outs: number;
}
export interface SplitSide {
  balls: number;
  runs: number;
  sr: number;
  outs: number;
  out_rate: number;
}
export interface Matchups {
  as_batter: BatterMatchup[];
  as_bowler: BowlerMatchup[];
  splits: { vs_seam?: SplitSide; vs_spin?: SplitSide } | null;
}
export const getMatchups = (c: string, cid: string) =>
  getJSON<Matchups>(`${c}/matchups/${cid}.json`);

// ---- phase specialists (powerplay / middle / death) ------------------------
export interface PhaseBatter {
  name: string;
  balls: number;
  runs: number;
  sr: number;
}
export interface PhaseBowler {
  name: string;
  balls: number;
  runs: number;
  wickets: number;
  econ: number;
}
export interface PhaseBoard {
  batters: PhaseBatter[];
  bowlers: PhaseBowler[];
}
export type PhaseData = Record<"powerplay" | "middle" | "death", PhaseBoard>;
export const getPhase = (c: string) => getJSON<PhaseData>(`${c}/phase.json`);

// ---- partnerships (batter pairs) -------------------------------------------
export interface Partnership {
  a: string;
  b: string;
  a_cid: string | null;
  b_cid: string | null;
  a_display?: string | null;
  b_display?: string | null;
  innings: number;
  runs: number;
  balls: number;
  sr: number;
  best: number;
  avg: number;
  fifties: number;
  hundreds: number;
}
export const getPartnerships = (c: string) =>
  getJSON<{ pairs: Partnership[] }>(`${c}/partnerships.json`);

// ---- aging curves (performance vs age) -------------------------------------
export interface AgingBat {
  age: number;
  sr: number;
  average: number | null;
  n: number;
}
export interface AgingBowl {
  age: number;
  economy: number;
  strike_rate: number | null;
  n: number;
}
export interface AgingPlayer {
  // A player's own season-by-season trajectory per discipline (empty when under 3 seasons).
  batting: { age: number; sr: number }[];
  bowling: { age: number; economy: number }[];
}
export interface AgingData {
  batting: AgingBat[];
  bowling: AgingBowl[];
  players: Record<string, AgingPlayer>;
}
export const getAging = (c: string) => getJSON<AgingData>(`${c}/aging.json`);

/** Keep or release (keep.json): the competition's rules + sources, every squad player with
 * salary / value / tags / age / last season, and the pool free agents' tags. */
export const getKeep = async (c: string) => {
  const d = await getJSON<KeepData>(`${c}/keep.json`);
  // the retention model the calls come from (keep.ts `assess`)
  registerKeepModel(d.keep_model ?? null);
  return d;
};
/** Bid plan: every franchise's default plan, each seeing the others' (bidplan_rivals.json, bidplan.py
 * `rival_plan_bids`), or null when not exported (the rivals then bid by the demand model alone). */
export const fetchBidplanRivals = (c: string) =>
  getJSON<{ teams: import("./bidplan").RivalBids }>(`${c}/bidplan_rivals.json`)
    .then((x) => x.teams)
    .catch(() => null);

/** Bid plan: the official auction list once it is published (data/curated/ipl_auction_register.json, copied by the
 * export as `<c>/auction_register.json`), else null: the plan then infers the pool. */
export const getAuctionRegister = (c: string) =>
  getJSON<import("./bidplan").RegisterEntry[]>(`${c}/auction_register.json`).catch(() => null);
