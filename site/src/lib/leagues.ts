// The league registry, as exported from config/leagues.toml into `data/leagues.json` by
// scripts/export_site.py. Labels, Scout pools, pricing discounts and pool membership all come from
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
  discount: number | null; // value removed before comparing with IPL value
  calibrated: boolean | null; // false = discount borrowed by analogy, not yet fitted
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
  tiers: Record<string, { discount: number; calibrated: boolean }>;
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

/** The value discount of a strength tier. Throws for a tier the registry doesn't define — a wrong
 * price must never be shown silently (the Python port raises KeyError the same way). */
export function tierDiscount(tier: string): number {
  const t = current?.tiers[tier];
  if (!t) throw new Error(`unknown price tier "${tier}" — is leagues.json loaded?`);
  return t.discount;
}

/** The Scout look-alike pools, in display order. */
export function scoutPools(reg: LeagueRegistry | null = current): LeagueInfo[] {
  return (reg?.leagues ?? []).filter((l) => l.scout_pool && l.tier).sort((a, b) => a.order - b.order);
}
