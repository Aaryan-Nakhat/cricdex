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
  simulateAuction,
  estValue,
  IPL_TEAMS_DEFAULT,
  marketFeatures,
  marketPrice,
  registerPriceModel,
  scoutPrice,
  type MarketInputs,
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

const megaIds: Record<string, string[]> = {};
const realPrices: Record<string, number> = {};
for (const [team, rows] of Object.entries(ret.mega as Record<string, { cricsheet_id: string; price: number }[]>)) {
  megaIds[team] = rows.map((r) => r.cricsheet_id);
  for (const r of rows) realPrices[r.cricsheet_id] = r.price;
}

const teams = IPL_TEAMS_DEFAULT;
const retentions = defaultRetentions(pool, teams, "mega", megaIds);
const res = simulateAuction(pool, teams, {
  purse: 120,
  squadSize: 25,
  overseasCap: 8,
  trials: 40,
  mode: "mega",
  retentions,
  realPrices,
});

// Scout: deterministic pick = lexicographically-first IPL id.
const sel = [...(scout.ipl as ScoutPlayer[])].sort((a, b) => a.cricsheet_id.localeCompare(b.cricsheet_id))[0];
const scoutOut: Record<string, { id: string; sim: number; price: number }[]> = {};
for (const tier of tiers) {
  scoutOut[tier] = similarTo(sel, scout[tier] as ScoutPlayer[], sel.role, "").map((p) => ({
    id: p.cricsheet_id,
    sim: p.sim,
    price: scoutPrice(p, tier),
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
const ESTIMATE_CASES: [number, string, string, number | null, number | null][] = [
  [0, "batter", "ipl", 0, 0],
  [13.6, "batter", "ipl", 2.75, 6926],
  [59.7, "batter", "ipl", 12.5, 449],
  [27.7, "keeper", "ipl", 12.4, 471],
  [27.4, "keeper", "bbl", 4.9, 163],
  [40.0, "all_rounder", "smat", 9.0, null],
  [-30, "bowler", "bbl", 7.0, 0],
  [10, "bowler", "cpl", null, 600],
];
// mirrored in test_web_parity.py: market-model inputs on fixed rows (incl. missing fields)
const MARKET_CASES: [MarketInputs, "mega" | "mini", number][] = [
  [{ price_value: 13.6, value_sd: 2.75, role: "batter", is_overseas: false, intl_caps: 555, age: 38.1, ipl_balls: 8400, ipl_seasons: 19, ipl_gap: 0.55, target_balls: 6926, captain_ipl_last: 0, captain_ipl_seasons: 10, captain_intl_2y: 0 }, "mini", 125],
  [{ price_value: 59.7, value_sd: 12.5, role: "batter", is_overseas: false, intl_caps: 0, age: 15.7, ipl_balls: 449, ipl_seasons: 2, ipl_gap: 0.55, target_balls: 449 }, "mini", 125],
  [{ price_value: 23.2, value_sd: 2.7, role: "bowler", overseas: false, intl_caps: 210, age: 32.9, ipl_balls: 3100, ipl_seasons: 12, ipl_gap: 0.55, target_balls: 3000, captain_ipl_last: 1, captain_ipl_seasons: 1, captain_intl_2y: 1 }, "mega", 120],
  [{ price_value: 6.0, value_sd: 9.0, role: "all_rounder", is_overseas: true, intl_caps: 40, age: 27.2, ipl_balls: 0, ipl_seasons: 0, ipl_gap: null, target_balls: 0 }, "mini", 125],
  [{ price_value: null, role: "keeper", is_overseas: false, intl_caps: null, age: null, ipl_balls: null, ipl_seasons: null, ipl_gap: 3.2 }, "mega", 90],
  [{ price_value: -45, value_sd: 20, role: "bowler", is_overseas: true, intl_caps: 3, age: 41, ipl_balls: 120, ipl_seasons: 1, ipl_gap: 9.5, target_balls: 120 }, "mini", 125],
];
const out = {
  retentions,
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
  estCases: ESTIMATE_CASES.map(([v, role, tier, sd, balls]) => estValue(v, role as Role, tier, sd, balls)),
  // the market model on fixed inputs (features + price + P(bought)); null when there is no model
  marketCases: model
    ? MARKET_CASES.map(([row, cycle, purse]) => ({
        features: marketFeatures(row, cycle),
        ...marketPrice(row, { cycle, purse }),
      }))
    : null,
  poolPrices: pool.map((p) => [p.cricsheet_id, p.projected_value, p.onfield_value, p.p_bought, p.captain]),
};
process.stdout.write(JSON.stringify(out));
