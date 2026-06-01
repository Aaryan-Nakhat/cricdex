import { useMemo, useState } from "react";
import { Medal, CalendarRange } from "lucide-react";
import { useStore } from "@/lib/store";
import { useAsync } from "@/lib/useAsync";
import { getRecords } from "@/lib/data";
import { PageTitle, Card, Spinner, ErrorBox, Empty, InfoTip } from "@/components/ui";
import { cn, fmt } from "@/lib/utils";

function yearOf(v: unknown): number | null {
  if (typeof v !== "string") return null;
  const y = Number(v.slice(0, 4));
  return Number.isFinite(y) ? y : null;
}

const LABELS: Record<string, string> = {
  highest_individual_innings: "Highest individual innings",
  fastest_fifty: "Fastest fifties",
  fastest_hundred: "Fastest hundreds",
  most_sixes_innings: "Most sixes in an innings",
  career_run_leaders: "Career run leaders",
  best_bowling_innings: "Best bowling figures",
  career_wicket_leaders: "Career wicket leaders",
  highest_team_totals: "Highest team totals",
  highest_runs_in_over: "Most runs in an over",
};

const COL_LABELS: Record<string, string> = {
  batter: "Batter",
  bowler: "Bowler",
  team: "Team",
  match_date: "Date",
  venue: "Venue",
  runs: "Runs",
  balls: "Balls",
  fours: "4s",
  sixes: "6s",
  wickets: "Wkts",
  runs_conceded: "Runs",
  match_id: "Match",
  total: "Total",
  over_runs: "Runs",
};

function prettyCell(v: unknown): string {
  if (v === null || v === undefined) return "—";
  if (typeof v === "number") return fmt(v, Number.isInteger(v) ? 0 : 2);
  return String(v);
}

export function Records() {
  const { collection } = useStore();
  const { data, loading, error } = useAsync(() => getRecords(collection), [collection]);
  const [tab, setTab] = useState<string | null>(null);

  const keys = data ? Object.keys(data).filter((k) => (data[k]?.length ?? 0) > 0) : [];
  const active = tab && keys.includes(tab) ? tab : keys[0];
  const rawRows = active && data ? data[active] : [];
  const cols = rawRows.length ? Object.keys(rawRows[0]).filter((c) => c !== "match_id") : [];
  const hasDate = rawRows.some((r) => yearOf(r.match_date) !== null);

  // year span present in this record table (only for dated records)
  const [span, setSpan] = useState<{ from: number; to: number } | null>(null);
  const bounds = useMemo(() => {
    const ys = rawRows.map((r) => yearOf(r.match_date)).filter((y): y is number => y !== null);
    return ys.length ? { min: Math.min(...ys), max: Math.max(...ys) } : null;
  }, [rawRows]);
  const range = span ?? (bounds ? { from: bounds.min, to: bounds.max } : null);
  const rows =
    hasDate && range
      ? rawRows.filter((r) => {
          const y = yearOf(r.match_date);
          return y === null || (y >= range.from && y <= range.to);
        })
      : rawRows;

  return (
    <>
      <PageTitle
        title="Record books"
        icon={<Medal className="h-6 w-6" />}
        desc="The all-time tables for this collection — biggest innings, fastest milestones, career leaders, and team feats — straight from the ball-by-ball record."
      />

      {loading ? (
        <Spinner label="Loading records…" />
      ) : error ? (
        <ErrorBox message={error} />
      ) : keys.length === 0 ? (
        <Empty>No records available for {collection}.</Empty>
      ) : (
        <>
          <div className="mb-5 flex flex-wrap gap-2">
            {keys.map((k) => (
              <button
                key={k}
                onClick={() => setTab(k)}
                className={cn(
                  "rounded-lg border px-3 py-1.5 text-sm font-medium transition-all",
                  k === active
                    ? "border-accent/40 bg-accent/10 text-accent-glow"
                    : "border-border bg-surface text-muted hover:text-fg",
                )}
              >
                {LABELS[k] ?? k}
              </button>
            ))}
          </div>

          {hasDate && bounds && range && (
            <div className="mb-4 flex flex-wrap items-center gap-3 rounded-lg border border-border bg-surface/50 px-4 py-3 text-sm text-muted">
              <span className="flex items-center gap-2">
                <CalendarRange className="h-4 w-4 text-accent" /> Year range
                <InfoTip title="Year filter">
                  Limits this record table to feats between the two years. Only applies to dated
                  records (career-leader tables have no single date, so they're unaffected).
                </InfoTip>
              </span>
              <input type="number" className="input w-24 py-1.5" min={bounds.min} max={range.to}
                value={range.from} onChange={(e) => setSpan({ from: Number(e.target.value), to: range.to })} />
              <span>to</span>
              <input type="number" className="input w-24 py-1.5" min={range.from} max={bounds.max}
                value={range.to} onChange={(e) => setSpan({ from: range.from, to: Number(e.target.value) })} />
              {span && (
                <button onClick={() => setSpan(null)} className="text-xs text-muted hover:text-ball">reset</button>
              )}
              <span className="ml-auto text-xs">
                <span className="font-semibold text-fg">{rows.length}</span> of {rawRows.length}
              </span>
            </div>
          )}

          <Card className="overflow-hidden">
            <div className="overflow-auto" style={{ maxHeight: "70vh" }}>
              <table className="w-full border-collapse">
                <thead>
                  <tr>
                    <th className="th w-12 text-right">#</th>
                    {cols.map((c) => (
                      <th
                        key={c}
                        className={cn("th", typeof rows[0]?.[c] === "number" && "text-right")}
                      >
                        {COL_LABELS[c] ?? c.replace(/_/g, " ")}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r, i) => (
                    <tr key={i} className="hover:bg-surface/50">
                      <td className="td text-right stat-num text-muted">{i + 1}</td>
                      {cols.map((c) => {
                        const v = r[c];
                        const isNum = typeof v === "number";
                        return (
                          <td
                            key={c}
                            className={cn(
                              "td",
                              isNum && "stat-num text-right",
                              (c === "batter" || c === "bowler" || c === "team") && "font-medium text-fg",
                            )}
                          >
                            {prettyCell(v)}
                          </td>
                        );
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        </>
      )}
    </>
  );
}
