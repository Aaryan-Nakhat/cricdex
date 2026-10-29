// Parity harness: runs the canonical TS Auction + Scout logic on the exported
// JSON and dumps a compact result to stdout. The Python port
// (src/cricdex/web_parity) must reproduce this byte-for-byte —
// test_scripts/test_web_parity.py runs this and diffs. Run via:
//   node --no-warnings --experimental-strip-types scripts/parity_dump.ts
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import {
  buildPool,
  defaultRetentions,
  retentionInputs,
  retentionSpend,
  simulateAuction,
  IPL_TEAMS_DEFAULT,
  marketFeatures,
  marketPrice,
  calibrate,
  linkShare,
  registerPriceModel,
  scoutPrice,
  iplPrice,
  type MarketInputs,
  type PoolPlayer,
  type PriceModel,
  type PriceTier,
  type Role,
} from "../src/lib/auction.ts";
import { similarTo, gemThreshold, isGem } from "../src/lib/scout.ts";
import type { ScoutPlayer } from "../src/lib/data.ts";
import { registerLeagues, scoutPools, type LeagueRegistry } from "../src/lib/leagues.ts";

const here = dirname(fileURLToPath(import.meta.url));
// CRICDEX_SITE_DATA points the harness at another export (a scratch one), as it does the Python side
const dataDir = join(process.env.CRICDEX_SITE_DATA || join(here, "..", "public", "data"), "ipl");
const load = (f: string) => JSON.parse(readFileSync(join(dataDir, f), "utf8"));

// The market-price model: the test passes config/price_model.json in CRICDEX_PRICE_MODEL_JSON so
// both sides price with the same coefficients; else the exported copy (if any).
const modelPath = process.env.CRICDEX_PRICE_MODEL_JSON || join(dataDir, "price_model.json");
let model: PriceModel | null = null;
try {
  model = JSON.parse(readFileSync(modelPath, "utf8")) as PriceModel;
} catch {
  model = null;
}
registerPriceModel(model);
const pool = buildPool(load("auction_pool.json"));
const ret = load("retentions.json");
const scout = load("scout_index.json");
// The league registry: the test passes the Python payload (config/leagues.toml) in
// CRICDEX_LEAGUES_JSON so both sides price with the same table; else the exported copy.
const leaguesPath = process.env.CRICDEX_LEAGUES_JSON || join(dataDir, "..", "leagues.json");
const registry = JSON.parse(readFileSync(leaguesPath, "utf8")) as LeagueRegistry;
registerLeagues(registry);
// every registry Scout pool the export has (a pool added since the last export is skipped)
const tiers = scoutPools(registry)
  .map((l) => l.tier as PriceTier)
  .filter((t) => t in scout);
const gemTier = registry.gem_tier;

const ri = retentionInputs(ret);
const megaIds = ri.megaIds;

const teams = IPL_TEAMS_DEFAULT;
const retentions = defaultRetentions(pool, teams, "mega", megaIds);
const res = simulateAuction(pool, teams, {
  purse: 120,
  squadSize: 25,
  overseasCap: 8,
  trials: 40,
  mode: "mega",
  retentions,
  realPrices: ri.realPrices,
  retentionSlabs: ri.retentionSlabs,
  slabHolders: ri.slabHolders,
  fixedRetained: ri.fixedRetained,
});

// Scout: deterministic pick = lexicographically-first IPL id.
const sel = [...(scout.ipl as ScoutPlayer[])].sort((a, b) => a.cricsheet_id.localeCompare(b.cricsheet_id))[0];
const scoutOut: Record<string, { id: string; sim: number; price: number }[]> = {};
for (const tier of tiers) {
  scoutOut[tier] = similarTo(sel, scout[tier] as ScoutPlayer[], sel.role, "").map((p) => ({
    id: p.cricsheet_id,
    sim: p.sim,
    price: scoutPrice(p),
  }));
}
// Same-type matching + slot + country filters: every bowling all-rounder with a known country and slot
// (lexicographic id order), each against every pool, in all three country modes with the pick's own slot.
// The domestic gem pool assumes the pick's country for players with none on file, as Scout.tsx does.
const typedPicks = (scout.ipl as ScoutPlayer[])
  .filter((p) => p.role === "all_rounder" && p.bowling_category && p.country && p.batting_position)
  .sort((a, b) => a.cricsheet_id.localeCompare(b.cricsheet_id))
  .slice(0, 4);
const scoutTyped: Record<string, string[]> = {};
for (const pick of typedPicks) {
  for (const tier of tiers) {
    for (const mode of ["same", "overseas", "all"] as const) {
      const fb = tier === gemTier ? pick.country : null;
      scoutTyped[`${pick.cricsheet_id}|${tier}|${mode}`] = similarTo(pick, scout[tier] as ScoutPlayer[], "", "same", 8, {
        country: mode,
        fallbackCountry: fb,
      }).map((p) => `${p.cricsheet_id}:${p.sim}`);
    }
  }
}
const gemPool = (gemTier && scout[gemTier] ? scout[gemTier] : []) as ScoutPlayer[];
const gemMedian = gemThreshold(gemPool);
const gems = gemPool.filter((p) => isGem(p, gemMedian)).map((p) => p.cricsheet_id);

