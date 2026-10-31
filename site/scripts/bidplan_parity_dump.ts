// Parity harness for Bid plan: runs the canonical TS optimiser (src/lib/bidplan.ts) on a fixture and
// prints the results as JSON. test_scripts/test_bidplan_parity.py runs the Python twin
// (cricdesk.web_parity.bidplan) on the same fixture and diffs. Run via:
//   node --no-warnings --experimental-strip-types scripts/bidplan_parity_dump.ts <fixture.json>
// fixture = { cases: [{ data (keep.json shape), pool (auction_pool rows), team, decisions, purse,
//             open_slots, rules, register, needs, overrides, trials }], model: price model or null }
import { readFileSync } from "node:fs";
import { buildPool, oneTrial, registerPriceModel } from "../src/lib/auction.ts";
import { registerKeepModel } from "../src/lib/keep.ts";
import { bestXi, buildContext, chainText, gapCosts, piece, plan, rivalRuns, strength, toCsvRows } from "../src/lib/bidplan.ts";

const fx = JSON.parse(readFileSync(process.argv[2], "utf8"));
registerPriceModel(fx.model ?? null);
// the retention model the Python side uses (config/keep_model.json): the default keep calls
registerKeepModel(fx.keep_model ?? null);
const out = fx.cases.map((c: any) => {
  const pool = buildPool(c.pool);
  const display: Record<string, string> = {};
  for (const r of c.pool) if (r.display_name) display[r.cricsheet_id] = r.display_name;
  const ctx = buildContext(c.data, pool, c.team, c.decisions ?? {}, c.purse ?? null, c.open_slots, c.rules ?? null, c.register ?? null, display, c.rival_bids ?? null);
  const runs = rivalRuns(ctx, c.trials);
  const prices = runs.prices;
  const res = plan(ctx, c.needs ?? {}, c.overrides ?? {}, c.trials, prices, runs.rate, c.money ?? "auction");
  return {
    ctx: { kept: ctx.kept, purse_left: ctx.purse_left, rivals: ctx.rivals, available: ctx.available, squad: ctx.squad, rules: ctx.rules },
    prices,
    market: { rate: runs.rate, rival_gain: runs.rival_gain, rival_spend: runs.rival_spend },
    plan: res,
    csv: toCsvRows(res),
    chains: res.chains.map(chainText),
    gaps: gapCosts(ctx, res, c.needs ?? {}, c.overrides ?? {}, prices, runs.rate, c.money ?? "auction"),
  };
});
// the strength model on its own, on fixed squads
const xi = (fx.xi_cases ?? []).map((ps: any[]) => {
  const pieces = ps.map((p) => {
    const q = piece(p.id, p.name, p.value, p.role, p.overseas, p.tags, p.parts ?? null);
    if (p.cap !== undefined) q.cap = p.cap; // an auction candidate's bench cap (his P(plays))
    return q;
  });
  const b = bestXi(pieces);
  return { xi: b.xi, ids: b.ids, fillers: b.fillers, strength: strength(pieces, fx.xi_needs) };
});
// the simulator on its own (every demand path on: interest by needs, heat, anchor, stage, mega)
const sims = (fx.sim_cases ?? []).map((c: any) =>
  c.seeds.map((seed: number) =>
    oneTrial(c.bases, c.lots, { purse: c.opts.purse, squadSize: c.opts.squad_size, squadMin: c.opts.squad_min, overseasCap: c.opts.overseas_cap, mode: c.opts.mode, demand: c.opts.demand }, seed).map((st) => ({
      team: st.team,
      bought: st.bought.map((p) => p.cricsheet_id),
      prices: st.boughtPrices,
      spent: st.spent,
    })),
  ),
);
process.stdout.write(JSON.stringify({ out, xi, sims }));
