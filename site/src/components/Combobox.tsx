import { useEffect, useId, useMemo, useRef, useState } from "react";
import { Search, X } from "lucide-react";
import { cn } from "@/lib/utils";

export interface Option {
  value: string;
  label: string;
  search?: string; // extra text to match against (e.g. alt names)
  hint?: string;
}

export function Combobox({
  options,
  value,
  onChange,
  placeholder = "Search player…",
  className,
  label,
}: {
  options: Option[];
  value: string | null;
  onChange: (value: string | null) => void;
  placeholder?: string;
  className?: string;
  /** Accessible name for the input; defaults to the placeholder. */
  label?: string;
}) {
  const listId = useId();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const ref = useRef<HTMLDivElement>(null);

  const selected = options.find((o) => o.value === value) ?? null;

  const LIMIT = 50;
  const matches = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return options;
    return options.filter((o) => `${o.label} ${o.search ?? ""}`.toLowerCase().includes(q));
  }, [options, query]);
  const filtered = matches.slice(0, LIMIT);

  useEffect(() => {
    function onDoc(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, []);

  return (
    <div ref={ref} className={cn("relative", className)}>
      <div className="relative">
        <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted" />
        <input
          role="combobox"
          aria-label={label ?? placeholder}
          aria-expanded={open}
          aria-controls={listId}
          aria-autocomplete="list"
          aria-activedescendant={open && filtered[active] ? `${listId}-${active}` : undefined}
          className="input pl-9 pr-8"
          placeholder={placeholder}
          value={open ? query : (selected?.label ?? "")}
          onChange={(e) => {
            setQuery(e.target.value);
            setActive(0);
            setOpen(true);
          }}
          onFocus={() => {
            setOpen(true);
            setQuery("");
          }}
          onKeyDown={(e) => {
            if (e.key === "ArrowDown") {
              e.preventDefault();
              setActive((a) => Math.min(a + 1, filtered.length - 1));
            } else if (e.key === "ArrowUp") {
              e.preventDefault();
              setActive((a) => Math.max(a - 1, 0));
            } else if (e.key === "Enter" && filtered[active]) {
              onChange(filtered[active].value);
              setOpen(false);
            } else if (e.key === "Escape" || e.key === "Tab") {
              setOpen(false);
            }
          }}
        />
        {selected && (
          <button
            className="absolute right-2.5 top-1/2 -translate-y-1/2 text-muted hover:text-fg"
            onClick={() => {
              onChange(null);
              setQuery("");
            }}
            aria-label="Clear selection"
          >
            <X className="h-4 w-4" />
          </button>
        )}
      </div>
      {open && (
        <div
          id={listId}
          role="listbox"
          className="absolute z-50 mt-1.5 max-h-72 w-full overflow-auto rounded-xl border border-border bg-card p-1 shadow-card"
        >
          {filtered.length === 0 && (
            <div className="px-3 py-2 text-sm text-muted">{options.length ? "No player matches that." : "Loading players…"}</div>
          )}
          {filtered.map((o, i) => (
            <button
              key={o.value}
              id={`${listId}-${i}`}
              role="option"
              aria-selected={o.value === value}
              tabIndex={-1}
              className={cn(
                "flex w-full items-center justify-between gap-2 rounded-md px-3 py-2 text-left text-sm",
                i === active ? "bg-accent/10 text-accent-glow" : "text-fg hover:bg-surface",
              )}
              onMouseEnter={() => setActive(i)}
              onClick={() => {
                onChange(o.value);
                setOpen(false);
              }}
            >
              <span className="truncate">{o.label}</span>
              {o.hint && <span className="shrink-0 text-xs text-muted">{o.hint}</span>}
            </button>
          ))}
          {matches.length > LIMIT && (
            <div className="px-3 py-2 text-xs text-faint">
              Showing {LIMIT} of {matches.length.toLocaleString("en-US")} — keep typing to narrow it down.
            </div>
          )}
        </div>
      )}
    </div>
  );
}
