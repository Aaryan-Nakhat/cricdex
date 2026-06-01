import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Trophy, Info, TrendingDown } from "lucide-react";
import { useStore } from "@/lib/store";
import { useAsync } from "@/lib/useAsync";
import { getLeaderboard } from "@/lib/data";
import { METRICS, METRIC_BY_SLUG } from "@/lib/metrics";
import { DataTable, type Col } from "@/components/DataTable";
import { PageTitle, Card, Spinner, ErrorBox, Empty, Badge } from "@/components/ui";
import { cn } from "@/lib/utils";

export function Leaderboards() {
  const { collection } = useStore();
  const navigate = useNavigate();
  const [slug, setSlug] = useState("ngi");
  const metric = METRIC_BY_SLUG[slug];

  const { data, loading, error } = useAsync(
    () => getLeaderboard(collection, slug),
    [collection, slug],
  );

  const cols: Col<Record<string, unknown>>[] = metric.columns.map((c) => ({
    key: c.key,
    label: c.label,
    digits: c.digits,
    primary: c.primary,
    align: c.digits !== undefined ? "right" : "left",
  }));

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

      {/* explainer */}
      <Card className="mb-5 px-5 py-4">
        <div className="flex items-start gap-3">
          <Info className="mt-0.5 h-4 w-4 shrink-0 text-accent" />
          <div>
            <div className="flex items-center gap-2">
              <h3 className="text-sm font-semibold text-fg">{metric.name}</h3>
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

      {loading ? (
        <Spinner label={`Loading ${metric.name}…`} />
      ) : error ? (
        <ErrorBox message={error} />
      ) : !data || data.length === 0 ? (
        <Empty>No data for this metric in {collection}.</Empty>
      ) : (
        <DataTable
          rows={data}
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
