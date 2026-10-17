import { memo, useDeferredValue, useEffect, useMemo, useRef } from "react";
import { TrendingUp, X } from "lucide-react";
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
import { displayName, getAging, type AgingData } from "@/lib/data";
import { usePlayers } from "@/lib/usePlayers";
import { Combobox } from "@/components/Combobox";
import { PageTitle, Card, CardHeader, Spinner, ErrorBox, Empty, InfoTip } from "@/components/ui";
import { useTheme } from "@/lib/theme";
import { cn } from "@/lib/utils";
import { useClearOnChange, useUrlParams, useUrlState } from "@/lib/useUrlState";

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

const MAX_PLAYERS = 5;

/** One player's own season-by-season series for a discipline + metric, as age -> value. Cached per data file so
 * adding a fifth player doesn't rebuild the other four. */
function useSeriesCache(data: AgingData | null) {
  const cache = useRef(new Map<string, Map<number, number>>());
  const owner = useRef<AgingData | null>(null);
  if (owner.current !== data) {
    owner.current = data;
    cache.current = new Map();
  }
  return (cid: string, role: Role, key: string): Map<number, number> => {
    const k = `${cid}|${role}|${key}`;
    const hit = cache.current.get(k);
    if (hit) return hit;
    const out = new Map<number, number>();
    for (const p of data?.players[cid]?.[role] ?? []) {
      const v = (p as unknown as Record<string, number | undefined>)[key];
      if (v != null) out.set(p.age, v);
    }
    cache.current.set(k, out);
    return out;
  };
}

interface ChartProps {
  rows: Record<string, number | null>[];
  series: { key: string; name: string; color: string }[];
  avgName: string;
  colors: ReturnType<typeof useTheme>["colors"];
}

// The chart only re-renders when its rows / series actually change; no animation, so picks feel instant.
const AgingChart = memo(function AgingChart({ rows, series, avgName, colors }: ChartProps) {
  return (
    <ResponsiveContainer width="100%" height="100%">
      <LineChart data={rows} margin={{ top: 8, right: 16, bottom: 8, left: 0 }}>
        <CartesianGrid stroke={colors.grid} vertical={false} />
        <XAxis dataKey="age" tick={{ fill: colors.muted, fontSize: 12 }} />
        <YAxis tick={{ fill: colors.muted, fontSize: 12 }} domain={["auto", "auto"]} width={44} />
        <Tooltip
          isAnimationActive={false}
          contentStyle={{ background: colors.card, border: `1px solid ${colors.border}`, borderRadius: 10, fontSize: 12 }}
          labelStyle={{ color: colors.fg }}
          labelFormatter={(a) => `Age ${a}`}
          formatter={(v: number | string) => (typeof v === "number" ? v.toFixed(1) : v)}
        />
        <Legend wrapperStyle={{ fontSize: 12, color: colors.muted }} />
        <Line
          type="monotone"
          dataKey="avg"
          name={avgName}
          stroke={colors.muted}
          strokeWidth={2.5}
          strokeDasharray="6 4"
          dot={false}
          isAnimationActive={false}
        />
        {series.map((s) => (
          <Line
            key={s.key}
            type="monotone"
            dataKey={s.key}
            name={s.name}
            stroke={s.color}
            strokeWidth={2}
            dot={{ r: 2 }}
            connectNulls
            isAnimationActive={false}
          />
        ))}
      </LineChart>
    </ResponsiveContainer>
  );
});

