// Shared player-row filtering. Rows carry the Gemini taxonomy fields
// (primary_role / bowling_category / batting_position / country) plus a
// match count, injected at export time — so any player-keyed table can
// filter on them with one helper.

export interface Filters {
  minMatches: number;
  role: string; // primary_role | ""
  bowling: string; // bowling_category | ""
  position: string; // batting_position | ""
  country: string; // ISO-3 | ""
}

export const EMPTY_FILTERS: Filters = {
  minMatches: 0,
  role: "",
  bowling: "",
  position: "",
  country: "",
};

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
  minMatches: "Drops small samples — players below this many matches are hidden. Default 20.",
  role: "Primary role (Gemini-classified): batter, bowler, all-rounder or wicket-keeper.",
  bowling: "Seam/pace vs spin — Gemini-classified bowling type.",
  position: "Usual batting slot bucket: opener, No.3, middle (4–5), finisher (6–7), lower (8), tailender (9–11).",
  country: "Player's country (Gemini-classified).",
};

export function applyFilters<T extends Record<string, unknown>>(rows: T[], f: Filters): T[] {
  return rows.filter((r) => {
    if (Number(r.matches ?? 0) < f.minMatches) return false;
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
