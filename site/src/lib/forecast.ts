// Form forecast: a player's value (runs per 100 balls above the average ball) over the next three
// seasons. Computed offline by scripts/form_forecast.py (cricdesk.scout.forecast); the method is in
// docs/METHODOLOGY.md §11. This file only types and reads `<collection>/forecast.json`.

export type ForecastFlag = "hold" | "improve" | "hold_then_decline" | "decline";

export interface ForecastRole {
  now: number; // his career rating (value)
  now_sd: number; // its posterior sd
  level: number; // his current level: the level model's estimate after the latest season
  level_sd: number;
  recent: [number, number, number][]; // his last seasons: [season, value, balls]
  age: number | null;
  flag: ForecastFlag;
  text: string; // the plain-English line
  avg3: number; // mean of the three medians
  regular_now: boolean;
  /** rows of `columns`: [season, median, lo, hi, season_lo, season_hi, p_regular] */
  s: number[][];
}

export interface ForecastData {
  as_of_season: number;
  version: string;
  unit: string;
  regular_balls: number;
  columns: string[];
  players: Record<string, Partial<Record<"batter" | "bowler", ForecastRole>>>;
}

export interface ForecastSeason {
  season: number;
  median: number;
  lo: number;
  hi: number;
  season_lo: number;
  season_hi: number;
  p_regular: number;
}

/** A role's three seasons as objects (column order from the file). */
export function seasonsOf(data: ForecastData, role: ForecastRole): ForecastSeason[] {
  return role.s.map((row) => {
    const o: Record<string, number> = {};
    data.columns.forEach((c, i) => (o[c] = row[i]));
    return o as unknown as ForecastSeason;
  });
}

export const FLAG_LABEL: Record<ForecastFlag, string> = {
  hold: "Holds his level",
  improve: "Improving",
  hold_then_decline: "Holds, then declines",
  decline: "Declining",
};

/** "+12" / "−3" / "0" (a true minus sign). */
export function signed(v: number): string {
  const r = Math.round(v);
  return r === 0 ? "0" : r > 0 ? `+${r}` : `−${Math.abs(r)}`;
}

const cache = new Map<string, Promise<ForecastData | null>>();

/** The league's forecast file, or null when it has none (only the IPL is forecast). */
export function getForecast(collection: string): Promise<ForecastData | null> {
  const hit = cache.get(collection);
  if (hit) return hit;
  const p = fetch(`${import.meta.env.BASE_URL}data/${collection}/forecast.json`)
    .then((r) => (r.ok ? (r.json() as Promise<ForecastData>) : null))
    .catch(() => {
      cache.delete(collection);
      return null;
    });
  cache.set(collection, p);
  return p;
}
