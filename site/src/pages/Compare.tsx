import { Fragment, useEffect, useMemo } from "react";
import { GitCompareArrows, Plus, X } from "lucide-react";
import { useStore } from "@/lib/store";
import { usePlayers } from "@/lib/usePlayers";
import { useAsync } from "@/lib/useAsync";
import { getProfile, type Profile } from "@/lib/data";
import { BAT_STATS, BOWL_STATS, standardStats, type StandardStats } from "@/lib/standard";
import { METRIC_BY_SLUG, fmtMetric } from "@/lib/metrics";
import { MetricInfo } from "@/components/MetricInfo";
import { Combobox } from "@/components/Combobox";
import { PageTitle, Card, CardHeader, Spinner, Empty, InfoTip, ErrorBox } from "@/components/ui";
import { useTheme } from "@/lib/theme";
import { useClearOnChange, useUrlParams } from "@/lib/useUrlState";
import { cn, collectionLabel, fmt } from "@/lib/utils";

function num(v: unknown): number | null {
  if (v === null || v === undefined || v === "") return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}

interface Row {
  label: string;
  hint?: string;
  get: (p: Profile, st: StandardStats) => number | string | null;
  digits: number;
  better: "high" | "low" | "none";
  group: string;
  /** Format a number for display (default: fmt with `digits`). */
  show?: (v: number) => string;
  /** An explainer next to the row label. */
  info?: React.ReactNode;
}

const bb = (p: Profile) => (p.bayes?.bayes_batter ?? null) as Record<string, unknown> | null;
const bw = (p: Profile) => (p.bayes?.bayes_bowler ?? null) as Record<string, unknown> | null;
const met = (p: Profile, slug: string, key: string) =>
  num(((p.metrics ?? {}) as Record<string, Record<string, unknown> | null>)[slug]?.[key]);
const NGI_PCT = METRIC_BY_SLUG.ngi.columns.find((c) => c.key === "ngi_per_match")!;

const VALUE_INFO = (
  <InfoTip title="Batting and bowling value" label="What batting and bowling value mean">
    One number per role from the skill model, in <b>runs per 100 balls</b> above the league's average ball:{" "}
    <b>0 = average</b>, +10 = ten runs better every 100 balls; the best IPL regulars sit around +20 to +25.{" "}
    <b>Batting value</b> is how much faster he scores, plus the runs his team doesn't lose because he stays in — a
    wicket priced at what it costs where he bats (about 14 runs early in the powerplay, 2–3 in the last overs), so a
    finisher is valued mainly on his scoring rate. <b>Bowling value</b> is the runs he saves plus his extra wickets at
    the same price. Each is judged against the opponents he actually faced. Higher is better for both.
  </InfoTip>
);

const pctShow = (digits: number, suffix?: string) =>
  suffix ? (v: number) => `${fmt(v, digits)}${suffix}` : undefined;

const CONTEXT: [string, string, string, number][] = [
  ["pressure_runs", "pressure_sr_per_100_balls", "Pressure SR", 1],
  ["counter_attack", "counter_attack_sr", "Counter-attack SR", 1],
  ["dot_ball_recovery", "runs_per_6_after_dot", "Dot-ball recovery", 2],
  ["boundary_dependency", "bdr_pct", "Boundary dependency %", 1],
  ["crease_longevity", "longevity_index", "Crease longevity", 2],
  ["slow_start_cost", "slow_start_cost", "Slow-start cost", 1],
  ["wicket_quality", "wicket_quality", "Wicket quality", 3],
  ["dot_avoidance", "dots_avoided_per100", "Dots avoided / 100", 1],
  ["pace_spin", "spin_edge", "Spin edge / 100", 1],
  ["finisher", "above_per100", "Finisher / 100", 1],
  ["hand_split", "left_edge", "Left edge / 100", 1],
];

