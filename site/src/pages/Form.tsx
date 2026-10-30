import { useMemo } from "react";
import { useNavigate } from "react-router-dom";
import { TrendingUp, TrendingDown, ArrowUpRight, ArrowDownRight } from "lucide-react";
import { useStore } from "@/lib/store";
import { useAsync } from "@/lib/useAsync";
import { getLeaderboard, type LeaderboardRow } from "@/lib/data";
import { METRICS, METRIC_BY_SLUG, fmtMetric, primaryCol } from "@/lib/metrics";
import { usePlayers } from "@/lib/usePlayers";
import { MetricInfo } from "@/components/MetricInfo";
import { DataTable, type Col } from "@/components/DataTable";
import { FilterBar } from "@/components/FilterBar";
import { applyFilters, smartFilters, defaultFiltersFor } from "@/lib/filters";
import { useUrlFilters, useUrlState } from "@/lib/useUrlState";
import { PageTitle, Card, Spinner, ErrorBox, Empty, Badge, StatTile, Segmented } from "@/components/ui";
import { cn, fmtSigned } from "@/lib/utils";

type Row = Record<string, unknown>;

// Keeping and fielding boards rank dismissal *counts*: a 12-month count against a career count isn't form, so
// they're left out here (every other board is a rate or an index).
// Form needs a "better" direction: the volume boards and the descriptive Boundary Dependency are left out.
const FORM_METRICS = METRICS.filter((m) => m.slug !== "keeping" && m.slug !== "fielding" && m.direction !== "descriptive");

const WINDOW_LABEL: Record<string, string> = {
  last1y: "last 12 months",
  last3y: "last 3 years",
};

