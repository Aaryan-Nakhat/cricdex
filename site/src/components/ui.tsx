import { useEffect, useRef, useState, type ReactNode } from "react";
import { Info } from "lucide-react";
import { cn } from "@/lib/utils";

/** A small "i" button that pops a panel on click. Closes on outside-click. */
export function InfoTip({
  title,
  children,
  className,
}: {
  title?: string;
  children: ReactNode;
  className?: string;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    function onDoc(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, []);
  return (
    <div ref={ref} className={cn("relative inline-flex", className)}>
      <button
        type="button"
        aria-label="How it's calculated"
        onClick={() => setOpen((o) => !o)}
        className={cn(
          "inline-flex h-5 w-5 items-center justify-center rounded-full border text-[11px] transition-colors",
          open
            ? "border-accent/50 bg-accent/15 text-accent-glow"
            : "border-border bg-surface text-muted hover:border-accent/40 hover:text-accent-glow",
        )}
      >
        <Info className="h-3 w-3" />
      </button>
      {open && (
        <div className="absolute left-1/2 top-7 z-50 w-80 -translate-x-1/2 rounded-lg border border-border bg-card p-3.5 text-left shadow-card">
          {title && <div className="mb-1.5 text-xs font-semibold text-accent-glow">{title}</div>}
          <div className="text-xs leading-relaxed text-muted">{children}</div>
        </div>
      )}
    </div>
  );
}

export function Card({
  className,
  children,
}: {
  className?: string;
  children: ReactNode;
}) {
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
  tone?: "muted" | "accent" | "ball" | "willow";
  className?: string;
}) {
  const tones = {
    muted: "border-border bg-surface text-muted",
    accent: "border-accent/30 bg-accent/10 text-accent-glow",
    ball: "border-ball/30 bg-ball/10 text-ball",
    willow: "border-willow/30 bg-willow/10 text-willow",
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
    <div className="flex items-center justify-center gap-3 py-16 text-muted">
      <span className="h-5 w-5 animate-spin rounded-full border-2 border-border border-t-accent" />
      {label && <span className="text-sm">{label}</span>}
    </div>
  );
}

export function ErrorBox({ message }: { message: string }) {
  return (
    <div className="card border-ball/30 bg-ball/5 px-5 py-4 text-sm text-ball">
      <span className="font-semibold">Couldn't load data.</span> {message}
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return (
    <div className="card flex flex-col items-center justify-center gap-2 px-6 py-16 text-center text-muted">
      {children}
    </div>
  );
}

export function PageTitle({
  title,
  desc,
  icon,
}: {
  title: string;
  desc?: string;
  icon?: ReactNode;
}) {
  return (
    <div className="mb-6 animate-fade-up">
      <div className="flex items-center gap-2.5">
        {icon && <span className="text-accent">{icon}</span>}
        <h1 className="text-2xl font-bold tracking-tight text-fg">{title}</h1>
      </div>
      {desc && <p className="mt-1.5 max-w-3xl text-sm leading-relaxed text-muted">{desc}</p>}
    </div>
  );
}

/** Inline magnitude bar behind a numeric cell — frac in [0,1]. */
export function Bar({ frac }: { frac: number }) {
  const w = Math.max(0, Math.min(1, frac)) * 100;
  return (
    <div className="mt-1 h-1 w-full overflow-hidden rounded-full bg-border/60">
      <div
        className="h-full rounded-full bg-gradient-to-r from-accent-dim to-accent-glow"
        style={{ width: `${w}%` }}
      />
    </div>
  );
}

export function StatTile({
  label,
  value,
  hint,
}: {
  label: string;
  value: ReactNode;
  hint?: string;
}) {
  return (
    <Card className="px-4 py-3">
      <div className="text-[11px] font-medium uppercase tracking-wider text-muted">{label}</div>
      <div className="mt-1 stat-num text-xl font-bold text-fg">{value}</div>
      {hint && <div className="mt-0.5 text-xs text-muted">{hint}</div>}
    </Card>
  );
}
