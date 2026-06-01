import { useMemo, useState } from "react";
import { MapPin } from "lucide-react";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Cell,
} from "recharts";
import { useStore } from "@/lib/store";
import { useAsync } from "@/lib/useAsync";
import { getVenues } from "@/lib/data";
import { Combobox } from "@/components/Combobox";
import { PageTitle, Card, CardHeader, Spinner, Empty, StatTile } from "@/components/ui";
import { fmt } from "@/lib/utils";

const PHASE_ORDER = ["powerplay", "middle", "death"];

export function Venues() {
  const { collection } = useStore();
  const { data, loading } = useAsync(() => getVenues(collection), [collection]);
  const [venue, setVenue] = useState<string | null>(null);

  const names = data ? Object.keys(data) : [];
  const options = names.map((n) => ({ value: n, label: n }));
  const selected = venue && data ? data[venue] : null;

  const phaseRows = useMemo(() => {
    if (!selected) return [];
    const rows = (selected.phase_run_rates as Record<string, unknown>[]) ?? [];
    return [...rows]
      .filter((r) => PHASE_ORDER.includes(String(r.phase)))
      .sort((a, b) => PHASE_ORDER.indexOf(String(a.phase)) - PHASE_ORDER.indexOf(String(b.phase)))
      .map((r) => ({
        phase: String(r.phase),
        rpo: Number(r.rpo),
        dot_pct: Number(r.dot_pct),
        boundary_pct: Number(r.boundary_pct),
      }));
  }, [selected]);

  const totals = (selected?.innings_totals as Record<string, unknown>[])?.filter(
    (r) => Number(r.innings_idx) <= 1 && Number(r.innings_count) >= 3,
  );
  const chase = (selected?.chase_vs_set as Record<string, unknown>[])?.[0];
  const firstWinPct =
    chase && Number(chase.decided_matches)
      ? (Number(chase.first_innings_team_wins) / Number(chase.decided_matches)) * 100
      : null;

  return (
    <>
      <PageTitle
        title="Venue conditions"
        icon={<MapPin className="h-6 w-6" />}
        desc="What a ground actually plays like — typical first- vs second-innings totals, how scoring breaks down by phase, and whether batting first or chasing wins more often here."
      />

      <div className="mb-6 max-w-md">
        <Combobox options={options} value={venue} onChange={setVenue} placeholder={loading ? "Loading venues…" : "Search a venue…"} />
      </div>

      {!venue ? (
        <Empty>Pick a venue to see how it plays.</Empty>
      ) : loading ? (
        <Spinner />
      ) : !selected ? (
        <Empty>No data for this venue.</Empty>
      ) : (
        <div className="space-y-5 animate-fade-up">
          {/* headline tiles */}
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            {totals?.[0] && (
              <StatTile label="1st innings avg" value={fmt(Number(totals[0].avg_runs), 0)} hint={`${totals[0].innings_count} innings`} />
            )}
            {totals?.[1] && (
              <StatTile label="2nd innings avg" value={fmt(Number(totals[1].avg_runs), 0)} hint={`${totals[1].innings_count} innings`} />
            )}
            {firstWinPct !== null && (
              <StatTile label="Bat-first win %" value={`${firstWinPct.toFixed(0)}%`} hint={`${chase!.decided_matches} decided`} />
            )}
            {firstWinPct !== null && (
              <StatTile label="Chase win %" value={`${(100 - firstWinPct).toFixed(0)}%`} hint="2nd-innings team" />
            )}
          </div>

          {/* phase run rate */}
          <Card>
            <CardHeader title="Scoring by phase" subtitle="Run rate, dot-ball % and boundary % across powerplay / middle / death" />
            <div className="h-72 p-4">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={phaseRows} barGap={4}>
                  <CartesianGrid stroke="#1e2836" vertical={false} />
                  <XAxis dataKey="phase" tick={{ fill: "#8a97a8", fontSize: 12 }} tickFormatter={(s) => s[0].toUpperCase() + s.slice(1)} />
                  <YAxis tick={{ fill: "#8a97a8", fontSize: 12 }} />
                  <Tooltip
                    contentStyle={{ background: "#141b27", border: "1px solid #1e2836", borderRadius: 10, fontSize: 12 }}
                    labelStyle={{ color: "#e6edf3" }}
                  />
                  <Bar dataKey="rpo" name="Runs / over" radius={[4, 4, 0, 0]}>
                    {phaseRows.map((_, i) => (
                      <Cell key={i} fill="#34d399" />
                    ))}
                  </Bar>
                  <Bar dataKey="dot_pct" name="Dot %" radius={[4, 4, 0, 0]} fill="#475569" />
                  <Bar dataKey="boundary_pct" name="Boundary %" radius={[4, 4, 0, 0]} fill="#a3e635" />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </Card>

          {/* innings totals table */}
          {totals && totals.length > 0 && (
            <Card className="overflow-hidden">
              <CardHeader title="Innings totals" subtitle="Average and median by batting position" />
              <div className="overflow-auto">
                <table className="w-full border-collapse">
                  <thead>
                    <tr>
                      <th className="th">Innings</th>
                      <th className="th text-right">Sample</th>
                      <th className="th text-right">Avg runs</th>
                      <th className="th text-right">Median</th>
                      <th className="th text-right">Avg wkts</th>
                    </tr>
                  </thead>
                  <tbody>
                    {totals.map((r, i) => (
                      <tr key={i} className="hover:bg-surface/50">
                        <td className="td font-medium text-fg">{Number(r.innings_idx) === 0 ? "Batting first" : "Chasing"}</td>
                        <td className="td stat-num text-right text-muted">{String(r.innings_count)}</td>
                        <td className="td stat-num text-right">{fmt(Number(r.avg_runs), 1)}</td>
                        <td className="td stat-num text-right">{fmt(Number(r.median_runs), 0)}</td>
                        <td className="td stat-num text-right">{fmt(Number(r.avg_wickets), 1)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Card>
          )}
        </div>
      )}
    </>
  );
}
