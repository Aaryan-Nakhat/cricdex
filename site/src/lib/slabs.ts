// The retention-slab charge, shared by Keep or release (keep.ts) and the Auction room (auction.ts), so
// neither imports the other. Mirror of web_parity/keep.py `slab_charge`.

export interface SlabHolder {
  salary: number;
  slab_holder?: string | null; // "capped" | "uncapped" (retained at the cycle's mega auction)
}

export interface SlabRules {
  retention_slabs?: number[];
  uncapped_retention_slab?: number;
  /** what a kept player costs the purse: "salary" | "slabs" (absent = salary) */
  retained_cost?: string;
}

/** What the kept players cost the purse: their salaries, with the slab holders charged together by
 * `slabCharge` when the cycle charges slabs (left-to-right sums, as keep.py's `fsum`). Mirror of
 * keep.py `purse_charged`; keep.ts re-exports it. */
export function purseCharged(kept: SlabHolder[], rules: SlabRules): number {
  let t = 0;
  if (rules.retained_cost !== "slabs") {
    for (const p of kept) t += Number(p.salary);
    return t;
  }
  const holders = kept.filter((p) => p.slab_holder);
  for (const p of kept) if (!p.slab_holder) t += Number(p.salary);
  return t + (holders.length ? slabCharge(holders, rules) : 0);
}

/** A team's kept slab holders together: max(Σ the first n capped slabs + the uncapped slab × n
 * uncapped, Σ their salaries). A capped holder past the end of the slab list costs his salary.
 * Mirror of keep.py `slab_charge`. */
export function slabCharge(holders: SlabHolder[], rules: SlabRules): number {
  const slabs = rules.retention_slabs ?? [];
  const u = Number(rules.uncapped_retention_slab ?? 0);
  let total = 0;
  let sal = 0;
  let i = 0;
  for (const p of holders) {
    if (p.slab_holder === "capped") {
      total += i < slabs.length ? Number(slabs[i]) : Number(p.salary);
      i += 1;
    }
  }
  for (const p of holders) if (p.slab_holder === "uncapped") total += u;
  for (const p of holders) sal += Number(p.salary);
  return Math.max(total, sal);
}
