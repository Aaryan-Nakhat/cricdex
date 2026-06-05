// Data layer — fetches the pre-cooked JSON tree under public/data.
// Everything the UI shows is computed offline by scripts/export_site.py
// and re-cooked nightly by the GitHub Action; the browser only displays.

const DATA_ROOT = `${import.meta.env.BASE_URL}data`;

// A cache-buster token. Bumped by the Refresh button so a manual refresh
// re-pulls JSON past the CDN/browser cache without a hard reload.
let bust = "";
export function bumpCacheBust() {
  bust = `?t=${Date.now()}`;
  cache.clear();
}

const cache = new Map<string, unknown>();

async function getJSON<T>(rel: string): Promise<T> {
  const key = rel;
  if (cache.has(key)) return cache.get(key) as T;
  const res = await fetch(`${DATA_ROOT}/${rel}${bust}`);
  if (!res.ok) throw new Error(`${rel}: ${res.status}`);
  const data = (await res.json()) as T;
  cache.set(key, data);
  return data;
}

// ---- types ----------------------------------------------------------------

export interface CollectionMeta {
  collection: string;
  data_as_of: string | null;
  n_matches: number;
  n_balls: number;
  n_players: number;
  n_active?: number;
  windows?: string[]; // recomputed time windows available, e.g. ["last3y","last1y"]
}

export interface PlayerRow {
  cricsheet_id: string;
  name: string;
  full_name: string;
  balls_faced: number;
  balls_bowled: number;
  matches: number;
  role: "batter" | "bowler";
  // Gemini taxonomy (null until enriched)
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
  balls: number;
  runs: number;
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
  activity?: { first_match_date: string | null; last_match_date: string | null; active: boolean } | null;
}

export interface Cohorts {
  co_faced: Record<string, unknown>[];
}

// ---- fetchers -------------------------------------------------------------

export const getCollections = () => getJSON<CollectionMeta[]>("collections.json");
export const getMeta = (c: string) => getJSON<CollectionMeta>(`${c}/meta.json`);
export const getPlayers = (c: string) => getJSON<PlayerRow[]>(`${c}/players.json`);
export const getRatings = (c: string) => getJSON<RatingRow[]>(`${c}/ratings.json`);
export const getLeaderboard = (c: string, slug: string, window?: string) =>
  getJSON<LeaderboardRow[]>(
    `${c}/leaderboards/${slug}${window && window !== "all" ? `.${window}` : ""}.json`,
  );
export const getRecords = (c: string) =>
  getJSON<Record<string, Record<string, unknown>[]>>(`${c}/records.json`);
export const getVenues = (c: string) =>
  getJSON<Record<string, Record<string, Record<string, unknown>[]>>>(`${c}/venues.json`);
export const getProfile = (c: string, cid: string) =>
  getJSON<Profile>(`${c}/profiles/${cid}.json`);

export interface RetentionData {
  mega: Record<string, { cricsheet_id: string; name: string; price: number }[]>;
}
export const getRetentions = (c: string) => getJSON<RetentionData>(`${c}/retentions.json`);

export interface AuctionPoolRow {
  cricsheet_id: string;
  name: string;
  value: number;
  role: "batter" | "bowler" | "all_rounder" | "keeper";
  country: string | null;
  is_overseas: boolean;
  team: string | null;
}
export const getAuctionPool = (c: string) => getJSON<AuctionPoolRow[]>(`${c}/auction_pool.json`);

export interface ScoutPlayer {
  cricsheet_id: string;
  name: string;
  role: "batter" | "bowler" | "all_rounder" | "keeper";
  bowling_category: string | null;
  batting_position: string | null;
  country: string | null;
  value: number;
  z: number; // skill standing within the tier (mean 0, sd 1)
  balls: number; // exposure in this tier — powers the uncapped-gem flag
  last_match_date: string | null;
}
export interface ScoutIndex {
  ipl: ScoutPlayer[];
  smat: ScoutPlayer[];
  bbl: ScoutPlayer[];
  sa20: ScoutPlayer[];
  cpl: ScoutPlayer[];
  blast: ScoutPlayer[];
}
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
