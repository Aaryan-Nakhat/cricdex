import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";

/** "auto" follows the system; "light" / "dark" are a saved choice. index.html applies it before first paint. */
export type ThemeChoice = "auto" | "light" | "dark";
export type Theme = "light" | "dark";

const KEY = "cricdesk.theme";

function systemTheme(): Theme {
  return window.matchMedia?.("(prefers-color-scheme: light)").matches ? "light" : "dark";
}

function readChoice(): ThemeChoice {
  try {
    const t = localStorage.getItem(KEY);
    return t === "light" || t === "dark" ? t : "auto";
  } catch {
    return "auto";
  }
}

/** Chart colours for the active theme. Recharts needs real colour strings, so these read the CSS variables. */
export interface ChartColors {
  accent: string;
  teal: string;
  gold: string;
  ball: string;
  sky: string;
  willow: string;
  fg: string;
  muted: string;
  grid: string;
  card: string;
  border: string;
}

function readChartColors(): ChartColors {
  const cs = getComputedStyle(document.documentElement);
  const rgb = (name: string, a = 1) => `rgb(${cs.getPropertyValue(`--${name}`).trim().split(/\s+/).join(" ")} / ${a})`;
  return {
    accent: rgb("accent"),
    teal: rgb("teal"),
    gold: rgb("gold"),
    ball: rgb("ball"),
    sky: rgb("sky"),
    willow: rgb("willow"),
    fg: rgb("fg"),
    muted: rgb("muted"),
    grid: rgb("border", 0.7),
    card: rgb("card"),
    border: rgb("border"),
  };
}

interface ThemeCtx {
  choice: ThemeChoice;
  theme: Theme;
  setChoice: (c: ThemeChoice) => void;
  colors: ChartColors;
}

const Ctx = createContext<ThemeCtx | null>(null);

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [choice, setChoiceRaw] = useState<ThemeChoice>(readChoice);
  const [sys, setSys] = useState<Theme>(systemTheme);
  const theme: Theme = choice === "auto" ? sys : choice;

  useEffect(() => {
    const mq = window.matchMedia?.("(prefers-color-scheme: light)");
    if (!mq) return;
    const on = () => setSys(mq.matches ? "light" : "dark");
    mq.addEventListener("change", on);
    return () => mq.removeEventListener("change", on);
  }, []);

  // index.html already set data-theme before first paint, so the first read is correct.
  const [colors, setColors] = useState<ChartColors>(readChartColors);
  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
    document.querySelector('meta[name="theme-color"]')?.setAttribute("content", theme === "light" ? "#f3f6f7" : "#060a0f");
    setColors(readChartColors()); // the variables have swapped now
  }, [theme]);

  const setChoice = useCallback((c: ThemeChoice) => {
    setChoiceRaw(c);
    try {
      if (c === "auto") localStorage.removeItem(KEY);
      else localStorage.setItem(KEY, c);
    } catch {
      /* private mode: the choice just isn't remembered */
    }
  }, []);

  return <Ctx.Provider value={{ choice, theme, setChoice, colors }}>{children}</Ctx.Provider>;
}

export function useTheme() {
  const v = useContext(Ctx);
  if (!v) throw new Error("useTheme outside ThemeProvider");
  return v;
}
