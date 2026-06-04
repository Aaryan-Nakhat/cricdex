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
  type PriceTier,
} from "../src/lib/auction.ts";
import type { ScoutPlayer } from "../src/lib/data.ts";

const here = dirname(fileURLToPath(import.meta.url));
const dataDir = join(here, "..", "public", "data", "ipl");
const load = (f: string) => JSON.parse(readFileSync(join(dataDir, f), "utf8"));

const pool = buildPool(load("auction_pool.json"));
const ret = load("retentions.json");
const scout = load("scout_index.json");

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
function similarTo(s: ScoutPlayer, arr: ScoutPlayer[], role: string, pos: string) {
  return arr
    .filter((p) => p.cricsheet_id !== s.cricsheet_id && p.role === role)
    .filter((p) => role !== "bowler" || !s.bowling_category || p.bowling_category === s.bowling_category)
    .filter((p) => !pos || p.batting_position === pos)
    .map((p) => ({ p, sim: Math.max(0, 1 - Math.abs(p.z - s.z) / 2.5) }))
    .sort((a, b) => b.sim - a.sim)
    .slice(0, 8);
}
const scoutOut: Record<string, { id: string; sim: number; price: number }[]> = {};
for (const tier of ["ipl", "smat", "bbl", "sa20", "cpl"] as PriceTier[]) {
  scoutOut[tier] = similarTo(sel, scout[tier] as ScoutPlayer[], sel.role, "").map(({ p, sim }) => ({
    id: p.cricsheet_id,
    sim,
    price: estValue(p.value, p.role, tier),
  }));
}

const out = {
  retentions,
  poolSize: res.poolSize,
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
  scout: scoutOut,
};
process.stdout.write(JSON.stringify(out));
