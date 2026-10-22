// Keep or release: the franchise retention calculator. EXACT mirror of
// src/cricdex/web_parity/keep.py — same constants, same formulas, same sentences — so the page
// and `cricdex keep` show identical numbers (test_scripts/test_keep_parity.py runs both).
// The method in plain words: docs/METHODOLOGY.md §10.
import { hasMarketInputs, iplPrice, marketPrice, type MarketInputs, type Role } from "./auction.ts";

// A recommendation needs a gap of at least max(KEEP_MARGIN_MIN, KEEP_MARGIN_SHARE × salary) cr
// between price and salary; inside it the player is fairly paid (Borderline).
export const KEEP_MARGIN_MIN = 0.5;
export const KEEP_MARGIN_SHARE = 0.15;
// A value sd at least this wide (runs per 100 balls) counts as a thin record in the reason.
export const THIN_SD = 6.0;
// From this age a Keep becomes Borderline unless the surplus is at least twice the margin.
export const AGE_DECLINE = 35;
// The cheapest a squad slot can be filled for (the lowest base-price band, cr).
export const MIN_SLOT_PRICE = 0.3;

export type Tag = "keeper" | "opener" | "death" | "spinner" | "overseas";
export const DEFAULT_NEEDS: Record<"keeper" | "opener" | "death" | "spinner", number> = {
  keeper: 2,
  opener: 3,
  death: 3,
  spinner: 3,
};
export const TAG_ORDER: Tag[] = ["keeper", "opener", "death", "spinner", "overseas"];
export const TAG_LETTER: Record<Tag, string> = { keeper: "k", opener: "o", death: "d", spinner: "s", overseas: "x" };
export const TAG_LABEL: Record<Tag, string> = {
  keeper: "Wicketkeepers",
  opener: "Openers",
  death: "Death bowlers",
  spinner: "Spinners",
  overseas: "Overseas",
};

export type Rec = "keep" | "release" | "borderline";

export interface KeepForm {
  bat?: [number, number, number]; // balls, runs, outs
  bowl?: [number, number, number]; // balls, runs conceded, wickets
}
export interface KeepPlayer {
  id: string | null;
  name: string;
  team: string;
  salary: number;
  acquired?: string | null;
  overseas: boolean;
  country?: string | null;
  role: Role;
  value: number | null;
  value_sd: number | null;
  target_balls: number;
  balls: number;
  age: number | null;
  tags: string;
  form: KeepForm | null;
  withdrawn?: string | boolean | null;
  trade?: { from: string; salary_before_cr: number | null } | null;
  profile?: string | null;
  // the market price's inputs (auction.ts `marketFeatures`); absent in exports before it
  price_value?: number | null;
  intl_caps?: number | null;
  intl_caps_2y?: number | null;
  ipl_balls?: number | null;
  ipl_seasons?: number | null;
  ipl_gap?: number | null;
  captain_ipl_last?: number | null;
  captain_ipl_seasons?: number | null;
  captain_intl_2y?: number | null;
  captain_teams?: string[] | null; // the IPL sides he captained last season
  /** A hand-written note on the salary (e.g. an overseas fee cap). Display only. */
  note?: string | null;
  /** Form forecast's 3-season outlook (export_site via scout/forecast.py `keep_outlook`). */
  forecast?: KeepForecast | null;
}
export interface KeepForecast {
  role: "batter" | "bowler";
  seasons: number[];
  median: number[];
  avg3: number;
  flag: string;
  p_regular_last: number;
  level?: number | null;
  text: string;
}
export interface LeagueForm {
  season: number;
  bat_sr: number;
  bowl_econ: number;
}
export interface KeepRules {
  purse: number;
  squad_min: number;
  squad_max: number;
  overseas_max: number;
  max_retained: number;
  max_overseas_retained: number;
  replacements_retainable: boolean;
}

// ---- formatting (identical rounding to keep.py: half up on |x| scaled) ----

export function fmtNum(x: number, d = 1): string {
  const n = Math.floor(Math.abs(x) * 10 ** d + 0.5 + 1e-9);
  let s = String(n);
  if (d > 0) {
    s = s.padStart(d + 1, "0");
    s = s.slice(0, -d) + "." + s.slice(-d);
  }
  return (x < 0 && n !== 0 ? "-" : "") + s;
}

