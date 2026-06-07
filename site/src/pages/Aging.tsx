import { useMemo, useState } from "react";
import { TrendingUp } from "lucide-react";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Legend,
} from "recharts";
import { useStore } from "@/lib/store";
import { useAsync } from "@/lib/useAsync";
import { getAging } from "@/lib/data";
import { usePlayers } from "@/lib/usePlayers";
import { Combobox } from "@/components/Combobox";
import { PageTitle, Card, CardHeader, Spinner, ErrorBox, Empty, InfoTip } from "@/components/ui";
import { cn } from "@/lib/utils";

type Role = "batting" | "bowling";

const METRICS: Record<Role, { key: string; label: string; overlay: string | null }[]> = {
  batting: [
    { key: "sr", label: "Strike rate", overlay: "sr" },
    { key: "average", label: "Average", overlay: null },
  ],
  bowling: [
    { key: "economy", label: "Economy", overlay: "economy" },
    { key: "strike_rate", label: "Strike rate", overlay: null },
  ],
};

export function Aging() {
  const { collection } = useStore();
  const { options } = usePlayers(collection);
  const { data, loading, error } = useAsync(() => getAging(collection), [collection]);
  const [role, setRole] = useState<Role>("batting");
  const [metricKey, setMetricKey] = useState("sr");
  const [cid, setCid] = useState<string | null>(null);

  const metrics = METRICS[role];
  const metric = metrics.find((m) => m.key === metricKey) ?? metrics[0];

  const chartData = useMemo(() => {
    if (!data) return [];
    const curve = role === "batting" ? data.batting : data.bowling;
    const overlay = metric.overlay && cid ? data.players[cid] : null;
    const overlayByAge = new Map<number, number>();
    if (overlay && metric.overlay) {
      const wantRole = role === "batting" ? "batter" : "bowler";
      if (overlay.role === wantRole) {
        for (const p of overlay.points) {
          const v = (p as unknown as Record<string, number | undefined>)[metric.overlay];
          if (v != null) overlayByAge.set(p.age, v);
        }
      }
    }
    return curve.map((r) => ({
      age: r.age,
      avg: (r as unknown as Record<string, number | null>)[metric.key],
      player: overlayByAge.get(r.age) ?? null,
    }));
  }, [data, role, metric, cid]);

  const selName = options.find((o) => o.value === cid)?.label ?? "player";

  return (
    <>
      <PageTitle
        title="Aging curves"
        icon={<TrendingUp className="h-6 w-6" />}
        desc="How performance changes with age. Each player-season is a data point, averaged by age into a curve. Pick a player to overlay their own trajectory."
      />

      <div className="mb-4 flex flex-wrap items-center gap-3">
        <div className="flex gap-2">
          {(["batting", "bowling"] as Role[]).map((r) => (
            <button
              key={r}
              onClick={() => {
                setRole(r);
                setMetricKey(METRICS[r][0].key);
              }}
              className={cn(
                "rounded-lg border px-3.5 py-2 text-sm font-semibold capitalize transition-colors",
                role === r
                  ? "border-accent/50 bg-accent/10 text-accent-glow"
                  : "border-border bg-surface text-muted hover:text-fg",
              )}
            >
              {r}
            </button>
          ))}
        </div>
        <div className="flex gap-2">
          {metrics.map((m) => (
            <button
              key={m.key}
              onClick={() => setMetricKey(m.key)}
              className={cn(
                "rounded-lg border px-3 py-1.5 text-sm transition-colors",
                m.key === metric.key
                  ? "border-accent/40 bg-accent/10 text-accent-glow"
                  : "border-border bg-surface text-muted hover:text-fg",
              )}
            >
              {m.label}
            </button>
          ))}
        </div>
        {metric.overlay && (
          <Combobox
            options={options}
            value={cid}
            onChange={setCid}
            placeholder="Overlay a player…"
            className="max-w-xs flex-1"
          />
        )}
      </div>

      {loading ? (
        <Spinner />
      ) : error ? (
        <ErrorBox message={error} />
      ) : !data || chartData.length === 0 ? (
        <Empty>No aging data for this collection (needs player dates of birth).</Empty>
      ) : (
        <Card>
          <CardHeader
            title={`${role === "batting" ? "Batting" : "Bowling"} ${metric.label.toLowerCase()} by age`}
            subtitle="Average across all qualifying player-seasons (≥60 balls)"
            right={
              <InfoTip title="Coverage + caveats">
                Ages come from Wikidata dates of birth, which cover only ~a third of players (elite /
                international skew). Survivorship isn't corrected — weaker players retire earlier, so
                the late-career end is the survivors. Treat the curve as indicative, not definitive.
              </InfoTip>
            }
          />
          <div className="h-96 p-4">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={chartData} margin={{ top: 8, right: 16, bottom: 8, left: 0 }}>
                <CartesianGrid stroke="#1e2836" vertical={false} />
                <XAxis dataKey="age" tick={{ fill: "#8a97a8", fontSize: 12 }} />
                <YAxis tick={{ fill: "#8a97a8", fontSize: 12 }} domain={["auto", "auto"]} />
                <Tooltip
                  contentStyle={{
                    background: "#141b27",
                    border: "1px solid #1e2836",
                    borderRadius: 10,
                    fontSize: 12,
                  }}
                  labelStyle={{ color: "#e6edf3" }}
                  labelFormatter={(a) => `Age ${a}`}
                />
                <Legend wrapperStyle={{ fontSize: 12 }} />
                <Line
                  type="monotone"
                  dataKey="avg"
                  name={`All players (${metric.label})`}
                  stroke="#34d399"
                  strokeWidth={2.5}
                  dot={false}
                />
                {metric.overlay && cid && (
                  <Line
                    type="monotone"
                    dataKey="player"
                    name={selName}
                    stroke="#fbbf24"
                    strokeWidth={2}
                    dot={{ r: 2 }}
                    connectNulls
                  />
                )}
              </LineChart>
            </ResponsiveContainer>
          </div>
        </Card>
      )}
    </>
  );
}
