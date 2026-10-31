// Parity harness for Keep or release: runs the canonical TS calculator (src/lib/keep.ts) on a
// fixture and prints the results as JSON. test_scripts/test_keep_parity.py runs the Python
// calculator (cricdesk.web_parity.keep) on the same fixture and diffs. Run via:
//   node --no-warnings --experimental-strip-types scripts/keep_parity_dump.ts <fixture.json>
// fixture = { cases: [{ team, players, pool, pool_tags, rules, decisions, needs, form }], fmt: number[],
//             model: the market-price model or null, keep_model: the retention model or null,
//             keep_cases: [keepFeatures arguments] }
import { readFileSync } from "node:fs";
import { buildPool, registerPriceModel } from "../src/lib/auction.ts";
import {
  cr,
  crExact,
  evaluate,
  fmtNum,
  keepFeatures,
  keepProbability,
  marketFor,
  registerKeepModel,
  toCsvRows,
} from "../src/lib/keep.ts";

const fx = JSON.parse(readFileSync(process.argv[2], "utf8"));
// the market-price model the Python side uses (config/price_model.json), or null
registerPriceModel(fx.model ?? null);
const CAL = { mega: { a: -0.4, b: 1.3 }, mini: { a: 0.2, b: 0.8 } };
// the retention model the Python side uses (config/keep_model.json), or null
registerKeepModel(fx.keep_model ?? null);
const out = fx.cases.map((c: any) => {
  const market = marketFor(c.team, c.players, buildPool(c.pool), c.pool_tags, c.form, c.rules);
  const squad = c.players.filter((p: any) => p.team === c.team);
  const res = evaluate(squad, market, c.rules, c.decisions, c.needs, c.form);
  return { market, res, csv: toCsvRows(res) };
});
const fmt = (fx.fmt as number[]).map((x) => [fmtNum(x, 0), fmtNum(x, 1), fmtNum(x, 2), cr(x), crExact(x)]);
// the retention model on fixed inputs (features + probability)
const keepCases = (fx.keep_cases ?? []).map((a: any[]) => {
  const f = keepFeatures(...(a as Parameters<typeof keepFeatures>));
  return {
    features: f,
    p: fx.keep_model ? keepProbability(f, fx.keep_model) : null,
    // the same model with a recalibration per cycle (keep_backtest.py's Platt, when the refit keeps one)
    pCal: fx.keep_model ? keepProbability(f, { ...fx.keep_model, calibration: CAL }) : null,
  };
});
process.stdout.write(JSON.stringify({ out, fmt, keepCases }));
