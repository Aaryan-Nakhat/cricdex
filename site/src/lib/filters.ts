// Shared player-row filtering. Rows carry the LLM taxonomy fields
// (primary_role / bowling_category / batting_position / country) plus a
// match count, injected at export time — so any player-keyed table can
// filter on them with one helper.

export interface Filters {
  minMatches: number;
  role: string; // primary_role | ""
  bowling: string; // bowling_category | ""
  position: string; // batting_position | ""
  country: string; // ISO-3 | ""
  activity: "all" | "active" | "retired";
}

export const EMPTY_FILTERS: Filters = {
  minMatches: 0,
  role: "",
  bowling: "",
  position: "",
  country: "",
  activity: "all",
};

/** Where the player boards (Leaderboards, Form, Phase) start: established, currently active players. */
export const DEFAULT_FILTERS: Filters = { ...EMPTY_FILTERS, minMatches: 20, activity: "active" };

/** The default min-matches is 20, or this share of the most matches anyone has on the board when that is
 * lower: a one-season window can't ask for 20 when nobody played more than 17. */
export const MIN_MATCHES_SHARE = 0.4;

export function defaultMinMatches(rows: Record<string, unknown>[]): number {
  let most = 0;
  for (const r of rows) most = Math.max(most, Number(r.matches ?? 0) || 0);
  if (most <= 0) return DEFAULT_FILTERS.minMatches;
  return Math.min(DEFAULT_FILTERS.minMatches, Math.ceil(MIN_MATCHES_SHARE * most));
}

/** DEFAULT_FILTERS with the min-matches sized to this board's rows. */
export function defaultFiltersFor(rows: Record<string, unknown>[]): Filters {
  return { ...DEFAULT_FILTERS, minMatches: defaultMinMatches(rows) };
}

export const ACTIVITY_OPTS = [
  { value: "active", label: "Active only" },
  { value: "retired", label: "Retired only" },
  { value: "all", label: "Active + retired" },
];

export const ROLE_OPTS = [
  { value: "", label: "Any role" },
  { value: "batter", label: "Batter" },
  { value: "bowler", label: "Bowler" },
  { value: "allrounder", label: "All-rounder" },
  { value: "wk_batter", label: "Wicket-keeper" },
];

export const BOWLING_OPTS = [
  { value: "", label: "Any bowling" },
  { value: "seam", label: "Seam / pace" },
  { value: "spin", label: "Spin" },
];

export const POSITION_OPTS = [
  { value: "", label: "Any position" },
  { value: "opener", label: "Opener (1–2)" },
  { value: "no3", label: "No. 3" },
  { value: "middle", label: "Middle (4–5)" },
  { value: "finisher", label: "Finisher (6–7)" },
  { value: "lower", label: "Lower (8)" },
  { value: "tailender", label: "Tailender (9–11)" },
];

export const FILTER_HELP: Record<string, string> = {
  minMatches: "Drops small samples — players below this many matches are hidden. Default 20, or 40% of the most matches anyone has in the period when that's lower (7 for one IPL season).",
  activity: "Active = appeared in this format within ~18 months of the latest match; retired = not. It's per-format, so a player retired from internationals can still be Active in IPL.",
  role: "Primary role (AI-classified): batter, bowler, all-rounder or wicket-keeper.",
  bowling: "Seam/pace vs spin — AI-classified bowling type (pure batters carry none).",
  position: "Usual batting slot bucket: opener, No.3, middle (4–5), finisher (6–7), lower (8), tailender (9–11).",
  country: "Player's country (AI-classified).",
};

export function applyFilters<T extends Record<string, unknown>>(rows: T[], f: Filters): T[] {
  return rows.filter((r) => {
    if (Number(r.matches ?? 0) < f.minMatches) return false;
    if (f.activity === "active" && !r.active) return false;
    if (f.activity === "retired" && r.active) return false;
    if (f.role && r.primary_role !== f.role) return false;
    if (f.bowling && r.bowling_category !== f.bowling) return false;
    if (f.position && r.batting_position !== f.position) return false;
    if (f.country && r.country !== f.country) return false;
    return true;
  });
}

/** Distinct country list present in the rows, for the country dropdown. */
export function countriesIn(rows: Record<string, unknown>[]): { value: string; label: string }[] {
  const set = new Set<string>();
  for (const r of rows) if (r.country) set.add(String(r.country));
  return [
    { value: "", label: "Any country" },
    ...[...set].sort().map((c) => ({ value: c, label: c })),
  ];
}

// ---- smart options ----------------------------------------------------------
// A filter option that can't apply is hidden (no row on this board has it, or the
// board rules it out) or disabled (no row left once the other filters apply), so a
// user never picks a dead end. Options carry live counts.

export type Dim = "minMatches" | "activity" | "role" | "bowling" | "position" | "country";
export type CatDim = "activity" | "role" | "bowling" | "position" | "country";

