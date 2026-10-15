import { Filter, RotateCcw } from "lucide-react";
import { InfoTip } from "./ui";
import {
  type Filters,
  EMPTY_FILTERS,
  ROLE_OPTS,
  BOWLING_OPTS,
  POSITION_OPTS,
  ACTIVITY_OPTS,
  FILTER_HELP,
} from "@/lib/filters";

type Dim = "minMatches" | "activity" | "role" | "bowling" | "position" | "country";

function Select({
  value,
  onChange,
  options,
  label,
}: {
  value: string;
  onChange: (v: string) => void;
  options: { value: string; label: string }[];
  label?: string;
}) {
  return (
    <select
      aria-label={label}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className="input w-auto cursor-pointer py-1.5 pr-8"
    >
      {options.map((o) => (
        <option key={o.value} value={o.value} className="bg-card">
          {o.label}
        </option>
      ))}
    </select>
  );
}

export function FilterBar({
  filters,
  onChange,
  show,
  countryOpts,
  count,
  total,
  defaults = EMPTY_FILTERS,
}: {
  filters: Filters;
  onChange: (f: Filters) => void;
  show: Dim[];
  countryOpts?: { value: string; label: string }[];
  count?: number;
  total?: number;
  /** What "reset" returns to — the page's own starting filters. */
  defaults?: Filters;
}) {
  const set = (patch: Partial<Filters>) => onChange({ ...filters, ...patch });
  const active =
    filters.minMatches > 0 ||
    filters.activity !== "all" ||
    !!filters.role ||
    !!filters.bowling ||
    !!filters.position ||
    !!filters.country;

  const helpLines = show.map((d) => `• ${labelFor(d)}: ${FILTER_HELP[d]}`).join("\n");

  return (
    <div className="mb-4 flex flex-wrap items-center gap-2.5 rounded-lg border border-border bg-surface/50 px-4 py-3">
      <div className="flex items-center gap-2 text-sm font-medium text-muted">
        <Filter className="h-4 w-4 text-accent" />
        Filters
        <InfoTip title="What you can filter">
          <div className="whitespace-pre-line">{helpLines}</div>
        </InfoTip>
      </div>

      {show.includes("minMatches") && (
        <label className="flex items-center gap-2 text-sm text-muted">
          <span>Min matches</span>
          <input
            type="range"
            min={0}
            max={100}
            value={filters.minMatches}
            onChange={(e) => set({ minMatches: Number(e.target.value) })}
            className="h-1.5 w-32 cursor-pointer accent-[rgb(var(--accent))]"
          />
          <input
            type="number"
            min={0}
            max={500}
            value={filters.minMatches}
            onChange={(e) => set({ minMatches: Math.max(0, Number(e.target.value)) })}
            className="input w-16 py-1.5"
          />
        </label>
      )}
      {show.includes("activity") && (
        <Select
          label={labelFor("activity")}
          value={filters.activity}
          onChange={(v) => set({ activity: v as Filters["activity"] })}
          options={ACTIVITY_OPTS}
        />
      )}
      {show.includes("role") && (
        <Select label={labelFor("role")} value={filters.role} onChange={(v) => set({ role: v })} options={ROLE_OPTS} />
      )}
      {show.includes("bowling") && (
        <Select label={labelFor("bowling")} value={filters.bowling} onChange={(v) => set({ bowling: v })} options={BOWLING_OPTS} />
      )}
      {show.includes("position") && (
        <Select
          label={labelFor("position")}
          value={filters.position}
          onChange={(v) => set({ position: v })}
          options={POSITION_OPTS}
        />
      )}
      {show.includes("country") && countryOpts && (
        <Select label={labelFor("country")} value={filters.country} onChange={(v) => set({ country: v })} options={countryOpts} />
      )}

      {active && (
        <button
          onClick={() => onChange({ ...defaults })}
          className="inline-flex items-center gap-1.5 text-xs text-muted hover:text-ball"
        >
          <RotateCcw className="h-3.5 w-3.5" /> reset
        </button>
      )}

      {count !== undefined && (
        <span className="ml-auto text-xs text-muted">
          <span className="font-semibold text-fg">{count}</span>
          {total !== undefined && <span className="text-muted/60"> / {total}</span>} shown
        </span>
      )}
    </div>
  );
}

function labelFor(d: Dim): string {
  return {
    minMatches: "Min matches",
    activity: "Active / retired",
    role: "Role",
    bowling: "Bowling type",
    position: "Batting position",
    country: "Country",
  }[d];
}
