// Parity harness for the player-row FilterBar. Runs the canonical TS
// `applyFilters` (src/lib/filters.ts) on a fixed fixture + filter cases and
// dumps the surviving ids per case to stdout. The Python port
// (src/cricdex/common/filters.py) must reproduce this — test_scripts/
// test_filters_parity.py runs this and diffs. Run via:
//   node --no-warnings --experimental-strip-types scripts/filters_parity_dump.ts
import { applyFilters, defaultMinMatches, type Filters } from "../src/lib/filters.ts";

// A small, hand-built fixture exercising every gate. `id` is just a label.
const fixture: Record<string, unknown>[] = [
  { id: "a", matches: 50, active: true, primary_role: "batter", bowling_category: null, batting_position: "opener", country: "IND", first_match_date: "2012-04-01", last_match_date: "2024-05-01" },
  { id: "b", matches: 5, active: true, primary_role: "batter", bowling_category: null, batting_position: "middle", country: "IND", first_match_date: "2022-04-01", last_match_date: "2024-05-01" },
  { id: "c", matches: 80, active: false, primary_role: "bowler", bowling_category: "spin", batting_position: "tailender", country: "AUS", first_match_date: "2008-04-01", last_match_date: "2016-05-01" },
  { id: "d", matches: 30, active: true, primary_role: "bowler", bowling_category: "seam", batting_position: "lower", country: "ENG", first_match_date: "2015-04-01", last_match_date: "2023-05-01" },
  { id: "e", matches: 25, active: false, primary_role: "allrounder", bowling_category: "seam", batting_position: "finisher", country: "RSA", first_match_date: "2010-04-01", last_match_date: "2019-05-01" },
  { id: "f", matches: 40, active: true, primary_role: "wk_batter", bowling_category: null, batting_position: "no3", country: "IND", first_match_date: "2013-04-01", last_match_date: "2025-05-01" },
  { id: "g", matches: 0, active: true, primary_role: "batter", bowling_category: null, batting_position: "opener", country: null, first_match_date: null, last_match_date: null },
];

const base: Filters = {
  minMatches: 0, role: "", bowling: "", position: "", country: "",
  activity: "all",
};

const cases: Record<string, Filters> = {
  empty: base,
  min20: { ...base, minMatches: 20 },
  active: { ...base, activity: "active" },
  retired: { ...base, activity: "retired" },
  batters: { ...base, role: "batter" },
  spin: { ...base, bowling: "spin" },
  openers: { ...base, position: "opener" },
  india: { ...base, country: "IND" },
  combo: { ...base, minMatches: 20, activity: "active", role: "bowler", country: "ENG" },
};

const out: Record<string, string[]> = {};
for (const [name, f] of Object.entries(cases)) {
  out[name] = applyFilters(fixture, f).map((r) => String(r.id));
}

// default min-matches on boards of different depth (all-time vs a one-season window)
const depths: Record<string, Record<string, unknown>[]> = {
  fixture,
  season: [{ matches: 17 }, { matches: 9 }, { matches: 3 }],
  short: [{ matches: 2 }],
  none: [],
};
const minDefaults: Record<string, number> = {};
for (const [name, rows] of Object.entries(depths)) minDefaults[name] = defaultMinMatches(rows);

process.stdout.write(JSON.stringify({ fixture, cases, survivors: out, depths, minDefaults }));
