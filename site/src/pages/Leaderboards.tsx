import { useMemo } from "react";
import { useNavigate } from "react-router-dom";
import { Trophy, Info, TrendingDown } from "lucide-react";
import { useStore } from "@/lib/store";
import { useAsync } from "@/lib/useAsync";
import { getLeaderboard } from "@/lib/data";
import { METRIC_BY_SLUG } from "@/lib/metrics";
import { DataTable, type Col } from "@/components/DataTable";
import { FilterBar } from "@/components/FilterBar";
import { applyFilters, countriesIn, DEFAULT_FILTERS } from "@/lib/filters";
import { hasKey, useUrlFilters, useUrlState } from "@/lib/useUrlState";
import { PageTitle, Card, Spinner, ErrorBox, Empty, Badge, InfoTip, Segmented } from "@/components/ui";
import { cn, collectionLabel } from "@/lib/utils";

// Metric switcher, grouped so twelve boards scan as three short rows.
const METRIC_GROUPS: { label: string; slugs: string[] }[] = [
  { label: "All-round", slugs: ["ngi"] },
  {
    label: "Batting",
    slugs: [
      "pressure_runs",
      "intent_curve",
      "dot_ball_recovery",
      "counter_attack",
      "boundary_dependency",
      "crease_longevity",
      "slow_start_cost",
    ],
  },
  { label: "Bowling", slugs: ["pressure_conversion", "wicket_quality"] },
  { label: "Fielding", slugs: ["keeping", "fielding"] },
];

const PERIOD_LABEL: Record<string, string> = {
  all: "All-time",
  last3y: "Last 3 yrs",
  last1y: "Last 1 yr",
};

// Intent-curve x-axis: SR per ball-faced bucket, innings order.
const INTENT_BUCKET_LABELS = ["0–5", "6–10", "11–20", "21–30", "31–50", "51+"];

// Inline mini bar-chart of a batter's 6-point intent curve, scaled to their
// own peak so the shape (ramp / fade) reads at a glance. Missing buckets
// (not enough balls) render as a faint stub. Hover for the per-bucket SRs.
function Sparkline({ values }: { values: (number | null)[] }) {
  if (!values || values.every((v) => v == null)) return <span className="text-muted">—</span>;
  const max = Math.max(...values.filter((v): v is number => v != null), 1);
  const title = values
    .map((v, i) => `${INTENT_BUCKET_LABELS[i]}: ${v == null ? "—" : Math.round(v)}`)
    .join("   ");
  return (
    <span className="flex h-7 items-end gap-[3px]" title={title}>
      {values.map((v, i) => (
        <span
          key={i}
          className={cn(
            "w-[7px] rounded-sm",
            v == null ? "bg-border/40" : "bg-gradient-to-t from-accent-dim to-accent-glow",
          )}
          style={{ height: v == null ? "12%" : `${Math.max(14, (v / max) * 100)}%` }}
        />
      ))}
    </span>
  );
}

