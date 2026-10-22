// The retention-slab charge, shared by Keep or release (keep.ts) and the Auction room (auction.ts), so
// neither imports the other. Mirror of web_parity/keep.py `slab_charge`.

export interface SlabHolder {
  salary: number;
  slab_holder?: string | null; // "capped" | "uncapped" (retained at the cycle's mega auction)
}

export interface SlabRules {
  retention_slabs?: number[];
  uncapped_retention_slab?: number;
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