/** A crore amount: two decimals below 1 cr (0.30), one above (13.3), no trailing ".0". */
export function cr(x: number): string {
  let s = fmtNum(x, Math.abs(x) < 1 ? 2 : 1);
  if (s.endsWith(".0")) s = s.slice(0, -2);
  return s === "0.00" ? "0" : s;
}

/** A salary as written: up to two decimals, trailing zeros dropped (13.25, 0.3, 18). */
export function crExact(x: number): string {
  let s = fmtNum(x, 2);
  if (s.includes(".")) s = s.replace(/0+$/, "").replace(/\.$/, "");
  return s;
}

/** Left-to-right sum (keep.py's `fsum`). */
function fsum(xs: number[]): number {
  let t = 0;
  for (const x of xs) t += x;
  return t;
}

// ---- per player ----

export const hasTag = (p: { tags: string }, tag: Tag) => p.tags.includes(TAG_LETTER[tag]);
export const margin = (salary: number) => Math.max(KEEP_MARGIN_MIN, KEEP_MARGIN_SHARE * salary);

export const FORECAST_FLAG: Record<string, string> = {
  hold: "holds",
  improve: "improves",
  hold_then_decline: "holds, then declines",
  decline: "declines",
};

/** "+5" / "-3" / "0" (Math.round: half up). Mirror of keep.py `signed`. */
export function signed(x: number): string {
  const r = Math.round(x);
  return r === 0 ? "0" : r > 0 ? `+${r}` : String(r);
}

/** The "3-season outlook" (Form forecast, METHODOLOGY §11). Mirror of keep.py `forecast_note`. */
export function forecastNote(p: KeepPlayer): string {
  const f = p.forecast;
  if (!f) return "";
  const s = f.seasons;
  const meds = f.median.map(signed).join(" / ");
  const pr = Math.round(100 * f.p_regular_last);
  return `${meds} (${s[0]}-${String(s[s.length - 1]).slice(2)}) · ${FORECAST_FLAG[f.flag] ?? f.flag} · ${pr}% a regular in ${s[s.length - 1]}`;
}

export function outlook(age: number | null): string {
  if (age === null || age === undefined) return "Age unknown.";
  if (age < 24) return "Young: likely to improve.";
  if (age < 30) return "Prime years.";
  if (age < 33) return "Holding: most players hold their level to about 33.";
  if (age < AGE_DECLINE) return "Past 32: values usually start to slip.";
  return `${AGE_DECLINE}+: expect decline; a short-term keep at best.`;
}

export function formNote(p: KeepPlayer, form: LeagueForm | null): string {
  const f = p.form;
  if (!f || !form) return "";
  const bits: string[] = [];
  const bat = f.bat;
  const bowl = f.bowl;
  const showBat = !!bat && bat[0] >= 30 && p.role !== "bowler";
  const showBowl = !!bowl && bowl[0] >= 30 && p.role !== "batter" && p.role !== "keeper";
  if (showBat && bat) {
    const sr = (100 * bat[1]) / bat[0];
    bits.push(`SR ${fmtNum(sr, 0)} v ${fmtNum(form.bat_sr, 0)} (${bat[0]} balls)`);
  }
  if (showBowl && bowl) {
    const econ = (6 * bowl[1]) / bowl[0];
    bits.push(`econ ${fmtNum(econ, 1)} v ${fmtNum(form.bowl_econ, 1)}, ${bowl[2]} wkts (${bowl[0]} balls)`);
  }
  if (bits.length === 0) return "";
  return `${form.season}: ` + bits.join("; ");
}

export interface Assessment {
  /** market price on the cautious estimate (the on-field curve when no market model / inputs) */
  price: number | null;
  price_central: number | null;
  /** the on-field curve's price: what his play alone is worth (cautious estimate) */
  onfield: number | null;
  /** chance a franchise buys him if released (market model), else null */
  p_bought: number | null;
  /** the IPL sides he captained last season, else null (the "Captain" badge) */
  captain: string | null;
  surplus: number | null;
  outlook: string;
  form_note: string;
  /** the 3-season outlook line ("" without a forecast) and its three-season average */
  forecast_note: string;
  forecast_avg3: number | null;
  rec: Rec;
  reason: string;
}

/** The IPL sides he captained last season ("RCB"), from the export's `captain_teams`, or null
 * (the "Captain" badge; captaincy is in the market price). Mirror of keep.py `captain_label`. */
