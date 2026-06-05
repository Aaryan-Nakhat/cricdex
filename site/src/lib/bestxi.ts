// Best XI — exact (top-N-per-role) optimum. CANONICAL; the Python port
// `src/cricdex/web_parity/best_xi.py` mirrors this bit-for-bit (locked by
// test_scripts/test_web_parity.py).
//
// Pick exactly `size` players maximising total NGI subject to total price ≤
// budget (cr), overseas count ≤ overseasCap, and per-role minimums. Exact
// branch-and-bound over the top-`capPerRole`-per-role candidates (a full-pool
// solve is intractable in-browser). The result is made UNIQUE — and therefore
// parity-safe regardless of branch order — by a strict tie-break: maximise NGI
// (6dp), then minimise total price, then the lexicographically smallest
// cricsheet_id list. Prices use 0.1-cr integer units so the budget test is
// exact. All rounding is `Math.round` (half-up), matched by the Python port.

export interface BestXIPlayer {
  cricsheet_id: string;
  name: string;
  role: string;
  is_overseas: boolean;
  ngi: number;
  price: number; // crore
}

export interface BestXIResult {
  players: BestXIPlayer[];
  total_ngi: number;
  total_price: number;
  overseas: number;
  feasible: boolean;
}

const ngiKey = (ngi: number): number => Math.round(ngi * 1_000_000) / 1_000_000;

// Code-point string comparison (matches Python's `<` on str / sorted()).
const cmpStr = (a: string, b: string): number => (a < b ? -1 : a > b ? 1 : 0);

// Lexicographic compare of two sorted string arrays (matches Python list `<`).
function lexLt(a: string[], b: string[]): boolean {
  const m = Math.min(a.length, b.length);
  for (let i = 0; i < m; i++) {
    if (a[i] !== b[i]) return a[i] < b[i];
  }
  return a.length < b.length;
}

export function bestXI(
  players: BestXIPlayer[],
  budget: number,
  overseasCap: number,
  roleMins: Record<string, number>,
  size = 11,
  capPerRole = 40,
): BestXIResult {
  const valid = players.filter((p) => p.ngi != null && p.price != null && p.price !== 0);
  // Trim per role to the top NGI candidates (deterministic).
  const byRole = new Map<string, BestXIPlayer[]>();
  const sortedValid = [...valid].sort(
    (a, b) => ngiKey(b.ngi) - ngiKey(a.ngi) || cmpStr(a.cricsheet_id, b.cricsheet_id),
  );
  for (const p of sortedValid) {
    let bucket = byRole.get(p.role);
    if (!bucket) {
      bucket = [];
      byRole.set(p.role, bucket);
    }
    if (bucket.length < capPerRole) bucket.push(p);
  }
  const cand: BestXIPlayer[] = [];
  for (const bucket of byRole.values()) cand.push(...bucket);
  // Deterministic order: NGI desc, price asc, cid — also a good B&B order.
  cand.sort(
    (a, b) =>
      ngiKey(b.ngi) - ngiKey(a.ngi) ||
      Math.round(a.price * 10) - Math.round(b.price * 10) ||
      cmpStr(a.cricsheet_id, b.cricsheet_id),
  );
  const n = cand.length;
  const priceI = cand.map((p) => Math.round(p.price * 10));
  const ngi = cand.map((p) => p.ngi);
  const over = cand.map((p) => (p.is_overseas ? 1 : 0));
  const role = cand.map((p) => p.role);
  const budgetI = Math.round(budget * 10);
  const roles = Object.keys(roleMins);
  const minTotal = roles.reduce((s, r) => s + roleMins[r], 0);

  const best: { ngi: number; price: number; cids: string[] | null; picked: number[] | null } = {
    ngi: -1,
    price: 0,
    cids: null,
    picked: null,
  };

  function better(curNgi: number, curPrice: number, cids: string[]): boolean {
    const cn = ngiKey(curNgi);
    const bn = ngiKey(best.ngi);
    if (cn !== bn) return cn > bn;
    if (curPrice !== best.price) return curPrice < best.price;
    return best.cids === null || lexLt(cids, best.cids);
  }

  function bound(i: number, slotsLeft: number, ov: number): number {
    // Admissible upper bound on remaining NGI: the top `slotsLeft` NGIs from
    // cand[i:] that still fit the overseas cap. Returns -1 if the slots can't
    // be filled within the cap (→ prune).
    let remOs = overseasCap - ov;
    let s = 0;
    let taken = 0;
    let j = i;
    while (j < n && taken < slotsLeft) {
      if (over[j] === 0 || remOs > 0) {
        s += ngi[j];
        taken++;
        if (over[j]) remOs--;
      }
      j++;
    }
    return taken === slotsLeft ? s : -1;
  }

  function dfs(
    i: number,
    picked: number[],
    spent: number,
    ov: number,
    cur: number,
    rcount: Record<string, number>,
  ): void {
    const k = picked.length;
    if (k === size) {
      if (roles.some((rr) => (rcount[rr] ?? 0) < roleMins[rr])) return; // role mins not met
      const cids = picked.map((j) => cand[j].cricsheet_id).sort(cmpStr);
      if (better(cur, spent, cids)) {
        best.ngi = cur;
        best.price = spent;
        best.cids = cids;
        best.picked = [...picked];
      }
      return;
    }
    if (i >= n || n - i < size - k) return;
    const slotsLeft = size - k;
    const b = bound(i, slotsLeft, ov);
    if (b < 0) return;
    if (best.cids && ngiKey(cur + b) <= ngiKey(best.ngi)) return;
    const r = role[i];
    const needRole = roles.reduce((s, rr) => s + Math.max(0, (roleMins[rr] ?? 0) - (rcount[rr] ?? 0)), 0);
    if (spent + priceI[i] <= budgetI && ov + over[i] <= overseasCap && needRole <= slotsLeft) {
      rcount[r] = (rcount[r] ?? 0) + 1;
      picked.push(i);
      dfs(i + 1, picked, spent + priceI[i], ov + over[i], cur + ngi[i], rcount);
      picked.pop();
      rcount[r]--;
    }
    if (n - (i + 1) >= size - k) {
      dfs(i + 1, picked, spent, ov, cur, rcount);
    }
  }

  if (minTotal <= size) dfs(0, [], 0, 0, 0, {});

  if (best.picked === null) {
    return { players: [], total_ngi: 0, total_price: 0, overseas: 0, feasible: false };
  }
  const chosen = best.picked
    .map((j) => cand[j])
    .sort((a, b) => ngiKey(b.ngi) - ngiKey(a.ngi) || cmpStr(a.cricsheet_id, b.cricsheet_id));
  return {
    players: chosen,
    total_ngi: Math.round(best.ngi * 1000) / 1000,
    total_price: best.price / 10,
    overseas: chosen.filter((p) => p.is_overseas).length,
    feasible: true,
  };
}
