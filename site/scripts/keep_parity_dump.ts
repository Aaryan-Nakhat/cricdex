// Parity harness for Keep or release: runs the canonical TS calculator (src/lib/keep.ts) on a
// fixture and prints the results as JSON. test_scripts/test_keep_parity.py runs the Python
// calculator (cricdex.web_parity.keep) on the same fixture and diffs. Run via:
//   node --no-warnings --experimental-strip-types scripts/keep_parity_dump.ts <fixture.json>
// fixture = { cases: [{ team, players, pool, pool_tags, rules, decisions, needs, form }], fmt: number[],
//             model: the market-price model or null }
import { readFileSync } from "node:fs";
import { buildPool, registerPriceModel } from "../src/lib/auction.ts";
import { cr, crExact, evaluate, fmtNum, marketFor, toCsvRows } from "../src/lib/keep.ts";

const fx = JSON.parse(readFileSync(process.argv[2], "utf8"));
// the market-price model the Python side uses (config/price_model.json), or null
registerPriceModel(fx.model ?? null);
const out = fx.cases.map((c: any) => {
  const market = marketFor(c.team, c.players, buildPool(c.pool), c.pool_tags, c.form);
  const squad = c.players.filter((p: any) => p.team === c.team);
  const res = evaluate(squad, market, c.rules, c.decisions, c.needs, c.form);
  return { market, res, csv: toCsvRows(res) };
});
const fmt = (fx.fmt as number[]).map((x) => [fmtNum(x, 0), fmtNum(x, 1), fmtNum(x, 2), cr(x), crExact(x)]);
process.stdout.write(JSON.stringify({ out, fmt }));
