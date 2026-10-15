// Parity harness for head-to-head: runs the canonical TS engine
// (src/lib/headtohead.ts) on a fixture and prints the results as JSON.
// test_scripts/test_h2h_parity.py runs the Python engine on the same
// fixture and diffs. Run via:
//   node --no-warnings --experimental-strip-types scripts/h2h_parity_dump.ts <fixture.json>
// fixture = { rows: RatingRow[], pairs: [cidA, cidB][] }
import { readFileSync } from "node:fs";
import { headToHead, type H2HRole } from "../src/lib/headtohead.ts";
import type { RatingRow } from "../src/lib/data.ts";

const fx = JSON.parse(readFileSync(process.argv[2], "utf8")) as {
  rows: RatingRow[];
  pairs: [string, string][];
};
const roles: H2HRole[] = ["batter", "bowler", "all_rounder"];
const out = fx.pairs.map(([a, b]) => {
  const res: Record<string, unknown> = {};
  for (const role of roles) {
    const r = headToHead(fx.rows, a, b, role);
    res[role] = r && {
      meanA: r.meanA,
      sdA: r.sdA,
      meanB: r.meanB,
      sdB: r.sdB,
      diff: r.diff,
      pooledSd: r.pooledSd,
      pAbetter: r.pAbetter,
      pBbetter: r.pBbetter,
      component: r.component,
      ballsA: r.ballsA,
      ballsB: r.ballsB,
      verdict: r.verdict,
    };
  }
  return res;
});
process.stdout.write(JSON.stringify(out));
