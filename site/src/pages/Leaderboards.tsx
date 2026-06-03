import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Trophy, Info, TrendingDown } from "lucide-react";
import { useStore } from "@/lib/store";
import { useAsync } from "@/lib/useAsync";
import { getLeaderboard } from "@/lib/data";
import { METRICS, METRIC_BY_SLUG } from "@/lib/metrics";
import { DataTable, type Col } from "@/components/DataTable";
import { FilterBar } from "@/components/FilterBar";
import { applyFilters, countriesIn, EMPTY_FILTERS, type Filters } from "@/lib/filters";
import { PageTitle, Card, Spinner, ErrorBox, Empty, Badge, InfoTip } from "@/components/ui";
import { cn } from "@/lib/utils";

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
  const [slug, setSlug] = useState("ngi");
  const [period, setPeriod] = useState("all");
  const [filters, setFilters] = useState<Filters>({
    ...EMPTY_FILTERS,
    minMatches: 20,
    activity: "active",
  });
  const metric = METRIC_BY_SLUG[slug];

  // recomputed periods: All-time + whatever windows this collection cooked
  const periods = useMemo(() => ["all", ...(meta?.windows ?? [])], [meta]);
  const activePeriod = periods.includes(period) ? period : "all";

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
    { key: "matches", label: "Mts", digits: 0, align: "right" as const },
  ];

  return (
    <>
      <PageTitle
        title="Leaderboards"
        icon={<Trophy className="h-6 w-6" />}
        desc="Ten metrics built from ball-by-ball data — each isolates a skill that batting average and economy can't see. Pick one, sort any column, click a player for their full dossier."
      />

      {/* metric switcher */}
      <div className="mb-5 flex flex-wrap gap-2">
        {METRICS.map((m) => (
          <button
            key={m.slug}
            onClick={() => setSlug(m.slug)}
            className={cn(
              "rounded-lg border px-3 py-1.5 text-sm font-medium transition-all",
              m.slug === slug
                ? "border-accent/40 bg-accent/10 text-accent-glow shadow-glow"
                : "border-border bg-surface text-muted hover:border-accent/30 hover:text-fg",
            )}
          >
            {m.name}
          </button>
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
          {periods.map((p) => (
            <button
              key={p}
              onClick={() => setPeriod(p)}
              className={cn(
                "rounded-lg border px-3 py-1.5 text-sm font-medium transition-all",
                p === activePeriod
                  ? "border-accent/40 bg-accent/10 text-accent-glow"
                  : "border-border bg-surface text-muted hover:text-fg",
              )}
            >
              {PERIOD_LABEL[p] ?? p}
            </button>
          ))}
        </div>
      )}

      {/* filter bar */}
      <FilterBar
        filters={filters}
        onChange={setFilters}
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
        <Empty>No data for this metric in {collection}.</Empty>
      ) : filtered.length === 0 ? (
        <Empty>No players match these filters — loosen them.</Empty>
      ) : (
        <DataTable
          rows={filtered}
          cols={cols}
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