export interface SmartOpt {
  value: string;
  label: string;
  count?: number;
  disabled?: boolean;
}

export interface SmartFilters {
  /** Dimensions worth showing (asked for, and with at least two real choices). */
  show: Dim[];
  opts: Partial<Record<CatDim, SmartOpt[]>>;
  /** Plain-English notes on what was hidden and why (shown in the filter help). */
  notes: string[];
  /** The filters with any value that can't apply here dropped back to "any". */
  effective: Filters;
}

const DIM_FIELD: Record<Exclude<CatDim, "activity">, string> = {
  role: "primary_role",
  bowling: "bowling_category",
  position: "batting_position",
  country: "country",
};

const DIM_NAME: Record<Dim, string> = {
  minMatches: "Min matches",
  activity: "Active / retired",
  role: "Role",
  bowling: "Bowling type",
  position: "Batting position",
  country: "Country",
};

function baseOpts(dim: CatDim, rows: Record<string, unknown>[]): { value: string; label: string }[] {
  if (dim === "activity") return ACTIVITY_OPTS;
  if (dim === "role") return ROLE_OPTS;
  if (dim === "bowling") return BOWLING_OPTS;
  if (dim === "position") return POSITION_OPTS;
  return countriesIn(rows);
}

function matchesDim(r: Record<string, unknown>, dim: CatDim, value: string): boolean {
  if (!value) return true;
  if (dim === "activity") return value === "all" || (value === "active" ? !!r.active : !r.active);
  return r[DIM_FIELD[dim]] === value;
}

/**
 * Work out which filter options make sense for these rows.
 * `allowed` = the dimensions this board/page supports (others are hidden with a note);
 * `exclude` = options the board rules out, value -> reason.
 */
export function smartFilters(
  rows: Record<string, unknown>[],
  filters: Filters,
  allowed: Dim[],
  exclude: Partial<Record<Dim, Record<string, string>>> = {},
  hiddenReason = "doesn't apply on this board",
): SmartFilters {
  const notes: string[] = [];
  const eff: Filters = { ...filters };
  const all: Dim[] = ["minMatches", "activity", "role", "bowling", "position", "country"];
  for (const d of all) {
    if (allowed.includes(d)) continue;
    if (d !== "minMatches" && d !== "activity" && eff[d]) (eff as unknown as Record<string, string>)[d] = "";
  }
  const cats: CatDim[] = ["activity", "role", "bowling", "position", "country"];
  // first pass: drop values that are excluded or absent from the board entirely
  for (const d of cats) {
    if (!allowed.includes(d) || d === "activity") continue;
    const v = eff[d];
    if (!v) continue;
    if (exclude[d]?.[v] || !rows.some((r) => r[DIM_FIELD[d]] === v)) (eff as unknown as Record<string, string>)[d] = "";
  }
  const opts: SmartFilters["opts"] = {};
  const show: Dim[] = [];
  for (const d of all) {
    if (!allowed.includes(d)) continue;
    if (d === "minMatches") {
      show.push(d);
      continue;
    }
    // counts under every other filter
    const others: Filters = { ...eff, [d]: d === "activity" ? "all" : "" } as Filters;
    const pool = applyFilters(rows, others);
    const present = baseOpts(d, rows).filter((o) => {
      if (!o.value || (d === "activity" && o.value === "all")) return true;
      if (exclude[d]?.[o.value]) return false;
      return d === "activity" ? rows.some((r) => matchesDim(r, d, o.value)) : rows.some((r) => r[DIM_FIELD[d]] === o.value);
    });
    const real = present.filter((o) => o.value && !(d === "activity" && o.value === "all"));
    for (const [v, why] of Object.entries(exclude[d] ?? {})) {
      const lab = baseOpts(d, rows).find((o) => o.value === v)?.label ?? v;
      notes.push(`${DIM_NAME[d]} “${lab}” isn't offered: ${why}`);
    }
    if (d !== "activity" && real.length < 2) {
      // nothing to choose between — hide it, and drop any value it held
      (eff as unknown as Record<string, string>)[d] = "";
      if (real.length === 1) notes.push(`${DIM_NAME[d]}: every player here is “${real[0].label}”.`);
      continue;
    }
    opts[d] = present.map((o) => {
      const isAny = !o.value || (d === "activity" && o.value === "all");
      const count = pool.filter((r) => matchesDim(r, d, isAny ? "" : o.value)).length;
      const isCurrent = eff[d] === o.value;
      return {
        value: o.value,
        label: `${o.label} (${count})`,
        count,
        disabled: !isAny && count === 0 && !isCurrent,
      };
    });
    show.push(d);
  }
  for (const d of all) {
    if (!allowed.includes(d) && d !== "minMatches" && d !== "activity") notes.push(`${DIM_NAME[d]} filter hidden — it ${hiddenReason}.`);
  }
  return { show, opts, notes, effective: eff };
}