const ROWS: Row[] = [
  { group: "Overall", label: "Batting value", hint: "runs per 100 balls vs average", digits: 1, better: "high", info: VALUE_INFO, get: (p) => num(bb(p)?.value) },
  {
    group: "Overall",
    label: "Bowling value",
    hint: "runs saved per 100 balls",
    digits: 1,
    better: "high",
    info: VALUE_INFO,
    get: (p) => ((num(bw(p)?.balls) ?? 0) > 60 ? num(bw(p)?.value) : null),
  },
  {
    group: "Overall",
    label: "Win chance added / match",
    hint: "+5% = five points of win chance a game",
    digits: 1,
    better: "high",
    show: (v) => fmtMetric(v, NGI_PCT),
    info: <MetricInfo m={METRIC_BY_SLUG.ngi} />,
    get: (p) => met(p, "ngi", "ngi_per_match"),
  },
  {
    group: "Overall",
    label: "Wins added (career)",
    hint: "a career total — grows with matches",
    digits: 1,
    better: "high",
    get: (p) => met(p, "ngi", "ngi_total"),
  },
  { group: "Batting", label: "Runs", digits: 0, better: "high", get: (_p, st) => st.runs },
  { group: "Batting", label: "Innings", digits: 0, better: "none", get: (_p, st) => st.innings },
  ...BAT_STATS.map(
    (r): Row => ({
      group: "Batting",
      label: r.label,
      hint: r.hint,
      digits: r.digits,
      better: r.better,
      show: pctShow(r.digits, r.suffix),
      get: (_p, st) => st[r.key],
    }),
  ),
  { group: "Bowling", label: "Wickets", digits: 0, better: "high", get: (_p, st) => ((st.ballsBowled ?? 0) > 0 ? st.wickets : null) },
  ...BOWL_STATS.map(
    (r): Row => ({
      group: "Bowling",
      label: r.label,
      hint: r.hint,
      digits: r.digits,
      better: r.better,
      show: pctShow(r.digits, r.suffix),
      get: (_p, st) => ((st.ballsBowled ?? 0) >= 60 ? st[r.key] : null),
    }),
  ),
  ...CONTEXT.map(([slug, key, label, digits]): Row => {
    const m = METRIC_BY_SLUG[slug];
    return {
      group: "Context metrics",
      label,
      hint: m.direction === "descriptive" ? "a style — no better side" : undefined,
      digits,
      better: m.direction === "higher" ? "high" : m.direction === "lower" ? "low" : "none",
      info: <MetricInfo m={m} />,
      get: (p) => met(p, slug, key),
    };
  }),
];

const GROUPS = ["Overall", "Batting", "Bowling", "Context metrics"];

// The four skills, in plain words. Each is centred on the average player in the league (0).
const AXES: { label: string; side: "batting" | "bowling"; get: (p: Profile) => number | null; none: string }[] = [
  { label: "Scoring speed", side: "batting", get: (p) => num(bb(p)?.skill), none: "no batting rating" },
  { label: "Staying in (hard to dismiss)", side: "batting", get: (p) => num(bb(p)?.survival_skill), none: "no batting rating" },
  { label: "Economy (keeping runs down)", side: "bowling", get: (p) => num(bw(p)?.skill), none: "doesn't bowl enough to rate" },
  { label: "Wicket-taking", side: "bowling", get: (p) => num(bw(p)?.strike_skill), none: "doesn't bowl enough to rate" },
];

