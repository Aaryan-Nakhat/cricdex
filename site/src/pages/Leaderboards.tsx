import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Trophy, Info, TrendingDown, Filter } from "lucide-react";
import { useStore } from "@/lib/store";
import { useAsync } from "@/lib/useAsync";
import { getLeaderboard } from "@/lib/data";
import { METRICS, METRIC_BY_SLUG } from "@/lib/metrics";
import { DataTable, type Col } from "@/components/DataTable";
import { PageTitle, Card, Spinner, ErrorBox, Empty, Badge, InfoTip } from "@/components/ui";
import { cn } from "@/lib/utils";

export function Leaderboards() {
  const { collection } = useStore();
  const navigate = useNavigate();
  const [slug, setSlug] = useState("ngi");
  const [minMatches, setMinMatches] = useState(20);
  const metric = METRIC_BY_SLUG[slug];

  const { data, loading, error } = useAsync(
    () => getLeaderboard(collection, slug),
    [collection, slug],
  );

  // Min-matches gate — keeps 1-match flukes (hi Tanush Kotian) off the top.
  const filtered = useMemo(
    () => (data ?? []).filter((r) => Number(r.matches ?? 0) >= minMatches),
    [data, minMatches],
  );

  const cols: Col<Record<string, unknown>>[] = [
    ...metric.columns.map((c) => ({
      key: c.key,
      label: c.label,
      digits: c.digits,
      primary: c.primary,
      align: (c.digits !== undefined ? "right" : "left") as "left" | "right",
    })),
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

      {/* filter bar */}
      <div className="mb-4 flex flex-wrap items-center gap-3 rounded-lg border border-border bg-surface/50 px-4 py-3">
        <div className="flex items-center gap-2 text-sm text-muted">
          <Filter className="h-4 w-4 text-accent" />
          Min matches
        </div>
        <input
          type="range"
          min={0}
          max={100}
          step={1}
          value={minMatches}
          onChange={(e) => setMinMatches(Number(e.target.value))}
          className="h-1.5 w-44 cursor-pointer accent-[#34d399]"
        />
        <input
          type="number"
          min={0}
          max={500}
          value={minMatches}
          onChange={(e) => setMinMatches(Math.max(0, Number(e.target.value)))}
          className="input w-20 py-1.5"
        />
        <span className="text-xs text-muted">
          showing <span className="font-semibold text-fg">{filtered.length}</span> players with ≥{" "}
          {minMatches} matches
          {data && <span className="text-muted/60"> (of {data.length})</span>}
        </span>
      </div>

      {loading ? (
        <Spinner label={`Loading ${metric.name}…`} />
      ) : error ? (
        <ErrorBox message={error} />
      ) : !data || data.length === 0 ? (
        <Empty>No data for this metric in {collection}.</Empty>
      ) : filtered.length === 0 ? (
        <Empty>No players clear {minMatches} matches — lower the filter.</Empty>
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
