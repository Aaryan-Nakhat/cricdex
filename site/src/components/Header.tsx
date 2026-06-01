import { useState } from "react";
import { RefreshCw, ChevronDown, CircleDot, CalendarClock, Github } from "lucide-react";
import { useStore } from "@/lib/store";
import { collectionLabel, prettyDate } from "@/lib/utils";
import { cn } from "@/lib/utils";

function CollectionSelect() {
  const { collections, collection, setCollection } = useStore();
  const [open, setOpen] = useState(false);
  return (
    <div className="relative">
      <button className="btn min-w-[180px] justify-between" onClick={() => setOpen((o) => !o)}>
        <span className="truncate">{collectionLabel(collection)}</span>
        <ChevronDown className="h-4 w-4 text-muted" />
      </button>
      {open && (
        <>
          <div className="fixed inset-0 z-40" onClick={() => setOpen(false)} />
          <div className="absolute right-0 z-50 mt-1.5 w-72 rounded-lg border border-border bg-card p-1 shadow-card">
            {collections.map((c) => (
              <button
                key={c.collection}
                className={cn(
                  "flex w-full items-center justify-between gap-2 rounded-md px-3 py-2 text-left text-sm",
                  c.collection === collection
                    ? "bg-accent/10 text-accent-glow"
                    : "text-fg hover:bg-surface",
                )}
                onClick={() => {
                  setCollection(c.collection);
                  setOpen(false);
                }}
              >
                <span className="truncate">{collectionLabel(c.collection)}</span>
                <span className="shrink-0 stat-num text-xs text-muted">{c.n_matches} matches</span>
              </button>
            ))}
          </div>
        </>
      )}
    </div>
  );
}

export function Header() {
  const { meta, refresh, refreshing } = useStore();
  return (
    <header className="sticky top-0 z-30 border-b border-border bg-bg/80 backdrop-blur-xl">
      <div className="mx-auto flex h-16 max-w-[1400px] items-center gap-4 px-4 sm:px-6">
        {/* logo */}
        <a href={import.meta.env.BASE_URL} className="flex items-center gap-2.5">
          <span className="relative flex h-8 w-8 items-center justify-center rounded-lg border border-accent/30 bg-accent/10">
            <CircleDot className="h-4 w-4 text-accent" />
          </span>
          <div className="leading-none">
            <div className="text-base font-extrabold tracking-tight text-fg">
              Cric<span className="text-accent">Dex</span>
            </div>
            <div className="text-[10px] font-medium uppercase tracking-[0.18em] text-muted">
              open cricket intel
            </div>
          </div>
        </a>

        <div className="ml-auto flex items-center gap-2.5 sm:gap-3">
          {/* freshness stamp */}
          <div className="hidden items-center gap-2 rounded-lg border border-border bg-surface px-3 py-2 sm:flex">
            <CalendarClock className="h-4 w-4 text-accent" />
            <div className="leading-tight">
              <div className="text-[10px] uppercase tracking-wider text-muted">Data up to</div>
              <div className="text-xs font-semibold text-fg">
                {prettyDate(meta?.data_as_of)}
              </div>
            </div>
          </div>

          <CollectionSelect />

          <button
            className="btn btn-accent"
            onClick={() => void refresh()}
            disabled={refreshing}
            title="Re-pull the latest cooked data"
          >
            <RefreshCw className={cn("h-4 w-4", refreshing && "animate-spin")} />
            <span className="hidden sm:inline">{refreshing ? "Refreshing…" : "Refresh"}</span>
          </button>

          <a
            className="btn px-2.5"
            href="https://github.com/Aaryan-Nakhat/cricdex"
            target="_blank"
            rel="noreferrer"
            title="Source on GitHub"
          >
            <Github className="h-4 w-4" />
          </a>
        </div>
      </div>
    </header>
  );
}
