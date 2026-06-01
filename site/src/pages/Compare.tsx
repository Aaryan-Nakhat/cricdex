import { Fragment, useState } from "react";
import { GitCompareArrows, Plus, X } from "lucide-react";
import {
  Radar,
  RadarChart,
  PolarGrid,
  PolarAngleAxis,
  PolarRadiusAxis,
  ResponsiveContainer,
  Legend,
} from "recharts";
import { useStore } from "@/lib/store";
import { usePlayers } from "@/lib/usePlayers";
import { useAsync } from "@/lib/useAsync";
import { getProfile, type Profile } from "@/lib/data";
import { Combobox } from "@/components/Combobox";
import { PageTitle, Card, CardHeader, Spinner, Empty } from "@/components/ui";
import { cn, fmt } from "@/lib/utils";

const SERIES_COLORS = ["#34d399", "#a3e635", "#60a5fa", "#f43f5e"];

function num(v: unknown): number | null {
  if (v === null || v === undefined || v === "") return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}

interface Row {
  label: string;
  get: (p: Profile) => number | null;
  digits: number;
  better: "high" | "low";
  group: string;
}

const ROWS: Row[] = [
  { group: "Bayesian skill", label: "Batting · scoring", digits: 3, better: "high", get: (p) => num((p.bayes?.bayes_batter as any)?.skill) },
  { group: "Bayesian skill", label: "Batting · survival", digits: 3, better: "high", get: (p) => num((p.bayes?.bayes_batter as any)?.survival_skill) },
  { group: "Bayesian skill", label: "Batting value", digits: 3, better: "high", get: (p) => num((p.bayes?.bayes_batter as any)?.value) },
  { group: "Bayesian skill", label: "Bowling · economy", digits: 3, better: "high", get: (p) => num((p.bayes?.bayes_bowler as any)?.skill) },
  { group: "Bayesian skill", label: "Bowling · strike", digits: 3, better: "high", get: (p) => num((p.bayes?.bayes_bowler as any)?.strike_skill) },
  { group: "Career", label: "Runs", digits: 0, better: "high", get: (p) => num((p.career as any)?.career_runs) },
  { group: "Career", label: "Balls faced", digits: 0, better: "high", get: (p) => num((p.career as any)?.career_balls_faced) },
  { group: "Career", label: "Strike rate", digits: 1, better: "high", get: (p) => {
    const r = num((p.career as any)?.career_runs); const b = num((p.career as any)?.career_balls_faced);
    return r !== null && b ? (r / b) * 100 : null;
  } },
  { group: "Career", label: "Wickets", digits: 0, better: "high", get: (p) => num((p.career as any)?.career_wickets) },
  { group: "Metrics", label: "Pressure SR", digits: 1, better: "high", get: (p) => num((p.metrics as any)?.pressure_runs?.pressure_sr_per_100_balls) },
  { group: "Metrics", label: "Counter-attack SR", digits: 1, better: "high", get: (p) => num((p.metrics as any)?.counter_attack?.counter_attack_sr) },
  { group: "Metrics", label: "Boundary %", digits: 1, better: "low", get: (p) => num((p.metrics as any)?.boundary_dependency?.bdr_pct) },
  { group: "Metrics", label: "Dot recovery", digits: 2, better: "high", get: (p) => num((p.metrics as any)?.dot_ball_recovery?.runs_per_6_after_dot) },
];

const GROUPS = ["Bayesian skill", "Career", "Metrics"];

