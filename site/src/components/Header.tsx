import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { RefreshCw, ChevronDown, CircleDot, CalendarClock, Github, Sun, Moon, Monitor, Check } from "lucide-react";
import { useStore } from "@/lib/store";
import { useTheme, type ThemeChoice } from "@/lib/theme";
import { collectionLabel, fmt, prettyDate } from "@/lib/utils";
import { cn } from "@/lib/utils";

const REPO_URL = "https://github.com/Aaryan-Nakhat/cricdex";

/** League picker — a listbox you can drive with the keyboard (↑ ↓ Enter Esc). */
function CollectionSelect() {
  const { collections, collection, setCollection } = useStore();
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const btn = useRef<HTMLButtonElement>(null);
  const list = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    setActive(Math.max(0, collections.findIndex((c) => c.collection === collection)));
    list.current?.focus();
  }, [open, collections, collection]);

  function choose(i: number) {
    const c = collections[i];
    if (c) setCollection(c.collection);
    setOpen(false);
    btn.current?.focus();
  }

  function onKey(e: React.KeyboardEvent) {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActive((a) => Math.min(collections.length - 1, a + 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActive((a) => Math.max(0, a - 1));
    } else if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      choose(active);
    } else if (e.key === "Escape" || e.key === "Tab") {
      setOpen(false);
      btn.current?.focus();
    }
  }

  return (
    <div className="relative">
      <button
        ref={btn}
        className="btn max-w-[60vw] justify-between whitespace-nowrap sm:max-w-none"
        onClick={() => setOpen((o) => !o)}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-label={`League: ${collectionLabel(collection)}`}
      >
        <span className="truncate sm:overflow-visible">{collectionLabel(collection)}</span>
        <ChevronDown className={cn("h-4 w-4 text-muted transition-transform", open && "rotate-180")} />
      </button>
      {open && (
        <>
          <div className="fixed inset-0 z-40" onClick={() => setOpen(false)} />
          <div
            ref={list}
            role="listbox"
            tabIndex={-1}
            aria-label="League"
            aria-activedescendant={`league-${active}`}
            onKeyDown={onKey}
            className="absolute right-0 z-50 mt-2 w-[min(24rem,calc(100vw-2rem))] rounded-xl border border-border bg-card p-1.5 shadow-card outline-none"
          >
            {collections.map((c, i) => (
              <div
                key={c.collection}
                id={`league-${i}`}
                role="option"
                aria-selected={c.collection === collection}
                onMouseEnter={() => setActive(i)}
                onClick={() => choose(i)}
                className={cn(
                  "flex cursor-pointer items-center justify-between gap-2 rounded-lg px-3 py-2 text-sm",
                  i === active && "bg-surface",
                  c.collection === collection ? "text-accent-glow" : "text-fg",
                )}
              >
                <span className="flex min-w-0 items-center gap-2">
                  <Check className={cn("h-3.5 w-3.5 shrink-0", c.collection === collection ? "opacity-100" : "opacity-0")} />
                  <span className="whitespace-normal leading-snug">{collectionLabel(c.collection)}</span>
                </span>
                <span className="shrink-0 stat-num text-xs text-muted">{fmt(c.n_matches)} matches</span>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  );
}

const THEMES: { value: ThemeChoice; label: string; icon: typeof Sun }[] = [
  { value: "auto", label: "Match system", icon: Monitor },
  { value: "light", label: "Light", icon: Sun },
  { value: "dark", label: "Dark", icon: Moon },
];

function ThemeSwitch() {
  const { choice, setChoice } = useTheme();
  return (
    <div role="radiogroup" aria-label="Theme" className="seg hidden p-0.5 md:inline-flex">
      {THEMES.map((t) => (
        <button
          key={t.value}
          role="radio"
          aria-checked={choice === t.value}
          aria-label={t.label}
          title={t.label}
          onClick={() => setChoice(t.value)}
          className={cn("seg-btn px-2 py-1.5", choice === t.value && "seg-btn-active")}
        >
          <t.icon className="h-4 w-4" />
        </button>
      ))}
    </div>
  );
}

/** Small screens: one button that cycles auto → light → dark. */
function ThemeCycle() {
  const { choice, setChoice } = useTheme();
  const i = THEMES.findIndex((t) => t.value === choice);
  const cur = THEMES[i] ?? THEMES[0];
  const next = THEMES[(i + 1) % THEMES.length];
  return (
    <button
      className="btn px-2.5 md:hidden"
      onClick={() => setChoice(next.value)}
      aria-label={`Theme: ${cur.label}. Switch to ${next.label}`}
    >
      <cur.icon className="h-4 w-4" />
    </button>
  );
}

export function Header() {
  const { meta, refresh, refreshing } = useStore();
  return (
    <header className="sticky top-0 z-30 border-b border-border bg-bg/75 backdrop-blur-xl">
      <div className="mx-auto flex h-16 max-w-[1400px] items-center gap-3 px-4 sm:px-6">
        <Link to="/" className="flex items-center gap-2.5 rounded-xl" aria-label="CricDex home">
          <span className="relative flex h-9 w-9 items-center justify-center rounded-xl border border-accent/30 bg-accent/10 shadow-glow">
            <CircleDot className="h-[18px] w-[18px] text-accent" />
          </span>
          <div className="hidden leading-none min-[420px]:block">
            <div className="text-[17px] font-extrabold tracking-tight">
              <span className="text-fg">Cric</span>
              <span className="grad-text">Dex</span>
            </div>
            <div className="mt-0.5 text-[10px] font-medium uppercase tracking-[0.18em] text-faint">
              open cricket intelligence
            </div>
          </div>
        </Link>

        <div className="ml-auto flex items-center gap-2 sm:gap-2.5">
          <div className="hidden items-center gap-2 rounded-xl border border-border bg-surface/70 px-3 py-1.5 lg:flex">
            <CalendarClock className="h-4 w-4 text-accent" />
            <div className="flex flex-col gap-1">
              <div className="eyebrow leading-none">Data up to</div>
              <div className="text-xs font-semibold leading-none text-fg">{prettyDate(meta?.data_as_of)}</div>
            </div>
          </div>

          <CollectionSelect />

          <button
            className="btn btn-accent px-2.5 sm:px-3.5"
            onClick={() => void refresh()}
            disabled={refreshing}
            aria-label="Refresh the data"
            title="Re-pull the latest exported data"
          >
            <RefreshCw className={cn("h-4 w-4", refreshing && "animate-spin")} />
            <span className="hidden sm:inline">{refreshing ? "Refreshing…" : "Refresh"}</span>
          </button>

          <ThemeSwitch />
          <ThemeCycle />

          <a
            className="btn hidden px-2.5 sm:inline-flex"
            href={REPO_URL}
            target="_blank"
            rel="noreferrer"
            aria-label="Source code on GitHub"
            title="Source on GitHub"
          >
            <Github className="h-4 w-4" />
          </a>
        </div>
      </div>
    </header>
  );
}