export function captainLabel(p: { captain_teams?: string[] | null }): string | null {
  const teams = p.captain_teams ?? [];
  return teams.length ? teams.join(" / ") : null;
}

export function assess(p: KeepPlayer, form: LeagueForm | null = null): Assessment {
  const salary = Number(p.salary);
  const base = {
    outlook: outlook(p.age),
    form_note: formNote(p, form),
    forecast_note: forecastNote(p),
    forecast_avg3: p.forecast?.avg3 ?? null,
    captain: captainLabel(p),
  };
  if (p.value === null || p.value === undefined) {
    return {
      ...base,
      price: null,
      price_central: null,
      onfield: null,
      p_bought: null,
      surplus: null,
      rec: "borderline",
      reason: `Not enough balls in our data to rate him: decide on scouting (he costs ${crExact(salary)} cr).`,
    };
  }
  const onfield = iplPrice(p.value, p.role, p.value_sd, p.target_balls);
  let price = onfield;
  let central = iplPrice(p.value, p.role, 0, p.target_balls);
  let pBought: number | null = null;
  const mkt = hasMarketInputs(p);
  if (mkt) {
    // median market price on the cautious estimate; the upper figure is the upper quartile of what
    // players like him fetch, on his central value
    const mk = marketPrice(p as unknown as MarketInputs);
    price = mk.price;
    pBought = mk.p_bought;
    central = marketPrice({ ...(p as unknown as MarketInputs), value_sd: 0 }).high;
  }
  const surplus = price - salary;
  const m = margin(salary);
  const age = p.age;
  let rec: Rec;
  let reason: string;
  if (surplus >= m) {
    if (age !== null && age !== undefined && age >= AGE_DECLINE && surplus < 2 * m) {
      rec = "borderline";
      reason = `Worth about ${cr(price)} cr against ${crExact(salary)}, but at ${Math.floor(age)} his value usually falls from here.`;
    } else {
      rec = "keep";
      reason = `Worth about ${cr(price)} cr at auction, paid ${crExact(salary)}: ${cr(surplus)} cr of surplus.`;
    }
  } else if (central - salary <= -m) {
    rec = "release";
    reason = mkt
      ? `Paid ${crExact(salary)} cr but players like him fetch about ${cr(price)} (${cr(central)} in the top quarter): releasing frees ${crExact(salary)} cr.`
      : `Paid ${crExact(salary)} cr but worth about ${cr(central)} even on his central estimate: releasing frees ${crExact(salary)} cr.`;
  } else if (central - salary >= m) {
    rec = "borderline";
    reason =
      (p.value_sd ?? 0) >= THIN_SD
        ? `Thin record: worth ${cr(price)} to ${cr(central)} cr against ${crExact(salary)}; keep if you trust the upside.`
        : `Close call: worth ${cr(price)} (${mkt ? "median" : "cautious"}) to ${cr(central)} cr${mkt ? " (top quarter)" : ""} against ${crExact(salary)}; a keep if you back the higher figure.`;
  } else {
    rec = "borderline";
    reason = mkt
      ? `Fairly paid: players like him fetch ${cr(price)} to ${cr(central)} cr (top quarter) against ${crExact(salary)}.`
      : `Fairly paid: worth about ${cr(price)} cr against ${crExact(salary)}.`;
  }
  if (mkt && base.captain) reason += ` Captained ${base.captain} last season: the market pays captains a premium.`;
  return { ...base, price, price_central: central, onfield, p_bought: pBought, surplus, rec, reason };
}

export const playerKey = (p: { id: string | null; team: string; name: string }) => p.id || `name:${p.team}:${p.name}`;

// ---- squad ----

export interface MarketPlayer {
  id: string;
  name: string;
  value: number;
  price: number;
  overseas: boolean;
  tags: string;
  /** null = a free agent; else the team our call releases him from */
  from_team: string | null;
}

/** The replacement market: priced auction-pool players with no franchise, with their tags.
 * `pool` = buildPool(auction_pool.json) rows (projected_value = the price). */
export function freeAgents(
  pool: { cricsheet_id: string; name: string; value: number; projected_value: number; is_overseas: boolean; team: string | null }[],
  tags: Record<string, string>,
): MarketPlayer[] {
  const out: MarketPlayer[] = [];
  for (const r of pool) {
    if (r.team) continue;
    let t = tags[r.cricsheet_id] ?? "";
    if (r.is_overseas && !t.includes("x")) t += "x";
    out.push({ id: r.cricsheet_id, name: r.name, value: r.value, price: r.projected_value, overseas: !!r.is_overseas, tags: t, from_team: null });
  }
  return out;
}