export function Compare() {
  const { collection } = useStore();
  const { options } = usePlayers(collection);
  const [cids, setCids] = useState<(string | null)[]>([null, null]);

  const profiles = useAsync(async () => {
    const ids = cids.filter(Boolean) as string[];
    return Promise.all(ids.map((id) => getProfile(collection, id)));
  }, [collection, cids.join(",")]);

  const loaded = (profiles.data ?? []).filter(Boolean) as Profile[];

  // radar over the 4 bayes axes, min-max normalised across the loaded set
  const radarData = (() => {
    const axes: { key: string; label: string }[] = [
      { key: "bat_skill", label: "Score" },
      { key: "bat_survival", label: "Survive" },
      { key: "bowl_skill", label: "Economy" },
      { key: "bowl_strike", label: "Strike" },
    ];
    const valOf = (p: Profile, k: string): number | null => {
      const b = p.bayes?.bayes_batter as any, w = p.bayes?.bayes_bowler as any;
      if (k === "bat_skill") return num(b?.skill);
      if (k === "bat_survival") return num(b?.survival_skill);
      if (k === "bowl_skill") return num(w?.skill);
      if (k === "bowl_strike") return num(w?.strike_skill);
      return null;
    };
    return axes.map((ax) => {
      const vals = loaded.map((p) => valOf(p, ax.key));
      const finite = vals.filter((v): v is number => v !== null);
      const min = Math.min(...finite, 0), max = Math.max(...finite, 0.01);
      const row: Record<string, number | string> = { axis: ax.label };
      loaded.forEach((p, i) => {
        const v = valOf(p, ax.key);
        row[`p${i}`] = v === null ? 0 : ((v - min) / (max - min || 1)) * 100;
      });
      return row;
    });
  })();

  function setAt(i: number, v: string | null) {
    setCids((c) => c.map((x, j) => (j === i ? v : x)));
  }

  return (
    <>
      <PageTitle
        title="Compare players"
        icon={<GitCompareArrows className="h-6 w-6" />}
        desc="Put two to four players side by side across every number — Bayesian skill axes, career totals, and the novel metrics. Greener cell wins each row."
      />

      <div className="mb-6 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {cids.map((cid, i) => (
          <div key={i} className="relative">
            <Combobox options={options} value={cid} onChange={(v) => setAt(i, v)} placeholder={`Player ${i + 1}`} />
            {cids.length > 2 && (
              <button
                className="absolute -right-1 -top-1 rounded-full bg-card p-0.5 text-muted hover:text-ball"
                onClick={() => setCids((c) => c.filter((_, j) => j !== i))}
              >
                <X className="h-3.5 w-3.5" />
              </button>
            )}
          </div>
        ))}
        {cids.length < 4 && (
          <button className="btn h-[42px]" onClick={() => setCids((c) => [...c, null])}>
            <Plus className="h-4 w-4" /> Add player
          </button>
        )}
      </div>

      {loaded.length < 2 ? (
        <Empty>Pick at least two players to compare.</Empty>
      ) : profiles.loading ? (
        <Spinner label="Loading players…" />
      ) : (
        <div className="space-y-5 animate-fade-up">
          {/* radar */}
          <Card>
            <CardHeader title="Skill shape" subtitle="Four Bayesian axes, min-max scaled across the selected players" />
            <div className="h-80 p-4">
              <ResponsiveContainer width="100%" height="100%">
                <RadarChart data={radarData} outerRadius="72%">
                  <PolarGrid stroke="#1e2836" />
                  <PolarAngleAxis dataKey="axis" tick={{ fill: "#8a97a8", fontSize: 12 }} />
                  <PolarRadiusAxis domain={[0, 100]} tick={false} axisLine={false} />
                  {loaded.map((p, i) => (
                    <Radar
                      key={i}
                      name={p.name}
                      dataKey={`p${i}`}
                      stroke={SERIES_COLORS[i]}
                      fill={SERIES_COLORS[i]}
                      fillOpacity={0.18}
                      strokeWidth={2}
                    />
                  ))}
                  <Legend wrapperStyle={{ fontSize: 12, color: "#e6edf3" }} />
                </RadarChart>
              </ResponsiveContainer>
            </div>
          </Card>

          {/* comparison table */}
          <Card className="overflow-hidden">
            <CardHeader title="Side by side" subtitle="Best value in each row is highlighted" />
            <div className="overflow-auto">
              <table className="w-full border-collapse">
                <thead>
                  <tr>
                    <th className="th">Metric</th>
                    {loaded.map((p, i) => (
                      <th key={i} className="th text-right" style={{ color: SERIES_COLORS[i] }}>
                        {p.name}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {GROUPS.map((g) => (
                    <Fragment key={g}>
                      <tr>
                        <td colSpan={loaded.length + 1} className="border-t border-border bg-surface/40 px-3 py-1.5 text-[11px] font-semibold uppercase tracking-wider text-muted">
                          {g}
                        </td>
                      </tr>
                      {ROWS.filter((r) => r.group === g).map((row) => {
                        const vals = loaded.map((p) => row.get(p));
                        const finite = vals.filter((v): v is number => v !== null);
                        const best = finite.length
                          ? row.better === "high"
                            ? Math.max(...finite)
                            : Math.min(...finite)
                          : null;
                        return (
                          <tr key={row.label} className="hover:bg-surface/40">
                            <td className="td text-muted">{row.label}</td>
                            {vals.map((v, i) => (
                              <td
                                key={i}
                                className={cn(
                                  "td stat-num text-right",
                                  v !== null && best !== null && v === best
                                    ? "font-bold text-accent-glow"
                                    : "text-fg",
                                )}
                              >
                                {fmt(v, row.digits)}
                              </td>
                            ))}
                          </tr>
                        );
                      })}
                    </Fragment>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        </div>
      )}
    </>
  );
}