export function Form() {
  const { collection, meta } = useStore();
  const navigate = useNavigate();
  // metric, window and non-default filters live in the URL (shareable links)
  const [slug, setSlug] = useUrlState<string>("metric", "ngi", {
    valid: FORM_METRICS.map((m) => m.slug),
    replace: false,
  });
  const metric = METRIC_BY_SLUG[slug];
  const pcol = primaryCol(metric);
  const valueKey = pcol.key;
  // NGI reads as a percentage ("+3.4%"); everything else as a plain number
  const show = (v: number) => (pcol.fmt ? fmtMetric(v, pcol) : fmtSigned(v, 2));
  const { nameOf } = usePlayers(collection);
  const nameKey = metric.nameCol;

  // Recent-window picker — whichever recomputed windows this collection cooked.
  const windows: string[] = (meta?.windows ?? []).filter((w) => w === "last1y" || w === "last3y");
  const [win, setWin] = useUrlState<string>("window", "", { valid: windows, ready: !!meta, replace: false });
  const recentWin = win && windows.includes(win) ? win : (windows[0] ?? null);

  const career = useAsync(() => getLeaderboard(collection, slug, "all"), [collection, slug]);
  const recent = useAsync(
    () => (recentWin ? getLeaderboard(collection, slug, recentWin) : Promise.resolve([])),
    [collection, slug, recentWin],
  );
  // same defaults as the leaderboards: established, active players, the min-matches sized to the window
  const defaults = useMemo(() => defaultFiltersFor((recent.data ?? []) as Row[]), [recent.data]);
  const [filters, setFilters] = useUrlFilters(defaults);

  // only the filters / options that can apply to this metric's board
  const smart = useMemo(
    () => smartFilters((recent.data ?? []) as Row[], filters, metric.filters, metric.exclude),
    [recent.data, filters, metric],
  );

  const rows = useMemo(() => {
    if (!career.data || !recent.data) return [];
    const careerBy = new Map<string, LeaderboardRow>();
    for (const r of career.data) {
      const k = r[nameKey];
      if (typeof k === "string") careerBy.set(k, r);
    }
    const filteredRecent = applyFilters(recent.data as Row[], smart.effective);
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
  }, [career.data, recent.data, nameKey, valueKey, metric.higherIsBetter, smart.effective]);

  const top = useMemo(() => [...rows].sort((a, b) => Number(b.mv) - Number(a.mv)), [rows]);
  // risers are only players actually improving, fallers only players declining — the two lists never overlap
  const heating = top.filter((r) => Number(r.mv) > 0);
  const cooling = [...top].reverse().filter((r) => Number(r.mv) < 0);
  const riser = heating[0];
  const faller = cooling[0];

  const cols: Col<Row>[] = [
    { key: "name", label: "Player", primary: false, render: (r: Row) => <span className="font-medium text-fg">{nameOf(String(r.name))}</span> },
    { key: "career", label: "Career", align: "right", digits: 2, fmtValue: pcol.fmt ? (v) => fmtMetric(v, pcol) : undefined },
    { key: "recent", label: WINDOW_LABEL[recentWin ?? ""] ?? "Recent", align: "right", digits: 2, fmtValue: pcol.fmt ? (v) => fmtMetric(v, pcol) : undefined },
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
            {show(v)}
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

      <div role="radiogroup" aria-label="Metric" className="mb-4 flex flex-wrap gap-2">
        {FORM_METRICS.map((m) => (
          <button
            key={m.slug}
            role="radio"
            aria-checked={m.slug === slug}
            onClick={() => setSlug(m.slug)}
            className={cn(
              "rounded-lg border px-3 py-1.5 text-sm font-medium transition-all",
              m.slug === slug
                ? "border-accent/40 bg-accent/10 text-accent-glow shadow-glow"
                : "border-border bg-surface/70 text-muted hover:border-accent/30 hover:text-fg",
            )}
          >
            {m.name}
          </button>
        ))}
      </div>

      {windows.length > 1 && (
        <div className="mb-4 flex flex-wrap items-center gap-2">
          <span className="text-sm font-medium text-muted">Recent window</span>
          <Segmented
            label="Recent window"
            value={recentWin ?? windows[0]}
            onChange={setWin}
            options={windows.map((w) => ({ value: w, label: WINDOW_LABEL[w] ?? w }))}
          />
        </div>
      )}

      <FilterBar
        filters={filters}
        onChange={setFilters}
        defaults={defaults}
        smart={smart}
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
                  <MetricInfo m={metric} />
                  {!metric.higherIsBetter && <Badge tone="muted">lower is better → sign-flipped</Badge>}
                </div>
                <p className="mt-1 text-sm leading-relaxed text-muted">{metric.what}</p>
              </div>
            </div>
          </Card>

          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            {riser && (
              <StatTile label="Biggest riser" value={nameOf(String(riser.name))} hint={`${show(Number(riser.mv))} form Δ`} />
            )}
            {faller && (
              <StatTile label="Biggest faller" value={nameOf(String(faller.name))} hint={`${show(Number(faller.mv))} form Δ`} />
            )}
          </div>

          <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
            <div>
              <div className="mb-2 flex items-center gap-2 text-sm font-semibold text-willow">
                <TrendingUp className="h-4 w-4" /> Heating up
              </div>
              {heating.length ? (
                <DataTable
                  rows={heating.slice(0, 25)}
                  cols={cols}
                  initialSort={{ key: "mv", dir: "desc" }}
                  rowLabel={(r) => `Open ${nameOf(String(r.name))}'s profile`}
                  onRowClick={(r) => navigate(`/player?name=${encodeURIComponent(String(r.name))}`)}
                />
              ) : (
                <Empty>Nobody is above their career level on this one.</Empty>
              )}
            </div>
            <div>
              <div className="mb-2 flex items-center gap-2 text-sm font-semibold text-ball">
                <TrendingDown className="h-4 w-4" /> Cooling down
              </div>
              {cooling.length ? (
                <DataTable
                  rows={cooling.slice(0, 25)}
                  cols={cols}
                  initialSort={{ key: "mv", dir: "asc" }}
                  rowLabel={(r) => `Open ${nameOf(String(r.name))}'s profile`}
                  onRowClick={(r) => navigate(`/player?name=${encodeURIComponent(String(r.name))}`)}
                />
              ) : (
                <Empty>Nobody is below their career level on this one.</Empty>
              )}
            </div>
          </div>
        </div>
      )}
    </>
  );
}
