import { useCallback, useEffect, useId, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { Info, ChevronRight, AlertTriangle, RotateCw, Inbox } from "lucide-react";
import { useStore } from "@/lib/store";
import { cn } from "@/lib/utils";

/** A click-to-expand panel. Collapsed by default. */
export function Collapsible({
  title,
  icon,
  defaultOpen = false,
  children,
}: {
  title: ReactNode;
  icon?: ReactNode;
  defaultOpen?: boolean;
  children: ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const id = useId();
  return (
    <div className="card mb-5 overflow-hidden">
      <button
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        aria-controls={id}
        className="flex w-full items-center gap-2.5 px-5 py-3.5 text-left text-sm font-semibold text-fg hover:bg-surface/40"
      >
        {icon && <span className="text-accent">{icon}</span>}
        {title}
        <ChevronRight className={cn("ml-auto h-4 w-4 text-muted transition-transform", open && "rotate-90")} />
      </button>
      {open && (
        <div id={id} className="border-t border-border px-5 py-4">
          {children}
        </div>
      )}
    </div>
  );
}

// Only one info popover is open at a time: opening one tells the others to close.
const INFO_OPEN_EVENT = "cricdex:infotip-open";

/** A small "i" button that pops a panel anchored to it. One open at a time; closes on outside click,
 * Escape (focus returns to the button) or scrolling it out of view. Rendered in a portal so a card's
 * stacking context or overflow can't hide it or let it overlap another popover. */
export function InfoTip({
  title,
  label,
  children,
  className,
}: {
  title?: string;
  /** Screen-reader name for the button; defaults to the title. */
  label?: string;
  children: ReactNode;
  className?: string;
}) {
  const [open, setOpen] = useState(false);
  const btn = useRef<HTMLButtonElement>(null);
  const pop = useRef<HTMLDivElement>(null);
  const id = useId();
  const [pos, setPos] = useState<{ top: number; left: number; width: number; above: boolean } | null>(null);

  const place = useCallback(() => {
    const b = btn.current;
    if (!b) return;
    const r = b.getBoundingClientRect();
    const vw = window.innerWidth;
    const vh = window.innerHeight;
    const width = Math.min(320, vw - 24);
    const left = Math.max(12, Math.min(vw - width - 12, r.left + r.width / 2 - width / 2));
    const h = pop.current?.offsetHeight ?? 200;
    const above = r.bottom + 8 + h > vh && r.top - 8 - h > 0;
    setPos({ top: above ? r.top - 8 - h : r.bottom + 8, left, width, above });
  }, []);

  useEffect(() => {
    function onOther(e: Event) {
      if ((e as CustomEvent<string>).detail !== id) setOpen(false);
    }
    window.addEventListener(INFO_OPEN_EVENT, onOther);
    return () => window.removeEventListener(INFO_OPEN_EVENT, onOther);
  }, [id]);

  useLayoutEffect(() => {
    if (open) place();
  }, [open, place]);

  useEffect(() => {
    if (!open) return;
    function onDown(e: PointerEvent) {
      const t = e.target as Node;
      if (btn.current?.contains(t) || pop.current?.contains(t)) return;
      setOpen(false);
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") {
        setOpen(false);
        btn.current?.focus();
      }
    }
    function onMove() {
      const b = btn.current;
      if (!b) return;
      const r = b.getBoundingClientRect();
      if (r.bottom < 0 || r.top > window.innerHeight) setOpen(false);
      else place();
    }
    document.addEventListener("pointerdown", onDown);
    document.addEventListener("keydown", onKey);
    window.addEventListener("scroll", onMove, true);
    window.addEventListener("resize", onMove);
    return () => {
      document.removeEventListener("pointerdown", onDown);
      document.removeEventListener("keydown", onKey);
      window.removeEventListener("scroll", onMove, true);
      window.removeEventListener("resize", onMove);
    };
  }, [open, place]);

  function toggle(e: React.MouseEvent) {
    // never let the click reach a sortable header or a clickable row behind the icon
    e.stopPropagation();
    e.preventDefault();
    setOpen((o) => {
      if (!o) window.dispatchEvent(new CustomEvent(INFO_OPEN_EVENT, { detail: id }));
      return !o;
    });
  }

  return (
    <span className={cn("relative inline-flex align-middle", className)}>
      <button
        ref={btn}
        type="button"
        aria-label={label ?? (title ? `About: ${title}` : "More information")}
        aria-expanded={open}
        aria-controls={open ? id : undefined}
        onClick={toggle}
        // Enter / Space open the tip without also activating a clickable row behind it; Escape still bubbles up
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") e.stopPropagation();
        }}
        className={cn(
          "inline-flex h-5 w-5 items-center justify-center rounded-full border text-[11px] transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent",
          open
            ? "border-accent/50 bg-accent/15 text-accent-glow"
            : "border-border bg-surface text-muted hover:border-accent/40 hover:text-accent-glow",
        )}
      >
        <Info className="h-3 w-3" />
      </button>
      {open &&
        createPortal(
          <div
            ref={pop}
            id={id}
            role="dialog"
            aria-label={title ?? label ?? "More information"}
            onClick={(e) => e.stopPropagation()}
            style={{
              position: "fixed",
              top: pos?.top ?? -9999,
              left: pos?.left ?? -9999,
              width: pos?.width ?? 320,
              visibility: pos ? "visible" : "hidden",
            }}
            className="z-[100] max-h-[70vh] overflow-auto rounded-xl border border-border bg-card p-3.5 text-left normal-case tracking-normal shadow-card"
          >
            {title && <div className="mb-1.5 text-xs font-semibold text-accent-glow">{title}</div>}
            <div className="text-xs font-normal leading-relaxed text-muted">{children}</div>
          </div>,
          document.body,
        )}
    </span>
  );
}