export function Leaderboards() {
  const { collection, meta } = useStore();
  const navigate = useNavigate();
  // metric, period and non-default filters live in the URL (shareable links)
  const [slug, setSlug] = useUrlState<string>("metric", "ngi", {
    valid: (v) => hasKey(METRIC_BY_SLUG, v),
    replace: false,
  });
  // recomputed periods: All-time + whatever windows this collection cooked
  const periods = useMemo(() => ["all", ...(meta?.windows ?? [])], [meta]);
  const [activePeriod, setPeriod] = useUrlState<string>("period", "all", {
    valid: periods,
    ready: !!meta,
    replace: false,
  });
  const [filters, setFilters] = useUrlFilters(DEFAULT_FILTERS);
  const metric = METRIC_BY_SLUG[slug];

  const { data, loading, error } = useAsync(
    () => getLeaderboard(collection, slug, activePeriod),
    [collection, slug, activePeriod],
  );

  const countryOpts = useMemo(() => countriesIn(data ?? []), [data]);
  // Min-matches + role/bowling/position/country gates. Min-matches keeps
  // 1-match flukes (hi Tanush Kotian) off the top.
  const filtered = useMemo(() => applyFilters(data ?? [], filters), [data, filters]);

  const cols: Col<Record<string, unknown>>[] = [
    ...metric.columns.map((c) =>
      c.key === "curve"
        ? {
            key: c.key,
            label: c.label,
            align: "left" as const,
            sortable: false,
            render: (row: Record<string, unknown>) => (
              <Sparkline values={(row.curve as (number | null)[]) ?? []} />
            ),
          }
        : {
            key: c.key,
            label: c.label,
            digits: c.digits,
            primary: c.primary,
            align: (c.digits !== undefined ? "right" : "left") as "left" | "right",
          },
    ),
    // a matches column, unless the metric already shows one (NGI does)
    ...(metric.columns.some((c) => c.key === "matches")
      ? []
      : [{ key: "matches", label: "Mts", digits: 0, align: "right" as const }]),
  ];

  return (
    <>
      <PageTitle
        title="Leaderboards"
        icon={<Trophy className="h-6 w-6" />}
        desc="Twelve boards built from ball-by-ball data — ten context metrics that batting average and economy can't see, plus wicketkeeping and fielding. Pick one, sort any column, open a player for their full dossier."
      />

      {/* metric switcher, grouped */}
      <div role="radiogroup" aria-label="Metric" className="card mb-5 grid gap-3 p-3 sm:grid-cols-[auto_1fr] sm:items-center">
        {METRIC_GROUPS.map((g) => (
          <div key={g.label} className="contents">
            <div className="eyebrow px-1 sm:pt-0.5">{g.label}</div>
            <div className="flex flex-wrap gap-1.5">
              {g.slugs
                .filter((sl) => METRIC_BY_SLUG[sl])
                .map((sl) => (
                  <button
                    key={sl}
                    role="radio"
                    aria-checked={sl === slug}
                    onClick={() => setSlug(sl)}
                    className={cn(
                      "rounded-lg border px-3 py-1.5 text-sm font-medium transition-all",
                      sl === slug
                        ? "border-accent/40 bg-accent/10 text-accent-glow shadow-glow"
                        : "border-border bg-surface/70 text-muted hover:border-accent/30 hover:text-fg",
                    )}
                  >
                    {METRIC_BY_SLUG[sl].name}
                  </button>
                ))}
            </div>
          </div>
        ))}
      </div>

      {/* explainer + how-it's-calculated */}
      <Card className="mb-4 px-5 py-4">
        <div className="flex items-start gap-3">
          <Info className="mt-0.5 h-4 w-4 shrink-0 text-accent" />
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h3 className="text-sm font-semibold text-fg">{metric.name}</h3>
              <InfoTip title={`How ${metric.name} is calculated`}>{metric.how}</InfoTip>
              {!metric.higherIsBetter && (
                <Badge tone="ball">
                  <TrendingDown className="h-3 w-3" /> lower is better
                </Badge>
              )}
            </div>
            <p className="mt-1 text-sm leading-relaxed text-muted">{metric.what}</p>
          </div>
        </div>
      </Card>

      {/* period selector — recomputed metric windows, not a row filter */}
      {periods.length > 1 && (
        <div className="mb-4 flex flex-wrap items-center gap-2">
          <span className="text-sm font-medium text-muted">Period</span>
          <InfoTip title="Recomputed time windows">
            These re-run the metric over only that window of matches — the numbers actually change,
            they're not just a row filter. Windows are relative to the latest match in this
            collection.
          </InfoTip>
          <Segmented
            label="Period"
            value={activePeriod}
            onChange={setPeriod}
            options={periods.map((p) => ({ value: p, label: PERIOD_LABEL[p] ?? p }))}
          />
        </div>
      )}

      {/* filter bar */}
      <FilterBar
        filters={filters}
        onChange={setFilters}
        defaults={DEFAULT_FILTERS}
        show={["minMatches", "activity", "role", "bowling", "position", "country"]}
        countryOpts={countryOpts}
        count={filtered.length}
        total={data?.length}
      />

      {loading ? (
        <Spinner label={`Loading ${metric.name}…`} />
      ) : error ? (
        <ErrorBox message={error} />
      ) : !data || data.length === 0 ? (
        <Empty>No {metric.name} board for {collectionLabel(collection)} yet.</Empty>
      ) : filtered.length === 0 ? (
        <Empty>No players match these filters — loosen them.</Empty>
      ) : (
        <DataTable
          key={`${slug}-${activePeriod}`}
          rows={filtered}
          cols={cols}
          higherIsBetter={metric.higherIsBetter}
          rowLabel={(row) => `Open ${String(row[metric.nameCol])}'s profile`}
          onRowClick={(row) => {
            const name = row[metric.nameCol];
            if (typeof name === "string")
              navigate(`/player?name=${encodeURIComponent(name)}`);
          }}
        />
      )}
    </>
  );
}