/** The auction pool a team will shop in: today's free agents plus the players our calls send back
 * from the other squads (their Release recommendations), each at our estimated price. */
export function marketFor(
  team: string,
  players: KeepPlayer[],
  pool: Parameters<typeof freeAgents>[0],
  tags: Record<string, string>,
  form: LeagueForm | null = null,
): MarketPlayer[] {
  const out = freeAgents(pool, tags);
  for (const p of players) {
    if (p.team === team || p.value === null || p.value === undefined) continue;
    const a = assess(p, form);
    if (a.rec !== "release") continue;
    let t = p.tags || "";
    if (p.overseas && !t.includes("x")) t += "x";
    out.push({ id: playerKey(p), name: p.name, value: p.value, price: a.price as number, overseas: !!p.overseas, tags: t, from_team: p.team });
  }
  return out;
}

export type Decision = "keep" | "release";
export interface AssessedPlayer extends KeepPlayer, Assessment {
  key: string;
  kept: boolean;
  overridden: boolean;
  /** released by the default plan to fit the squad limit or overseas cap, else null */
  auto_release: AutoRelease | null;
}
export interface Gap {
  tag: Tag;
  label: string;
  target: number;
  kept: number;
  gap: number;
  ref_value: number;
  ref_from_release: boolean;
  picks: { id: string; name: string; price: number; value: number; from_team: string | null }[];
  cost: number;
  short: number;
}
export interface SquadResult {
  players: AssessedPlayer[];
  kept: number;
  released: number;
  overseas_kept: number;
  salary_kept: number;
  salary_released: number;
  purse: number;
  purse_left: number;
  slots_left: number;
  overseas_slots_left: number;
  gaps: Gap[];
  replacement_cost: number;
  purse_after_replacements: number;
  to_min_after_replacements: number;
  warnings: string[];
}

/** Who goes first when the default plan is over a limit: Borderline before Keep, then the lowest
 * surplus per crore of salary (an unrated player first), then the key. Mirror of keep.py `_fit_order`. */
function fitOrder(a: AssessedPlayer, b: AssessedPlayer): number {
  const ta = a.rec === "borderline" ? 0 : 1;
  const tb = b.rec === "borderline" ? 0 : 1;
  if (ta !== tb) return ta - tb;
  const r = (p: AssessedPlayer) => {
    const sal = Number(p.salary);
    if (p.surplus === null) return -Infinity;
    return sal > 0 ? p.surplus / sal : p.surplus;
  };
  const ra = r(a);
  const rb = r(b);
  if (ra !== rb) return ra < rb ? -1 : 1;
  return a.key < b.key ? -1 : a.key > b.key ? 1 : 0;
}

/** Make the default plan legal (mirror of keep.py `fit_to_rules`): release kept overseas Borderline
 * players, lowest surplus per crore first (a Keep only once no Borderline is left), until the overseas
 * cap holds; then the same for the squad maximum. A player the user decided on is never moved. */
export function fitToRules(players: AssessedPlayer[], rules: KeepRules): void {
  let sqMax = rules.squad_max;
  if (rules.max_retained) sqMax = Math.min(sqMax, rules.max_retained);
  let osMax = rules.overseas_max;
  if (rules.max_overseas_retained) osMax = Math.min(osMax, rules.max_overseas_retained);
  const passes: [AutoRelease, number, boolean][] = [
    ["overseas", osMax, true],
    ["squad", sqMax, false],
  ];
  for (const [kind, limit, osOnly] of passes) {
    let count = players.filter((p) => p.kept && (!osOnly || p.overseas)).length;
    if (count <= limit) continue;
    const cands = players
      .filter((p) => p.kept && !p.overridden && (p.rec === "borderline" || p.rec === "keep") && (!osOnly || p.overseas))
      .sort(fitOrder);
    for (const p of cands) {
      if (count <= limit) break;
      p.kept = false;
      p.auto_release = kind;
      p.reason +=
        kind === "overseas" ? ` Released to fit the ${limit}-overseas cap.` : ` Released to fit the ${limit}-player squad limit.`;
      count--;
    }
  }
}