export function Card({ className, children }: { className?: string; children: ReactNode }) {
  return <div className={cn("card", className)}>{children}</div>;
}

export function CardHeader({
  title,
  subtitle,
  right,
}: {
  title: ReactNode;
  subtitle?: ReactNode;
  right?: ReactNode;
}) {
  return (
    <div className="flex items-start justify-between gap-3 border-b border-border px-5 py-4">
      <div>
        <h3 className="text-sm font-semibold text-fg">{title}</h3>
        {subtitle && <p className="mt-0.5 text-xs text-muted">{subtitle}</p>}
      </div>
      {right}
    </div>
  );
}

export function Badge({
  children,
  tone = "muted",
  className,
}: {
  children: ReactNode;
  tone?: "muted" | "accent" | "ball" | "willow" | "gold";
  className?: string;
}) {
  const tones = {
    muted: "border-border bg-surface text-muted",
    accent: "border-accent/30 bg-accent/10 text-accent-glow",
    ball: "border-ball/30 bg-ball/10 text-ball",
    willow: "border-willow/30 bg-willow/10 text-willow",
    gold: "border-gold/30 bg-gold/10 text-gold",
  };
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-md border px-2 py-0.5 text-[11px] font-semibold",
        tones[tone],
        className,
      )}
    >
      {children}
    </span>
  );
}

export function Spinner({ label }: { label?: string }) {
  return (
    <div role="status" className="flex items-center justify-center gap-3 py-16 text-muted">
      <span className="h-5 w-5 animate-spin rounded-full border-2 border-border border-t-accent" />
      <span className="text-sm">{label ?? "Loading…"}</span>
    </div>
  );
}

/** A failed load, with a retry (re-pulls the data like the header's Refresh). "Not available for this league"
 * is shown as an empty state, not an error. */
export function ErrorBox({ message }: { message: string }) {
  const { refresh, refreshing } = useStore();
  if (message.startsWith("Not available")) {
    return <Empty>{message} Pick another league in the header.</Empty>;
  }
  return (
    <div role="alert" className="card flex flex-wrap items-center gap-3 border-ball/30 bg-ball/5 px-5 py-4 text-sm">
      <AlertTriangle className="h-4 w-4 shrink-0 text-ball" />
      <span className="text-fg">
        <span className="font-semibold text-ball">Couldn't load this.</span> {message}
      </span>
      <button className="btn ml-auto" onClick={() => void refresh()} disabled={refreshing}>
        <RotateCw className={cn("h-4 w-4", refreshing && "animate-spin")} />
        Try again
      </button>
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return (
    <div className="card flex flex-col items-center justify-center gap-2 px-6 py-14 text-center text-sm text-muted">
      <Inbox className="h-6 w-6 text-faint" />
      {children}
    </div>
  );
}

export function PageTitle({ title, desc, icon }: { title: string; desc?: string; icon?: ReactNode }) {
  return (
    <div className="mb-6 animate-fade-up">
      <div className="flex items-center gap-3">
        {icon && (
          <span className="flex h-9 w-9 items-center justify-center rounded-xl border border-accent/25 bg-accent/10 text-accent">
            {icon}
          </span>
        )}
        <h1 className="text-2xl font-bold tracking-tight text-fg sm:text-[26px]">{title}</h1>
      </div>
      {desc && <p className="mt-2 max-w-3xl text-sm leading-relaxed text-muted">{desc}</p>}
    </div>
  );
}

export function StatTile({
  label,
  value,
  hint,
  icon,
}: {
  label: string;
  value: ReactNode;
  hint?: string;
  icon?: ReactNode;
}) {
  return (
    <Card className="relative overflow-hidden px-4 py-3.5">
      <div className="absolute inset-x-0 top-0 h-px bg-grad opacity-60" />
      <div className="flex items-center gap-1.5">
        {icon && <span className="text-accent">{icon}</span>}
        <div className="eyebrow">{label}</div>
      </div>
      <div className="mt-1.5 stat-num text-xl font-bold text-fg">{value}</div>
      {hint && <div className="mt-0.5 text-xs text-muted">{hint}</div>}
    </Card>
  );
}

/** A row of mutually exclusive options (metric / tab / mode switchers). Keyboard-friendly radio group. */
export function Segmented<T extends string>({
  value,
  onChange,
  options,
  label,
  className,
}: {
  value: T;
  onChange: (v: T) => void;
  options: { value: T; label: ReactNode }[];
  label: string;
  className?: string;
}) {
  return (
    <div role="radiogroup" aria-label={label} className={cn("seg", className)}>
      {options.map((o) => (
        <button
          key={o.value}
          role="radio"
          aria-checked={o.value === value}
          onClick={() => onChange(o.value)}
          className={cn("seg-btn", o.value === value && "seg-btn-active")}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

/** "data to 15 Dec 2024 · stale" — for a league whose data has stopped updating (collections meta `stale`). */
export function StaleBadge({ asOf, className }: { asOf?: string | null; className?: string }) {
  const d = asOf ? new Date(`${asOf}T00:00:00`) : null;
  const label =
    d && !Number.isNaN(d.getTime())
      ? d.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" })
      : null;
  return (
    <span
      title="This league's data has stopped updating — its numbers end at this date and may be out of date."
      className={cn(
        "inline-flex shrink-0 items-center gap-1 rounded-md border border-gold/40 bg-gold/10 px-1.5 py-0.5 text-[10px] font-semibold text-gold",
        className,
      )}
    >
      {label ? `data to ${label} · stale` : "stale data"}
    </span>
  );
}
