import { useMemo, useState } from "react";
import { Timer } from "lucide-react";
import { useStore } from "@/lib/store";
import { useAsync } from "@/lib/useAsync";
import { getPhase } from "@/lib/data";
import { DataTable, type Col } from "@/components/DataTable";
import { FilterBar } from "@/components/FilterBar";
import { applyFilters, countriesIn, EMPTY_FILTERS, type Filters } from "@/lib/filters";
import { PageTitle, Spinner, ErrorBox, Empty } from "@/components/ui";
import { cn } from "@/lib/utils";

type Row = Record<string, unknown>;
type PhaseKey = "powerplay" | "middle" | "death";

const PHASES: { key: PhaseKey; label: string; overs: string }[] = [
  { key: "powerplay", label: "Powerplay", overs: "overs 1–6" },
  { key: "middle", label: "Middle", overs: "overs 7–15" },
  { key: "death", label: "Death", overs: "overs 16–20" },
];

const BAT_COLS: Col<Row>[] = [
  { key: "name", label: "Batter", primary: false },
  { key: "runs", label: "Runs", align: "right", digits: 0 },
  { key: "balls", label: "Balls", align: "right", digits: 0 },
  { key: "sr", label: "Strike rate", align: "right", digits: 1, primary: true },
];
const BOWL_COLS: Col<Row>[] = [
  { key: "name", label: "Bowler", primary: false },
  { key: "wickets", label: "Wkts", align: "right", digits: 0 },
  { key: "balls", label: "Balls", align: "right", digits: 0 },
  { key: "runs", label: "Runs", align: "right", digits: 0 },
  { key: "econ", label: "Economy", align: "right", digits: 2, primary: true },
];
const TOP = 25;

export function Phase() {
  const { collection } = useStore();
  const { data, loading, error } = useAsync(() => getPhase(collection), [collection]);
  const [phase, setPhase] = useState<PhaseKey>("powerplay");
  const [filters, setFilters] = useState<Filters>(EMPTY_FILTERS);

  const board = data?.[phase];
  const rawBatters = (board?.batters ?? []) as unknown as Row[];
  const rawBowlers = (board?.bowlers ?? []) as unknown as Row[];

  const countryOpts = useMemo(
    () => countriesIn([...rawBatters, ...rawBowlers]),
    [rawBatters, rawBowlers],
  );
  const batters = useMemo(
    () => applyFilters(rawBatters, filters).slice(0, TOP),
    [rawBatters, filters],
  );
  const bowlers = useMemo(
    () => applyFilters(rawBowlers, filters).slice(0, TOP),
    [rawBowlers, filters],
  );

  return (
    <>
      <PageTitle
        title="Phase specialists"
        icon={<Timer className="h-6 w-6" />}
        desc="Who actually dominates each phase of the innings — best strike rates with the bat and tightest economies with the ball across the powerplay, middle overs and death."
      />

      <div className="mb-4 flex flex-wrap gap-2">
        {PHASES.map((p) => (
          <button
            key={p.key}
            onClick={() => setPhase(p.key)}
            className={cn(
              "rounded-lg border px-3.5 py-2 text-sm transition-colors",
              phase === p.key
                ? "border-accent/50 bg-accent/10 text-accent-glow"
                : "border-border bg-surface text-muted hover:text-fg",
            )}
          >
            <span className="font-semibold">{p.label}</span>
            <span className="ml-1.5 text-xs text-muted">{p.overs}</span>
          </button>
        ))}
      </div>

      <FilterBar
        filters={filters}
        onChange={setFilters}
        show={["minMatches", "activity", "role", "bowling", "position", "country"]}
        countryOpts={countryOpts}
      />

      {loading ? (
        <Spinner />
      ) : error ? (
        <ErrorBox message={error} />
      ) : !board ? (
        <Empty>No phase data for this collection.</Empty>
      ) : (
        <div className="grid grid-cols-1 gap-5 animate-fade-up lg:grid-cols-2">
          <div>
            <div className="mb-2 text-sm font-semibold text-fg">Best strike rates</div>
            {batters.length ? (
              <DataTable rows={batters} cols={BAT_COLS} initialSort={{ key: "sr", dir: "desc" }} />
            ) : (
              <Empty>No batters match these filters.</Empty>
            )}
          </div>
          <div>
            <div className="mb-2 text-sm font-semibold text-fg">Tightest economies</div>
            {bowlers.length ? (
              <DataTable rows={bowlers} cols={BOWL_COLS} initialSort={{ key: "econ", dir: "asc" }} />
            ) : (
              <Empty>No bowlers match these filters.</Empty>
            )}
          </div>
        </div>
      )}
    </>
  );
}