export type AutoRelease = "overseas" | "squad" | "open";

export function evaluate(
  squad: KeepPlayer[],
  market: MarketPlayer[],
  rules: KeepRules,
  decisions: Record<string, Decision> = {},
  needs: Partial<Record<Tag, number>> = {},
  form: LeagueForm | null = null,
): SquadResult {
  const players: AssessedPlayer[] = squad.map((p) => {
    const a = assess(p, form);
    const key = playerKey(p);
    const d = Object.prototype.hasOwnProperty.call(decisions, key) ? decisions[key] : undefined;
    const ok = d === "keep" || d === "release";
    const kept = ok ? d === "keep" : a.rec !== "release";
    return { ...p, ...a, key, kept, overridden: ok, auto_release: null };
  });
  fitToRules(players, rules);
  const kept = players.filter((p) => p.kept);
  const released = players.filter((p) => !p.kept);
  const salaryKept = fsum(kept.map((p) => Number(p.salary)));
  const overseasKept = kept.filter((p) => p.overseas).length;
  const purse = Number(rules.purse);
  const purseLeft = purse - salaryKept;
  const slotsLeft = rules.squad_max - kept.length;
  const overseasSlots = rules.overseas_max - overseasKept;

  const overseasNow = players.filter((p) => p.overseas).length;
  const target: Record<Tag, number> = { ...DEFAULT_NEEDS, overseas: Math.min(rules.overseas_max, overseasNow) };
  for (const [k, v] of Object.entries(needs)) {
    if (k in target && typeof v === "number" && v >= 0) target[k as Tag] = Math.trunc(v);
  }

  const have: Record<Tag, number> = Object.fromEntries(
    TAG_ORDER.map((t) => [t, kept.filter((p) => hasTag(p, t)).length]),
  ) as Record<Tag, number>;
  const picked = new Set<string>();
  let room = Math.max(slotsLeft, 0);
  let osRoom = Math.max(overseasSlots, 0);
  const gaps: Gap[] = [];
  for (const tag of TAG_ORDER) {
    const need = Math.max(0, target[tag] - have[tag]);
    const relVals = released.filter((p) => hasTag(p, tag) && p.value !== null && p.value !== undefined).map((p) => p.value as number);
    const ref = relVals.length ? Math.max(...relVals) : 0.0;
    const picks: MarketPlayer[] = [];
    if (need > 0) {
      const cands = market.filter((c) => c.tags.includes(TAG_LETTER[tag]) && c.value >= ref && !picked.has(c.id));
      cands.sort((a, b) => a.price - b.price || b.value - a.value || (a.id < b.id ? -1 : a.id > b.id ? 1 : 0));
      for (const c of cands) {
        if (picks.length >= need || room <= 0) break;
        if (c.overseas && osRoom <= 0) continue;
        picks.push(c);
        picked.add(c.id);
        room -= 1;
        if (c.overseas) osRoom -= 1;
        for (const t of TAG_ORDER) if (c.tags.includes(TAG_LETTER[t])) have[t] += 1;
      }
    }
    gaps.push({
      tag,
      label: TAG_LABEL[tag],
      target: target[tag],
      kept: kept.filter((p) => hasTag(p, tag)).length,
      gap: need,
      ref_value: ref,
      ref_from_release: relVals.length > 0,
      picks: picks.map((c) => ({ id: c.id, name: c.name, price: c.price, value: c.value, from_team: c.from_team })),
      cost: fsum(picks.map((c) => c.price)),
      short: need - picks.length,
    });
  }
  const replacementCost = fsum(gaps.map((g) => g.cost));
  const nPicks = gaps.reduce((s, g) => s + g.picks.length, 0);
  const toMin = Math.max(0, rules.squad_min - kept.length - nPicks);

  const warnings: string[] = [];
  if (kept.length > rules.squad_max) warnings.push(`Keeping ${kept.length}: over the ${rules.squad_max}-player squad limit.`);
  if (overseasKept > rules.overseas_max)
    warnings.push(`Keeping ${overseasKept} overseas players: over the cap of ${rules.overseas_max}.`);
  const mr = rules.max_retained || 0;
  if (mr && kept.length > mr) warnings.push(`Keeping ${kept.length}: the rules allow ${mr}.`);
  const mo = rules.max_overseas_retained || 0;
  if (mo && overseasKept > mo) warnings.push(`Keeping ${overseasKept} overseas: the rules allow ${mo}.`);
  if (purseLeft < 0) warnings.push(`Kept salaries exceed the ${cr(purse)} cr purse by ${cr(-purseLeft)} cr.`);
  else if (purseLeft - replacementCost < toMin * MIN_SLOT_PRICE)
    warnings.push(
      `After the replacements there isn't enough purse to reach ${rules.squad_min} players at ${cr(MIN_SLOT_PRICE)} cr each.`,
    );
  for (const g of gaps)
    if (g.short > 0)
      warnings.push(
        `${g.label}: only ${g.picks.length} of ${g.gap} found in the pool at that level (or no squad / overseas room left).`,
      );

  return {
    players,
    kept: kept.length,
    released: released.length,
    overseas_kept: overseasKept,
    salary_kept: salaryKept,
    salary_released: fsum(released.map((p) => Number(p.salary))),
    purse,
    purse_left: purseLeft,
    slots_left: slotsLeft,
    overseas_slots_left: overseasSlots,
    gaps,
    replacement_cost: replacementCost,
    purse_after_replacements: purseLeft - replacementCost,
    to_min_after_replacements: toMin,
    warnings,
  };
}