/** One skill as bars growing from the "average player" line: right = better than average, left = worse. */
function SkillBars({
  axis,
  players,
  colors,
  names,
}: {
  axis: (typeof AXES)[number];
  players: Profile[];
  colors: string[];
  names: string[];
}) {
  const vals = players.map((p) =>
    axis.side !== "bowling" || (num(bw(p)?.balls) ?? 0) > 60 ? axis.get(p) : null,
  );
  const finite = vals.filter((v): v is number => v !== null);
  const span = Math.max(0.3, ...finite.map((v) => Math.abs(v))) * 1.1;
  return (
    <div>
      <div className="mb-1.5 text-sm font-medium text-fg">{axis.label}</div>
      <div className="space-y-1.5">
        {players.map((_p, i) => {
          const v = vals[i];
          const w = v === null ? 0 : (Math.abs(v) / span) * 50;
          return (
            <div
              key={i}
              className="grid grid-cols-[minmax(0,6.5rem)_1fr_3.5rem] items-center gap-2 text-xs sm:grid-cols-[minmax(0,9rem)_1fr_4rem]"
            >
              <span className="truncate font-medium" style={{ color: colors[i] }} title={names[i]}>
                {names[i]}
              </span>
              <div className="relative h-4 rounded bg-border/30">
                <div className="absolute -top-0.5 left-1/2 h-5 w-0.5 -translate-x-1/2 rounded bg-fg/70" aria-hidden />
                {v !== null && (
                  <div
                    className="absolute top-0.5 h-3 rounded-sm"
                    style={{ background: colors[i], left: v >= 0 ? "50%" : `${50 - w}%`, width: `${Math.max(0.8, w)}%` }}
                  />
                )}
              </div>
              <span className={cn("stat-num text-right", v === null ? "text-faint" : v >= 0 ? "text-accent-glow" : "text-ball")}>
                {v === null ? "—" : `${v >= 0 ? "+" : "−"}${Math.abs(v).toFixed(2)}`}
              </span>
            </div>
          );
        })}
      </div>
      <div className="mt-1 flex justify-between pl-[7rem] pr-[4rem] text-[10px] uppercase tracking-wider text-faint sm:pl-[9.5rem] sm:pr-[4.5rem]">
        <span>worse</span>
        <span className="font-semibold text-muted">average</span>
        <span>better</span>
      </div>
      {vals.some((v) => v === null) && <div className="mt-1 text-[11px] text-faint">— = {axis.none}</div>}
    </div>
  );
}