// mirrored in test_web_parity.py: value, role, tier, value_sd
const ESTIMATE_CASES: [number, string, number | null, number | null][] = [
  [0, "batter", 0, 0],
  [13.6, "batter", 2.75, 6926],
  [59.7, "batter", 12.5, 449],
  [27.7, "keeper", 12.4, 471],
  [27.4, "keeper", 4.9, 163],
  [40.0, "all_rounder", 9.0, null],
  [-30, "bowler", 7.0, 0],
  [10, "bowler", null, 600],
];
// mirrored in test_web_parity.py: market-model inputs on fixed rows (incl. missing fields)
const MARKET_CASES: [MarketInputs, "mega" | "mini", number][] = [
  [{ price_value: 13.6, value_sd: 2.75, role: "batter", is_overseas: false, intl_caps: 555, age: 38.1, ipl_balls: 8400, ipl_seasons: 19, ipl_gap: 0.55, target_balls: 6926, captain_ipl_last: 0, captain_ipl_seasons: 10, captain_intl_2y: 0, prior_share: 0.175, prior_years: 2, prior_retained: true, wiki_views: 2500000.0 }, "mini", 125],
  [{ price_value: 59.7, value_sd: 12.5, role: "batter", is_overseas: false, intl_caps: 0, age: 15.7, ipl_balls: 449, ipl_seasons: 2, ipl_gap: 0.55, target_balls: 449 }, "mini", 125],
  [{ price_value: 23.2, value_sd: 2.7, role: "bowler", overseas: false, intl_caps: 210, age: 32.9, ipl_balls: 3100, ipl_seasons: 12, ipl_gap: 0.55, target_balls: 3000, captain_ipl_last: 1, captain_ipl_seasons: 1, captain_intl_2y: 1, prior_share: 0.9, prior_years: 9, prior_retained: false, wiki_views: 41234.5 }, "mega", 120],
  [{ price_value: 6.0, value_sd: 9.0, role: "all_rounder", is_overseas: true, intl_caps: 40, age: 27.2, ipl_balls: 0, ipl_seasons: 0, ipl_gap: null, target_balls: 0 }, "mini", 125],
  [{ price_value: null, role: "keeper", is_overseas: false, intl_caps: null, age: null, ipl_balls: null, ipl_seasons: null, ipl_gap: 3.2 }, "mega", 90],
  [{ price_value: -45, value_sd: 20, role: "bowler", is_overseas: true, intl_caps: 3, age: 41, ipl_balls: 120, ipl_seasons: 1, ipl_gap: 9.5, target_balls: 120, prior_share: 0, prior_years: 3, prior_retained: true }, "mini", 125],
  [{ price_value: 18.5, value_sd: 3.1, role: "keeper", is_overseas: true, intl_caps: 160, intl_caps_2y: 30, age: 33.5, ipl_balls: 2600, ipl_seasons: 9, ipl_gap: 0.6, target_balls: 2500, prior_share: 0.0001, prior_years: 1, wiki_views: 0 }, "mega", 120],
  // resold a season after his last auction (the resale rule, 2026-10-29): a sale and a retention
  [{ price_value: 3.0, value_sd: 6.0, role: "batter", is_overseas: false, intl_caps: 0, age: 20.4, ipl_balls: 90, ipl_seasons: 1, ipl_gap: 0.6, target_balls: 90, prior_share: 0.1136, prior_years: 1, prior_retained: false }, "mini", 125],
  [{ price_value: 12.0, value_sd: 3.0, role: "bowler", is_overseas: true, intl_caps: 60, intl_caps_2y: 20, age: 23.0, ipl_balls: 1500, ipl_seasons: 4, ipl_gap: 0.6, target_balls: 1500, prior_share: 0.108, prior_years: 1, prior_retained: true }, "mini", 125],
  // the price input's own sd (2026-10-23: the pool's value_sd is the translated blend's)
  [{ price_value: 21.0, price_value_sd: 9.0, value_sd: 2.0, role: "batter", is_overseas: false, intl_caps: 4, age: 24.0, ipl_balls: 300, ipl_seasons: 2, ipl_gap: 0.6, target_balls: 300 }, "mini", 125],
  [{ price_value: 21.0, price_value_sd: null, value_sd: 2.0, role: "batter", is_overseas: false, intl_caps: 4, age: 24.0, ipl_balls: 300, ipl_seasons: 2, ipl_gap: 0.6, target_balls: 300 }, "mini", 125],
];
// mirrored in test_web_parity.py (SCOUT_CASES): Scout prices on fixed rows
const SCOUT_CASES: Parameters<typeof scoutPrice>[0][] = [
  { value: 30.0, value_sd: 8.0, ipl_value: 9.5, ipl_value_sd: 12.0, role: "batter", target_balls: 0 },
  { value: 30.0, value_sd: 8.0, ipl_value: 9.5, ipl_value_sd: 12.0, price_value: 13.0, price_value_sd: 10.3, role: "batter", target_balls: 0, is_overseas: false, intl_caps: 0, age: 23.0, ipl_balls: 0, ipl_seasons: 0, ipl_gap: null },
  { value: 12.0, value_sd: 5.0, ipl_value: 4.0, ipl_value_sd: 9.0, role: "bowler", target_balls: 0, is_overseas: true, intl_caps: 12, age: 27.0, ipl_balls: 0, ipl_seasons: 0, ipl_gap: null },
  { value: 12.0, value_sd: 5.0, role: "bowler", target_balls: 40 },
];
// mirrored in test_web_parity.py: the calibration (knots + hi_slope) and the link on fixed parts
const CAL_PART = {
  intercept: 0,
  coef: {},
  calibration: { x: [-4, -3, -1.5], y: [-4.2, -3.1, -2.2], hi_slope: 0.4 },
  shift: -0.1,
};
const CAL_CASES = [-6, -4, -3.5, -1.5, -1.0, 0.5];
const SAT_PART = { intercept: 0, coef: {}, link: { kind: "sat" as const, cap_share: 0.3 } };
const LINK_CASES = [-40, -5, -1, 0, 2, 30];
// mirrored in test_web_parity.py: a team's retentions under the slab rule (KKR's 2025 list: four
// capped and two uncapped at retention, 57 cr of salaries, 69 cr charged)
const SLAB_OPTS = {
  purse: 120, squadSize: 25, overseasCap: 8, trials: 1, mode: "mega" as const, retentions: {},
  realPrices: { a: 13, b: 12, c: 12, d: 12, e: 4 } as Record<string, number>,
  retentionSlabs: { capped: [18, 14, 11, 18, 14], uncapped: 4 },
  slabHolders: { a: "capped", b: "capped", c: "capped", d: "capped", e: "uncapped" } as Record<string, string>,
  fixedRetained: { KKR: [{ salary: 4, slab_holder: "uncapped" }] },
};
const SLAB_PLAYERS = ["a", "b", "c", "d", "e"].map((id) => ({ cricsheet_id: id }) as unknown as PoolPlayer);
const out = {
  calCases: CAL_CASES.map((x) => calibrate(CAL_PART, x)),
  linkCases: LINK_CASES.map((x) => linkShare(SAT_PART, x)),
  slabSpend: [
    retentionSpend("KKR", SLAB_PLAYERS, SLAB_OPTS),
    retentionSpend("KKR", SLAB_PLAYERS.slice(0, 3), SLAB_OPTS),
    retentionSpend("XYZ", SLAB_PLAYERS, { ...SLAB_OPTS, retentionSlabs: null }),
    retentionSpend("KKR", SLAB_PLAYERS, { ...SLAB_OPTS, mode: "mini" as const }),
  ],
  retentions,
  // a mini auction's default retentions: each team's top 18 by expected season value
  retentionsMini: defaultRetentions(pool, teams, "mini", megaIds),
  poolSize: res.poolSize,
  auctioned: res.auctioned,
  teams: res.teams.map((t) => ({
    team: t.team,
    retained: t.retained,
    avgBought: t.avgBought,
    avgSpend: t.avgSpend,
    avgValue: t.avgValue,
    avgOverseas: t.avgOverseas,
  })),
  marquee: res.marquee.map((m) => ({
    id: m.player.cricsheet_id,
    winners: m.winners.map((w) => ({ team: w.team, pct: w.pct })),
  })),
  outcomes: res.outcomes.map((o) => ({
    id: o.cricsheet_id,
    status: o.status,
    team: o.team,
    soldPct: o.soldPct,
    avgPrice: o.avgPrice,
    winners: o.winners.map((w) => ({ team: w.team, pct: w.pct })),
  })),
  sampleDraft: res.sampleDraft.map((s) => ({
    team: s.team,
    bought: s.bought.map((p) => p.cricsheet_id),
    spent: s.spent,
    overseas: s.overseas,
  })),
  scoutPick: sel.cricsheet_id,
  scoutTiers: tiers,
  scout: scoutOut,
  scoutTypedPicks: typedPicks.map((p) => p.cricsheet_id),
  scoutTyped,
  gemMedian,
  gems,
  // the cautious price on fixed inputs (value, role, tier, sd), including a missing sd
  scoutCases: SCOUT_CASES.map((p) => scoutPrice(p)),
  estCases: ESTIMATE_CASES.map(([v, role, sd, balls]) => iplPrice(v, role as Role, sd, balls)),
  // the market model on fixed inputs (features + price + P(bought)); null when there is no model
  marketCases: model
    ? MARKET_CASES.map(([row, cycle, purse]) => ({
        features: marketFeatures(row, cycle, (model as PriceModel).price.pv_max),
        ...marketPrice(row, { cycle, purse }),
      }))
    : null,
  poolPrices: pool.map((p) => [p.cricsheet_id, p.projected_value, p.onfield_value, p.p_bought, p.captain]),
};
process.stdout.write(JSON.stringify(out));
