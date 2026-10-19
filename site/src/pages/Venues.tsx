import { useMemo } from "react";
import { MapPin } from "lucide-react";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Legend,
} from "recharts";
import { useStore } from "@/lib/store";
import { useAsync } from "@/lib/useAsync";
import { getVenues } from "@/lib/data";
import { Combobox } from "@/components/Combobox";
import { PageTitle, Card, CardHeader, Spinner, Empty, StatTile, ErrorBox } from "@/components/ui";
import { useTheme } from "@/lib/theme";
import { fmt } from "@/lib/utils";
import { hasKey, useClearOnChange, useUrlId } from "@/lib/useUrlState";

const PHASE_ORDER = ["powerplay", "middle", "death"];

export function Venues() {
  const { collection } = useStore();
  const { data, loading, error } = useAsync(() => getVenues(collection), [collection]);
  // the ground lives in the URL (`?venue=…`) so a link reproduces the view
  const [venue, setVenue] = useUrlId("venue", { has: (v) => hasKey(data, v) }, !!data);
  const { colors } = useTheme();
  // grounds are per league: a switch clears the pick
  useClearOnChange(collection, ["venue"]);

  const names = data ? Object.keys(data) : [];
  // search matches a ground's other names too ("Kotla" finds Arun Jaitley Stadium); a former name shows as a hint
  const options = names.map((n) => {
    const aliases = (data?.[n]?.aliases as string[] | undefined) ?? [];
    const short = n.split(",")[0].toLowerCase();
    const former = aliases.find((a) => !a.toLowerCase().startsWith(short));
    return { value: n, label: n, search: aliases.join(" "), hint: former ? `was ${former.split(",")[0]}` : undefined };
  });
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

  // the format this ground has the most innings in (a league is one format, a mixed collection may not be)
  const allTotals = (selected?.innings_totals as Record<string, unknown>[] | undefined) ?? [];
  const mainType = useMemo(() => {
    const by = new Map<string, number>();
    for (const r of allTotals) by.set(String(r.match_type ?? ""), (by.get(String(r.match_type ?? "")) ?? 0) + Number(r.innings_count));
    return [...by.entries()].sort((a, b) => b[1] - a[1])[0]?.[0];
  }, [allTotals]);
  const totals = allTotals.filter(
    (r) => String(r.match_type ?? "") === mainType && Number(r.innings_idx) <= 1 && Number(r.innings_count) >= 3,
  );
  // look innings up by number, never by position in the list
  const first = totals.find((r) => Number(r.innings_idx) === 0);
  const second = totals.find((r) => Number(r.innings_idx) === 1);
  // the par moves with the era: the last three seasons here, and the season-by-season series
  const recentSeasons = (selected?.recent_seasons as string[] | undefined) ?? [];
  const recentTotals = ((selected?.innings_totals_recent as Record<string, unknown>[] | undefined) ?? []).filter(
    (r) => String(r.match_type ?? "") === mainType && Number(r.innings_idx) <= 1 && Number(r.innings_count) >= 3,
  );
  const recentFirst = recentTotals.find((r) => Number(r.innings_idx) === 0);
  const recentSecond = recentTotals.find((r) => Number(r.innings_idx) === 1);
  const bySeason = useMemo(() => {
    const rows = ((selected?.innings_by_season as Record<string, unknown>[] | undefined) ?? []).filter(
      (r) => String(r.match_type ?? "") === mainType,
    );
    const out = new Map<string, { season: string; first?: number; second?: number; n: number }>();
    for (const r of rows) {
      const k = String(r.season);
      const e = out.get(k) ?? { season: k, n: 0 };
      if (Number(r.innings_idx) === 0) {
        e.first = Number(r.avg_runs);
        e.n = Number(r.innings_count);
      } else e.second = Number(r.avg_runs);
      out.set(k, e);
    }
    return [...out.values()].sort((a, b) => b.season.localeCompare(a.season));
  }, [selected, mainType]);
  const seasonSpan = recentSeasons.length ? `${recentSeasons[0]}–${recentSeasons[recentSeasons.length - 1]}` : "";
  const chase = (selected?.chase_vs_set as Record<string, unknown>[])?.[0];
  const firstWinPct =
    chase && Number(chase.decided_matches)
      ? (Number(chase.first_innings_team_wins) / Number(chase.decided_matches)) * 100
      : null;

  return (
    <>
      <PageTitle
        title="Venues"
        icon={<MapPin className="h-6 w-6" />}
        desc="What a ground actually plays like — typical first- vs second-innings totals, how scoring breaks down by phase, and whether batting first or chasing wins more often here."
      />

      <div className="mb-6 max-w-md">
        <Combobox options={options} value={venue} onChange={setVenue} placeholder={loading ? "Loading venues…" : "Search a venue…"} />
      </div>

      {error ? (
        <ErrorBox message={error} />
      ) : !venue ? (
        <Empty>Pick a venue to see how it plays.</Empty>
      ) : loading && !data ? (
        <Spinner label="Loading venues…" />
      ) : !selected ? (
        <Empty>No data for this venue.</Empty>
      ) : (
        <div className="space-y-5 animate-fade-up">
          {/* recent par first: scoring levels change with the era, so the last three seasons lead */}
          {(recentFirst || recentSecond) && (
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              {recentFirst && (
                <StatTile
                  label={`1st innings par, ${seasonSpan}`}
                  value={fmt(Number(recentFirst.avg_runs), 0)}
                  hint={`last ${recentSeasons.length} seasons · ${recentFirst.innings_count} innings`}
                />
              )}
              {recentSecond && (
                <StatTile
                  label={`2nd innings avg, ${seasonSpan}`}
                  value={fmt(Number(recentSecond.avg_runs), 0)}
                  hint={`last ${recentSeasons.length} seasons · ${recentSecond.innings_count} innings`}
                />
              )}
            </div>
          )}
          {/* all-time headline tiles */}
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            {first && (
              <StatTile label="1st innings avg (all-time)" value={fmt(Number(first.avg_runs), 0)} hint={`${first.innings_count} innings`} />
            )}
            {second && (
              <StatTile label="2nd innings avg (all-time)" value={fmt(Number(second.avg_runs), 0)} hint={`${second.innings_count} innings`} />
            )}
            {firstWinPct !== null && (
              <StatTile label="Bat-first win %" value={`${firstWinPct.toFixed(0)}%`} hint={`${chase!.decided_matches} decided`} />
            )}
            {firstWinPct !== null && (
              <StatTile label="Chase win %" value={`${(100 - firstWinPct).toFixed(0)}%`} hint="2nd-innings team" />
            )}
          </div>

          {/* phase scoring: run rate and percentages on their own scales */}
          <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
            <Card>
              <CardHeader title="Run rate by phase" subtitle="Runs per over in the powerplay, middle overs and death" />
              <div className="h-64 p-4">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={phaseRows}>
                    <CartesianGrid stroke={colors.grid} vertical={false} />
                    <XAxis dataKey="phase" tick={{ fill: colors.muted, fontSize: 12 }} tickFormatter={(s) => s[0].toUpperCase() + s.slice(1)} />
                    <YAxis tick={{ fill: colors.muted, fontSize: 12 }} />
                    <Tooltip
                      formatter={(v: number) => fmt(v, 2)}
                      contentStyle={{ background: colors.card, border: `1px solid ${colors.border}`, borderRadius: 10, fontSize: 12 }}
                      labelStyle={{ color: colors.fg }}
                    />
                    <Bar dataKey="rpo" name="Runs / over" radius={[6, 6, 0, 0]} fill={colors.accent} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </Card>
            <Card>
              <CardHeader title="Dots and boundaries by phase" subtitle="Share of balls that were dots or went to the rope" />
              <div className="h-64 p-4">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={phaseRows} barGap={4}>
                    <CartesianGrid stroke={colors.grid} vertical={false} />
                    <XAxis dataKey="phase" tick={{ fill: colors.muted, fontSize: 12 }} tickFormatter={(s) => s[0].toUpperCase() + s.slice(1)} />
                    <YAxis unit="%" tick={{ fill: colors.muted, fontSize: 12 }} />
                    <Tooltip
                      formatter={(v: number) => `${fmt(v, 1)}%`}
                      contentStyle={{ background: colors.card, border: `1px solid ${colors.border}`, borderRadius: 10, fontSize: 12 }}
                      labelStyle={{ color: colors.fg }}
                    />
                    <Legend wrapperStyle={{ fontSize: 12, color: colors.muted }} />
                    <Bar dataKey="dot_pct" name="Dot %" radius={[6, 6, 0, 0]} fill={colors.muted} />
                    <Bar dataKey="boundary_pct" name="Boundary %" radius={[6, 6, 0, 0]} fill={colors.gold} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </Card>
          </div>

          {/* innings totals table */}
          {totals.length > 0 && (
            <Card className="overflow-hidden">
              <CardHeader title="Innings totals (all-time)" subtitle="Average and median by batting position, every season" />
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

          {/* par by season */}
          {bySeason.length > 1 && (
            <Card className="overflow-hidden">
              <CardHeader title="Par by season" subtitle="Average first- and second-innings totals here, season by season" />
              <div className="max-h-80 overflow-auto">
                <table className="w-full border-collapse">
                  <thead>
                    <tr>
                      <th className="th">Season</th>
                      <th className="th text-right">Matches</th>
                      <th className="th text-right">1st innings</th>
                      <th className="th text-right">2nd innings</th>
                    </tr>
                  </thead>
                  <tbody>
                    {bySeason.map((r) => (
                      <tr key={r.season} className="hover:bg-surface/50">
                        <td className="td font-medium text-fg">{r.season}</td>
                        <td className="td stat-num text-right text-muted">{r.n}</td>
                        <td className="td stat-num text-right">{r.first != null ? fmt(r.first, 0) : "—"}</td>
                        <td className="td stat-num text-right">{r.second != null ? fmt(r.second, 0) : "—"}</td>
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