export function Compare() {
  const { collection } = useStore();
  const { options, players, byId } = usePlayers(collection);
  const { colors } = useTheme();
  const SERIES_COLORS = [colors.accent, colors.gold, colors.sky, colors.ball];

  // The picks live in the URL as `?cids=a,b` (an empty slot is an empty entry),
  // so a link reproduces the comparison. Ids not in this league are dropped.
  const { params, update } = useUrlParams();
  const cidsParam = params.get("cids") ?? "";
  const ready = players.length > 0;
  const cids = useMemo(() => {
    const list = cidsParam ? cidsParam.split(",").slice(0, 4) : [];
    const out = list.map((id) => (id && (!ready || byId.has(id)) ? id : null));
    while (out.length < 2) out.push(null);
    return out;
  }, [cidsParam, ready, byId]);
  const encode = (c: (string | null)[]) =>
    c.length <= 2 && !c.some(Boolean) ? null : c.map((x) => x ?? "").join(",");
  const setCids = (next: (string | null)[]) => update({ cids: encode(next) }, { replace: false });

  // tidy the URL once the league's players are known (unknown ids, >4 slots)
  useEffect(() => {
    if (ready && (encode(cids) ?? "") !== cidsParam) update({ cids: encode(cids) });
  }, [ready, cids, cidsParam, update]);

  // players are per league: a switch clears the picks instead of asking for files that don't exist
  useClearOnChange(collection, ["cids"]);

  const picked = cids.filter(Boolean) as string[];
  const profiles = useAsync(async () => {
    // one missing profile shouldn't sink the others
    const got = await Promise.allSettled(picked.map((id) => getProfile(collection, id)));
    const ok = got.flatMap((g) => (g.status === "fulfilled" && g.value ? [g.value] : []));
    const failed = got.filter((g) => g.status === "rejected").length;
    return { ok, failed };
  }, [collection, picked.join(",")]);

  const loaded = (profiles.data?.ok ?? []) as Profile[];
  const stats = loaded.map((p) => standardStats(p));
  const names = loaded.map((p) => {
    const row = byId.get(p.cricsheet_id);
    return (p.identity?.display_name ?? row?.display_name ?? "").trim() || p.name;
  });
  const lg = collectionLabel(collection);

  function setAt(i: number, v: string | null) {
    setCids(cids.map((x, j) => (j === i ? v : x)));
  }

  return (
    <>
      <PageTitle
        title="Compare players"
        icon={<GitCompareArrows className="h-6 w-6" />}
        desc="Put two to four players side by side: their skills against an average player, the standard scorecard numbers, and the context metrics. The best value in each row is highlighted."
      />

      <div className="mb-6 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {cids.map((cid, i) => (
          <div key={i} className="relative">
            <Combobox options={options} value={cid} onChange={(v) => setAt(i, v)} placeholder={`Player ${i + 1}`} />
            {cids.length > 2 && (
              <button
                className="absolute -right-1 -top-1 rounded-full bg-card p-0.5 text-muted hover:text-ball"
                onClick={() => setCids(cids.filter((_, j) => j !== i))}
                aria-label={`Remove player ${i + 1}`}
              >
                <X className="h-3.5 w-3.5" />
              </button>
            )}
          </div>
        ))}
        {cids.length < 4 && (
          <button className="btn h-[42px]" onClick={() => setCids([...cids, null])}>
            <Plus className="h-4 w-4" /> Add player
          </button>
        )}
      </div>

      {picked.length < 2 ? (
        <Empty>Pick at least two players to compare.</Empty>
      ) : profiles.loading && !profiles.data ? (
        <Spinner label="Loading players…" />
      ) : profiles.error ? (
        <ErrorBox message={profiles.error} />
      ) : loaded.length < 2 ? (
        <Empty>
          {profiles.data?.failed
            ? "One of these players has no profile in this league — pick someone else."
            : "Pick at least two players to compare."}
        </Empty>
      ) : (
        <div className="space-y-5 animate-fade-up">
          {/* skills as bars from the average-player line */}
          <Card>
            <CardHeader
              title={
                <span className="flex items-center gap-2">
                  Skills vs an average {lg} player
                  <InfoTip title="How to read this">
                    Each block is one skill from the rating model. The dark centre line is an{" "}
                    <b>average {lg} player</b>. A bar to the <b>right</b> means better than average, to the{" "}
                    <b>left</b> worse; the longer the bar, the bigger the gap. The numbers are on the model's own
                    scale (0 = average), and every skill is judged against the opponents the player actually faced. A
                    pure batter shows “—” on the bowling skills: he doesn't bowl enough to rate.
                  </InfoTip>
                </span>
              }
              subtitle="Centre line = average player · bar to the right = better · to the left = worse"
            />
            <div className="grid grid-cols-1 gap-6 p-5 md:grid-cols-2">
              {AXES.map((ax) => (
                <SkillBars key={ax.label} axis={ax} players={loaded} colors={SERIES_COLORS} names={names} />
              ))}
            </div>
          </Card>

          {/* comparison table */}
          <Card className="overflow-hidden">
            <CardHeader
              title="Side by side"
              subtitle="The best value in each row is highlighted. “—” = not available for that player or not in this export yet."
            />
            <div className="overflow-auto">
              <table className="w-full border-collapse">
                <thead>
                  <tr>
                    <th className="th">Stat</th>
                    {loaded.map((_p, i) => (
                      <th key={i} className="th text-right" style={{ color: SERIES_COLORS[i] }}>
                        {names[i]}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {GROUPS.map((g) => (
                    <Fragment key={g}>
                      <tr>
                        <td
                          colSpan={loaded.length + 1}
                          className="border-t border-border bg-surface/40 px-3 py-1.5 text-[11px] font-semibold uppercase tracking-wider text-muted"
                        >
                          {g}
                        </td>
                      </tr>
                      {ROWS.filter((r) => r.group === g).map((row) => {
                        const vals = loaded.map((p, i) => row.get(p, stats[i]));
                        if (vals.every((v) => v === null)) return null;
                        const finite = vals.filter((v): v is number => typeof v === "number");
                        const best =
                          finite.length > 1 && row.better !== "none"
                            ? row.better === "high"
                              ? Math.max(...finite)
                              : Math.min(...finite)
                            : null;
                        return (
                          <tr key={row.label} className="hover:bg-surface/40">
                            <td className="td">
                              <span className="inline-flex items-center gap-1.5">
                                <span className="text-fg">{row.label}</span>
                                {row.info}
                              </span>
                              {row.hint && <div className="text-[11px] text-faint">{row.hint}</div>}
                            </td>
                            {vals.map((v, i) => (
                              <td
                                key={i}
                                className={cn(
                                  "td stat-num text-right",
                                  typeof v === "number" && best !== null && v === best ? "font-bold text-accent-glow" : "text-fg",
                                )}
                              >
                                {typeof v === "number" ? (row.show ? row.show(v) : fmt(v, row.digits)) : (v ?? "—")}
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
