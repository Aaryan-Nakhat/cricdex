import { TrendingUp } from "lucide-react";
import { Area, CartesianGrid, ComposedChart, Line, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { useAsync } from "@/lib/useAsync";
import { useTheme } from "@/lib/theme";
import { Badge, Card, CardHeader, InfoTip } from "@/components/ui";
import { FLAG_LABEL, getForecast, seasonsOf, signed, type ForecastData, type ForecastRole } from "@/lib/forecast";

const Z80 = 1.2816;
const TONE = { hold: "accent", improve: "willow", hold_then_decline: "gold", decline: "ball" } as const;

interface Point {
  season: number;
  median: number;
  level: [number, number];
  one: [number, number];
  p: number | null;
}

function points(data: ForecastData, r: ForecastRole): Point[] {
  const lo = r.level - Z80 * r.level_sd;
  const hi = r.level + Z80 * r.level_sd;
  return [
    { season: data.as_of_season, median: r.level, level: [lo, hi], one: [lo, hi], p: null },
    ...seasonsOf(data, r).map((s) => ({
      season: s.season,
      median: s.median,
      level: [s.lo, s.hi] as [number, number],
      one: [s.season_lo, s.season_hi] as [number, number],
      p: s.p_regular,
    })),
  ];
}

function FanTip({ active, payload, now }: { active?: boolean; payload?: { payload: Point }[]; now: number }) {
  if (!active || !payload?.length) return null;
  const d = payload[0].payload;
  return (
    <div className="rounded-lg border border-border bg-card px-3 py-2 text-xs shadow-lg">
      <div className="mb-1 font-semibold text-fg">{d.p == null ? `${d.season} · current level` : d.season}</div>
      <div className="text-fg">
        {d.p == null ? "Level" : "Median"} <span className="font-semibold">{signed(d.median)}</span>
        {d.p != null && <span className="text-muted"> (level now {signed(now)})</span>}
      </div>
      <div className="text-muted">
        Level, 80%: {signed(d.level[0])} to {signed(d.level[1])}
      </div>
      {d.p != null && (
        <>
          <div className="text-muted">
            One season, 80%: {signed(d.one[0])} to {signed(d.one[1])}
          </div>
          <div className="text-muted">Chance he's a regular: {Math.round(d.p * 100)}%</div>
        </>
      )}
    </div>
  );
}

function RoleFan({ data, role, label, color }: { data: ForecastData; role: ForecastRole; label: string; color: string }) {
  const { colors } = useTheme();
  const pts = points(data, role);
  const seasons = seasonsOf(data, role);
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm font-semibold text-fg">{label}</span>
        <Badge tone={TONE[role.flag]}>{FLAG_LABEL[role.flag]}</Badge>
        <span className="text-xs text-muted">
          current level {signed(role.level)} · career rating {signed(role.now)}
        </span>
      </div>
      {role.recent.length > 0 && (
        <div className="text-xs text-muted">
          Last seasons: {role.recent.map(([s, v, b]) => `${s} ${signed(v)} (${b} balls)`).join(" · ")}
        </div>
      )}
      <p className="text-sm text-fg">{role.text}</p>
      <div className="h-56 w-full" role="img" aria-label={`${label} forecast: ${role.text}`}>
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={pts} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
            <CartesianGrid stroke={colors.grid} vertical={false} />
            <XAxis dataKey="season" tick={{ fill: colors.muted, fontSize: 12 }} />
            <YAxis tick={{ fill: colors.muted, fontSize: 12 }} width={40} domain={["auto", "auto"]} tickFormatter={(v: number) => signed(v)} />
            <ReferenceLine y={0} stroke={colors.muted} strokeDasharray="4 4" />
            <Tooltip isAnimationActive={false} content={<FanTip now={role.level} />} cursor={{ stroke: colors.muted, strokeWidth: 1 }} />
            <Area dataKey="one" stroke="none" fill={color} fillOpacity={0.12} isAnimationActive={false} activeDot={false} />
            <Area dataKey="level" stroke="none" fill={color} fillOpacity={0.3} isAnimationActive={false} activeDot={false} />
            <Line dataKey="median" stroke={color} strokeWidth={2} dot={{ r: 4, fill: color, strokeWidth: 2, stroke: colors.card }} isAnimationActive={false} />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
      <div className="grid grid-cols-3 gap-2 text-center text-xs">
        {seasons.map((s) => (
          <div key={s.season} className="rounded-lg border border-border bg-surface px-2 py-1.5">
            <div className="text-muted">{s.season}</div>
            <div className="text-sm font-semibold text-fg">{signed(s.median)}</div>
            <div className="text-muted">regular {Math.round(s.p_regular * 100)}%</div>
          </div>
        ))}
      </div>
    </div>
  );
}

/** The player profile's Form forecast section (IPL only; renders nothing without a forecast). */
export function FormForecast({ collection, cid }: { collection: string; cid: string }) {
  const { colors } = useTheme();
  const { data } = useAsync(() => getForecast(collection), [collection]);
  const roles = data?.players[cid];
  if (!data || !roles || (!roles.batter && !roles.bowler)) return null;
  const both = !!roles.batter && !!roles.bowler;
  return (
    <Card>
      <CardHeader
        title={
          <span className="inline-flex items-center gap-1.5">
            Form forecast
            <InfoTip title="How the forecast works">
              Value = runs per 100 balls above the average ball (the rating's own unit). It starts from his{" "}
              <b>current level</b>: a model of his true level drifting from season to season (with age), updated by
              each season he plays, a big season counting more than a short one, recent seasons more than old ones.
              It then projects that level forward with the age drift and the patterns of thousands of IPL careers
              (bowlers also lean on their career rating, which the data says holds up better for them), corrected for
              the players who were dropped. The dark band is where his true level probably sits (80%); the light band
              adds one season's luck at his usual workload. "Regular" = {data.regular_balls}+ balls in that role that
              season. Method and backtest: METHODOLOGY §11.
            </InfoTip>
          </span>
        }
        subtitle={`His value over the next three seasons (${data.as_of_season + 1}–${data.as_of_season + 3}), if he plays — with the chance he's still a regular`}
        right={<TrendingUp className="h-4 w-4 text-accent" />}
      />
      <div className={both ? "grid grid-cols-1 gap-6 p-5 lg:grid-cols-2" : "p-5"}>
        {roles.batter && <RoleFan data={data} role={roles.batter} label="Batting" color={colors.accent} />}
        {roles.bowler && <RoleFan data={data} role={roles.bowler} label="Bowling" color={colors.willow} />}
      </div>
      <div className="border-t border-border px-5 py-2.5 text-xs text-muted">
        Dark band: his level, 80% range · light band: one season, 80% range · dot at {data.as_of_season}: his current level (his seasons so far, recent ones counting most).
      </div>
    </Card>
  );
}
