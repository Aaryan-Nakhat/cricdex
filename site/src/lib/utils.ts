import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/** Compact number formatter — 1.2k, 3.4M, plain ints stay plain. */
export function fmt(n: number | null | undefined, digits = 2): string {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  if (Number.isInteger(n) && Math.abs(n) < 1000) return String(n);
  if (Math.abs(n) >= 1000) {
    return new Intl.NumberFormat("en", {
      notation: "compact",
      maximumFractionDigits: 1,
    }).format(n);
  }
  return n.toFixed(digits);
}

/** Human collection label. */
export function collectionLabel(slug: string): string {
  const map: Record<string, string> = {
    ipl: "IPL",
    bbl: "Big Bash (BBL)",
    t20s_male: "Men's T20Is",
    indian_domestic_male: "Syed Mushtaq Ali (SMAT)",
    recently_played_30_male: "Last 30 days (men's T20)",
  };
  return map[slug] ?? slug;
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