export function Aging() {
  const { collection } = useStore();
  const { options, players, byId } = usePlayers(collection);
  const { data, loading, error } = useAsync(() => getAging(collection), [collection]);
  // discipline, metric and overlay players live in the URL (`?role=…&metric=…&players=a,b`)
  const { params, update } = useUrlParams();
  const [role] = useUrlState<Role>("role", "batting", { valid: ["batting", "bowling"] });
  const metrics = METRICS[role];
  const [metricKey, setMetricKey] = useUrlState<string>("metric", metrics[0].key, {
    valid: metrics.map((m) => m.key),
    replace: false,
  });
  const { colors } = useTheme();
  const PALETTE = [colors.accent, colors.gold, colors.sky, colors.ball, colors.willow];
  // players are per league: a switch clears the overlays
  useClearOnChange(collection, ["players", "player"]);
  const setRole = (r: Role) => update({ role: r === "batting" ? null : r, metric: null }, { replace: false });

  // picks: `players=a,b,c` (the old single `player=` link still works)
  const ready = players.length > 0;
  const rawPicks = params.get("players") ?? params.get("player") ?? "";
  const picks = useMemo(() => {
    const list = rawPicks.split(",").filter(Boolean);
    const uniq = [...new Set(list)].slice(0, MAX_PLAYERS);
    return ready ? uniq.filter((c) => byId.has(c)) : uniq;
  }, [rawPicks, ready, byId]);
  const setPicks = (next: string[]) =>
    update({ players: next.length ? next.join(",") : null, player: null }, { replace: false });
  // tidy: unknown ids, the legacy key
  useEffect(() => {
    if (!ready) return;
    const want = picks.join(",");
    if (params.has("player") || (params.get("players") ?? "") !== want)
      update({ players: want || null, player: null });
  }, [ready, picks, params, update]);

  // the chart catches up a beat after the picks so typing / clicking never stutters
  const shownPicks = useDeferredValue(picks);

  const metric = metrics.find((m) => m.key === metricKey) ?? metrics[0];
  const seriesOf = useSeriesCache(data ?? null);

  // the league curve is built once per discipline + metric
  const base = useMemo(() => {
    if (!data) return [];
    const curve = role === "batting" ? data.batting : data.bowling;
    return curve.map((r) => ({ age: r.age, avg: (r as unknown as Record<string, number | null>)[metric.key] ?? null }));
  }, [data, role, metric.key]);

  const nameFor = (cid: string) => {
    const p = byId.get(cid);
    return p ? displayName(p) : cid;
  };

  const { rows, series, missing } = useMemo(() => {
    const overlay = metric.overlay;
    const withData: string[] = [];
    const missing: string[] = [];
    const maps = new Map<string, Map<number, number>>();
    if (overlay) {
      for (const cid of shownPicks) {
        const m = seriesOf(cid, role, overlay);
        if (m.size) {
          withData.push(cid);
          maps.set(cid, m);
        } else missing.push(cid);
      }
    }
    const rows = base.map((r) => {
      const row: Record<string, number | null> = { ...r };
      for (const cid of withData) row[`p_${cid}`] = maps.get(cid)!.get(r.age) ?? null;
      return row;
    });
    const series = withData.map((cid) => ({
      key: `p_${cid}`,
      name: nameFor(cid),
      color: PALETTE[shownPicks.indexOf(cid) % PALETTE.length],
    }));
    return { rows, series, missing };
    // nameFor / PALETTE read stable lookups; recompute only when the inputs change
  }, [base, shownPicks, role, metric.overlay, byId, colors]);

  return (
    <>
      <PageTitle
        title="Aging curves"
        icon={<TrendingUp className="h-6 w-6" />}
        desc="How performance changes with age. Each player-season is a data point, averaged by age into a curve (dashed). Add up to five players to lay their own careers over it."
      />

      <div className="mb-3 flex flex-wrap items-center gap-3">
        <div className="flex gap-2">
          {(["batting", "bowling"] as Role[]).map((r) => (
            <button
              key={r}
              onClick={() => setRole(r)}
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
            options={options.filter((o) => !picks.includes(o.value))}
            value={null}
            onChange={(v) => v && picks.length < MAX_PLAYERS && setPicks([...picks, v])}
            placeholder={picks.length >= MAX_PLAYERS ? `Up to ${MAX_PLAYERS} players` : "Add a player…"}
            className="max-w-xs flex-1"
          />
        )}
      </div>

      {/* picked players as chips — a fixed-height row so the chart never jumps */}
      <div className="mb-3 flex min-h-[32px] flex-wrap items-center gap-2">
        {metric.overlay ? (
          picks.length ? (
            picks.map((cid, i) => (
              <span
                key={cid}
                className="inline-flex items-center gap-1.5 rounded-full border border-border bg-surface px-2.5 py-1 text-xs text-fg"
              >
                <span className="h-2 w-2 rounded-full" style={{ background: PALETTE[i % PALETTE.length] }} />
                {nameFor(cid)}
                <button
                  onClick={() => setPicks(picks.filter((c) => c !== cid))}
                  aria-label={`Remove ${nameFor(cid)}`}
                  className="text-muted hover:text-ball"
                >
                  <X className="h-3 w-3" />
                </button>
              </span>
            ))
          ) : (
            <span className="text-xs text-muted">No players added — showing the league curve.</span>
          )
        ) : (
          <span className="text-xs text-muted">
            Player overlays are available for {role === "batting" ? "strike rate" : "economy"}.
          </span>
        )}
        {missing.length > 0 && (
          <span className="text-xs text-muted">
            · No {role} trajectory for {missing.map(nameFor).join(", ")} (needs a known date of birth and 3+ seasons).
          </span>
        )}
      </div>

      {loading && !data ? (
        <Spinner label="Loading aging curves…" />
      ) : error ? (
        <ErrorBox message={error} />
      ) : !data || base.length === 0 ? (
        <Empty>No aging data for this collection (needs player dates of birth).</Empty>
      ) : (
        <Card>
          <CardHeader
            title={`${role === "batting" ? "Batting" : "Bowling"} ${metric.label.toLowerCase()} by age`}
            subtitle="Dashed = average across all qualifying player-seasons (≥60 balls); solid = the players you added"
            right={
              <InfoTip title="Coverage + caveats">
                Ages come from Wikidata dates of birth, which cover only ~a third of players (elite /
                international skew). Survivorship isn't corrected — weaker players retire earlier, so
                the late-career end is the survivors. Treat the curve as indicative, not definitive.
              </InfoTip>
            }
          />
          <div className="h-96 p-4">
            <AgingChart rows={rows} series={series} avgName={`All players (${metric.label})`} colors={colors} />
          </div>
        </Card>
      )}
    </>
  );
}
