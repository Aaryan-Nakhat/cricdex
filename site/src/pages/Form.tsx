import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { TrendingUp, TrendingDown, ArrowUpRight, ArrowDownRight } from "lucide-react";
import { useStore } from "@/lib/store";
import { useAsync } from "@/lib/useAsync";
import { getLeaderboard, type LeaderboardRow } from "@/lib/data";
import { METRICS, METRIC_BY_SLUG } from "@/lib/metrics";
import { DataTable, type Col } from "@/components/DataTable";
import { FilterBar } from "@/components/FilterBar";
import { applyFilters, countriesIn, EMPTY_FILTERS, type Filters } from "@/lib/filters";
import { PageTitle, Card, Spinner, ErrorBox, Empty, Badge, InfoTip, StatTile } from "@/components/ui";
import { cn, fmt } from "@/lib/utils";

type Row = Record<string, unknown>;

const WINDOW_LABEL: Record<string, string> = {
  last1y: "last 12 months",
  last3y: "last 3 years",
};

export function Form() {
  const { collection, meta } = useStore();
  const navigate = useNavigate();
  const [slug, setSlug] = useState("ngi");
  const [filters, setFilters] = useState<Filters>(EMPTY_FILTERS);
  const metric = METRIC_BY_SLUG[slug];
  const valueKey = metric.columns.find((c) => c.primary)?.key ?? metric.columns[1]?.key;
  const nameKey = metric.nameCol;

  // Recent-window picker — whichever recomputed windows this collection cooked.
  const windows: string[] = (meta?.windows ?? []).filter((w) => w === "last1y" || w === "last3y");
  const [win, setWin] = useState<string | null>(null);
  const recentWin = win && windows.includes(win) ? win : (windows[0] ?? null);

  const career = useAsync(() => getLeaderboard(collection, slug, "all"), [collection, slug]);
  const recent = useAsync(
    () => (recentWin ? getLeaderboard(collection, slug, recentWin) : Promise.resolve([])),
    [collection, slug, recentWin],
  );

  const countryOpts = useMemo(() => countriesIn((recent.data ?? []) as Row[]), [recent.data]);

  const rows = useMemo(() => {
    if (!career.data || !recent.data) return [];
    const careerBy = new Map<string, LeaderboardRow>();
    for (const r of career.data) {
      const k = r[nameKey];
      if (typeof k === "string") careerBy.set(k, r);
    }
    const filteredRecent = applyFilters(recent.data as Row[], filters);
    const out: Row[] = [];
    for (const rr of filteredRecent) {
      const name = rr[nameKey];
      if (typeof name !== "string") continue;
      const cr = careerBy.get(name);
      if (!cr) continue;
      const careerVal = Number(cr[valueKey]);
      const recentVal = Number(rr[valueKey]);
      if (!Number.isFinite(careerVal) || !Number.isFinite(recentVal)) continue;
      const raw = recentVal - careerVal;
      const mv = metric.higherIsBetter ? raw : -raw; // +ve = improving form
      out.push({ name, career: careerVal, recent: recentVal, mv });
    }
    return out;
  }, [career.data, recent.data, nameKey, valueKey, metric.higherIsBetter, filters]);

  const top = useMemo(() => [...rows].sort((a, b) => Number(b.mv) - Number(a.mv)), [rows]);
  const riser = top[0];
  const faller = top[top.length - 1];

  const cols: Col<Row>[] = [
    { key: "name", label: "Player", primary: false },
    { key: "career", label: "Career", align: "right", digits: 2 },
    { key: "recent", label: WINDOW_LABEL[recentWin ?? ""] ?? "Recent", align: "right", digits: 2 },
    {
      key: "mv",
      label: "Form Δ",
      align: "right",
      digits: 2,
      primary: true,
      render: (r: Row) => {
        const v = Number(r.mv);
        const up = v >= 0;
        return (
          <span className={cn("inline-flex items-center gap-1 stat-num", up ? "text-willow" : "text-ball")}>
            {up ? <ArrowUpRight className="h-3.5 w-3.5" /> : <ArrowDownRight className="h-3.5 w-3.5" />}
            {up ? "+" : ""}
            {fmt(v, 2)}
          </span>
        );
      },
    },
  ];

  const loading = career.loading || recent.loading;
  const error = career.error || recent.error;

  return (
    <>
      <PageTitle
        title="Form board"
        icon={<TrendingUp className="h-6 w-6" />}
        desc="Who's trending up and who's fading — each metric recomputed over the recent window and compared against the player's career baseline. Positive Δ means improving form (already direction-corrected for 'lower is better' metrics)."
      />

      <div className="mb-4 flex flex-wrap gap-2">
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

      {windows.length > 1 && (
        <div className="mb-4 flex flex-wrap items-center gap-2">
          <span className="text-sm font-medium text-muted">Recent window</span>
          {windows.map((w) => (
            <button
              key={w}
              onClick={() => setWin(w)}
              className={cn(
                "rounded-lg border px-3 py-1.5 text-sm font-medium transition-all",
                w === recentWin
                  ? "border-accent/40 bg-accent/10 text-accent-glow"
                  : "border-border bg-surface text-muted hover:text-fg",
              )}
            >
              {WINDOW_LABEL[w] ?? w}
            </button>
          ))}
        </div>
      )}

      <FilterBar
        filters={filters}
        onChange={setFilters}
        show={["minMatches", "activity", "role", "bowling", "position", "country"]}
        countryOpts={countryOpts}
        count={rows.length}
      />

      {!recentWin ? (
        <Empty>This collection has no recomputed recent window — form needs a last-1y/3y window.</Empty>
      ) : loading ? (
        <Spinner label="Loading form…" />
      ) : error ? (
        <ErrorBox message={error} />
      ) : rows.length === 0 ? (
        <Empty>No players match — loosen the filters, or this metric has no recent board.</Empty>
      ) : (
        <div className="space-y-5 animate-fade-up">
          <Card className="px-5 py-4">
            <div className="flex items-start gap-3">
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <h3 className="text-sm font-semibold text-fg">
                    {metric.name} — {WINDOW_LABEL[recentWin]} vs career
                  </h3>
                  <InfoTip title={`How ${metric.name} is calculated`}>{metric.how}</InfoTip>
                  {!metric.higherIsBetter && <Badge tone="muted">lower is better → sign-flipped</Badge>}
                </div>
                <p className="mt-1 text-sm leading-relaxed text-muted">{metric.what}</p>
              </div>
            </div>
          </Card>

          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            {riser && (
              <StatTile
                label="Biggest riser"
                value={String(riser.name)}
                hint={`+${fmt(Number(riser.mv), 2)} form Δ`}
              />
            )}
            {faller && (
              <StatTile
                label="Biggest faller"
                value={String(faller.name)}
                hint={`${fmt(Number(faller.mv), 2)} form Δ`}
              />
            )}
          </div>

          <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
            <div>
              <div className="mb-2 flex items-center gap-2 text-sm font-semibold text-willow">
                <TrendingUp className="h-4 w-4" /> Heating up
              </div>
              <DataTable
                rows={top.slice(0, 25)}
                cols={cols}
                initialSort={{ key: "mv", dir: "desc" }}
                onRowClick={(r) => navigate(`/player?name=${encodeURIComponent(String(r.name))}`)}
              />
            </div>
            <div>
              <div className="mb-2 flex items-center gap-2 text-sm font-semibold text-ball">
                <TrendingDown className="h-4 w-4" /> Cooling down
              </div>
              <DataTable
                rows={[...top].reverse().slice(0, 25)}
                cols={cols}
                initialSort={{ key: "mv", dir: "asc" }}
                onRowClick={(r) => navigate(`/player?name=${encodeURIComponent(String(r.name))}`)}
              />
            </div>
          </div>
        </div>
      )}
    </>
  );
}
