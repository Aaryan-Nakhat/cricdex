// The league registry, as exported from config/leagues.toml into `data/leagues.json` by
// scripts/export_site.py. Labels, Scout pools, each league's fitted translation onto the IPL and pool
// membership all come from
// here, so adding a league is a TOML entry, never a frontend change. No imports: the parity harness
// (scripts/parity_dump.ts) loads this module under Node too.

export type ScoutGroup = "peers" | "uncapped" | "overseas";

export interface LeagueInfo {
  key: string; // collection id (site folder, `?c=` value)
  name: string; // display label
  short: string; // abbreviation ("SMAT", "BBL")
  gender: string;
  kind: string; // league | domestic | international | mixed
  country: string;
  tier: string | null; // strength tier (scout_index.json key, pricing key)
  /** How its ratings carry over to the IPL, per role: IPL rating ≈ a + b × league rating, with a
   * translation sd and the players seen in both (config/league_translation.json); null for the
   * auction target and a league not fitted yet. Display only: prices come translated in the data. */
  translation?: Record<"batter" | "bowler", { a: number; b: number; tsd: number; pairs: number }> | null;
  export: boolean;
  active: boolean;
  order: number;
  scout_pool: boolean;
  scout_group: ScoutGroup | null;
  scout_title: string | null;
  scout_subtitle: string | null;
  draftable: boolean;
  gem_pool: boolean;
  auction_pool: boolean;
  auction_target: boolean;
}

export interface LeagueRegistry {
  schema: number;
  tiers: Record<string, { group: string }>; // the pooling group of the translation fit
  leagues: LeagueInfo[];
  auction: {
    target: string | null;
    target_tier: string | null;
    eligible_nationalities: string[]; // allow-list (empty = every nation not excluded)
    excluded_nationalities: string[]; // deny-list, wins over the allow-list
  };
  gem_tier: string | null;
  windows?: Record<string, number>; // time windows a key may carry ("last1y" → 365 days)
}

let current: LeagueRegistry | null = null;

/** Install the loaded registry (data.ts `getLeagues` does this; so does the parity harness). */
export function registerLeagues(reg: LeagueRegistry): void {
  current = reg;
}

export function leaguesLoaded(): boolean {
  return current !== null;
}

function find(key: string): LeagueInfo | undefined {
  if (!current) return undefined;
  // a time window (`ipl_last1y`) reads as its league; the windows come from the registry
  const suffix = Object.keys(current.windows ?? {}).find((w) => key.endsWith(`_${w}`));
  const base = suffix ? key.slice(0, -(suffix.length + 1)) : key;
  return current.leagues.find((l) => l.key === base);
}

/** Display label for a collection key (the key itself until the registry has loaded). */
export function leagueLabel(key: string): string {
  return find(key)?.name ?? key;
}

/** Abbreviation for a collection key ("indian_domestic_male" → "SMAT"). */
export function leagueShort(key: string): string {
  return find(key)?.short ?? key;
}

/** What a league rating of `at` becomes on the IPL scale, per role (null when not fitted). Mirror of
 * cricdesk.scout.translation.summary, for copy. */
export function translatedAt(info: LeagueInfo, at = 10): { batter: number; bowler: number } | null {
  const t = info.translation;
  if (!t) return null;
  const r = (x: number) => Math.round(x * 10) / 10;
  return { batter: r(t.batter.a + t.batter.b * at), bowler: r(t.bowler.a + t.bowler.b * at) };
}

/** The Scout look-alike pools, in display order. */
export function scoutPools(reg: LeagueRegistry | null = current): LeagueInfo[] {
  return (reg?.leagues ?? []).filter((l) => l.scout_pool && l.tier).sort((a, b) => a.order - b.order);
}
