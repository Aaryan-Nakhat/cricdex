import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";
import { leagueLabel } from "./leagues";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/** Exact number for a stats site: thousands separators (9,336), `digits` decimals for fractions. Numeric strings
 * (some exported counts are strings) are accepted. */
export function fmt(n: number | string | null | undefined, digits = 2): string {
  const x = typeof n === "string" ? Number(n) : n;
  if (x === null || x === undefined || Number.isNaN(x)) return "—";
  if (Number.isInteger(x)) return x.toLocaleString("en-US");
  return x.toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

/** "+1.20" / "−0.42" — a signed delta without "+-". */
export function fmtSigned(n: number | null | undefined, digits = 2): string {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  const body = Math.abs(n).toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits });
  return n > 0 ? `+${body}` : n < 0 ? `−${body}` : body;
}

/** Human collection label, from the league registry (leagues.json); the slug until it loads. */
export function collectionLabel(slug: string): string {
  return leagueLabel(slug);
}

/** "2026-05-07" -> "7 May 2026". */
export function prettyDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso + "T00:00:00");
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString("en-GB", {
    day: "numeric",
    month: "long",
    year: "numeric",
  });
}