/** The table as CSV rows (same columns as keep.py's `to_csv_rows`). */
export function toCsvRows(res: SquadResult): string[][] {
  const head = [
    "player", "team", "role", "overseas", "age", "acquired", "salary_cr", "value", "value_sd",
    "price_cr", "onfield_cr", "p_bought", "surplus_cr", "recommendation", "decision", "auto_release",
    "reason", "outlook", "form", "outlook_3y_avg", "outlook_3y",
  ];
  const rows = [head];
  for (const p of res.players) {
    rows.push([
      p.name,
      p.team,
      p.role,
      p.overseas ? "yes" : "no",
      p.age === null || p.age === undefined ? "" : String(Math.floor(p.age)),
      p.acquired || "",
      fmtNum(Number(p.salary), 2),
      p.value === null || p.value === undefined ? "" : fmtNum(p.value, 1),
      p.value_sd === null || p.value_sd === undefined ? "" : fmtNum(p.value_sd, 1),
      p.price === null ? "" : fmtNum(p.price, 2),
      p.onfield === null ? "" : fmtNum(p.onfield, 2),
      p.p_bought === null ? "" : fmtNum(p.p_bought, 2),
      p.surplus === null ? "" : fmtNum(p.surplus, 2),
      p.rec,
      p.kept ? "keep" : "release",
      p.auto_release ?? "",
      p.reason,
      p.outlook,
      p.form_note,
      p.forecast_avg3 === null ? "" : fmtNum(p.forecast_avg3, 1),
      p.forecast_note,
    ]);
  }
  return rows;
}

/** CSV text (RFC 4180 quoting). */
export function toCsv(rows: string[][]): string {
  const q = (s: string) => (/[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s);
  return rows.map((r) => r.map(q).join(",")).join("\n") + "\n";
}

// ---- exported data (keep.json) ----

export interface CompetitionSource {
  about: string;
  status: "official" | "reported";
  title: string;
  url: string;
  date: string | null;
  note: string;
}
export interface CompetitionInfo {
  key: string;
  name: string;
  league: string;
  season: number;
  cycle: "mega" | "mini";
  currency: string;
  unit: string;
  retention_deadline: string;
  auction_date: string;
  auction_venue: string;
  purse: number;
  squad_min: number;
  squad_max: number;
  overseas_max: number;
  max_retained: number;
  max_overseas_retained: number;
  rtm_cards: number;
  retained_cost: string;
  replacements_retainable: boolean;
  overseas_fee_cap: number;
  min_purse_spend_share: number;
  assumed: string[];
  source: CompetitionSource[];
  rules: KeepRules;
}
export interface KeepData {
  competition: CompetitionInfo;
  squads_source: string | null;
  salary_source: string | null;
  changes_source: string | null;
  changes: { kind: string; name: string; from?: string; to?: string; team?: string; salary_cr?: number; date?: string }[];
  purse_check: { source: string | null; teams: Record<string, { published: number; ours: number }> };
  unmatched: { team: string; name: string }[];
  form: LeagueForm | null;
  death_rule: { share: number; min_balls: number };
  teams: string[];
  players: KeepPlayer[];
  pool_tags: Record<string, string>;
}
