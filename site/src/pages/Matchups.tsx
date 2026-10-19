import { useMemo } from "react";
import { Crosshair, Zap, Disc } from "lucide-react";
import { useStore } from "@/lib/store";
import { useAsync } from "@/lib/useAsync";
import { getMatchups, type Matchups as MatchupsData } from "@/lib/data";
import { usePlayers } from "@/lib/usePlayers";
import { Combobox } from "@/components/Combobox";
import { DataTable, type Col } from "@/components/DataTable";
import { PageTitle, Card, CardHeader, Spinner, Empty, StatTile, Badge, ErrorBox } from "@/components/ui";
import { fmt } from "@/lib/utils";
import { useUrlId, useUrlNumber } from "@/lib/useUrlState";

type Row = Record<string, unknown>;

const BAT_COLS: Col<Row>[] = [
  { key: "bowler", label: "Bowler", primary: false },
  { key: "balls", label: "Balls", align: "right", digits: 0 },
  { key: "runs", label: "Runs", align: "right", digits: 0 },
  { key: "sr", label: "SR", align: "right", digits: 1, primary: true },
  { key: "dot_pct", label: "Dot %", align: "right", digits: 1 },
  { key: "outs", label: "Outs", align: "right", digits: 0 },
];
const BOWL_COLS: Col<Row>[] = [
  { key: "batter", label: "Batter", primary: false },
  { key: "balls", label: "Balls", align: "right", digits: 0 },
  { key: "runs", label: "Runs", align: "right", digits: 0 },
  { key: "sr", label: "SR conceded", align: "right", digits: 1, primary: true },
  { key: "dot_pct", label: "Dot %", align: "right", digits: 1 },
  { key: "outs", label: "Wkts", align: "right", digits: 0 },
];

/** The opponent column shows the fan name (rows carry the scorecard name and the registry id). */
function withNames(cols: Col<Row>[], key: string, nameOf: (n: string, cid?: unknown) => string): Col<Row>[] {
  return cols.map((c) =>
    c.key === key
      ? { ...c, render: (r: Row) => <span className="text-fg">{nameOf(String(r[key] ?? ""), r[`${key}_id`])}</span> }
      : c,
  );
}

/** "once every 26 balls" — a dismissal rate a fan can picture. */
function outEvery(side: { balls: number; outs: number }): string {
  if (!side.outs) return "never out";
  return `once every ${Math.round(side.balls / side.outs)} balls`;
}

function Splits({ splits }: { splits: MatchupsData["splits"] }) {
  if (!splits || (!splits.vs_seam && !splits.vs_spin)) return null;
  const seam = splits.vs_seam;
  const spin = splits.vs_spin;
  // Lower SR side = the weaker matchup for this batter.
  const weaker =
    seam && spin ? (seam.sr < spin.sr ? "pace" : spin.sr < seam.sr ? "spin" : null) : null;
  return (
    <Card>
      <CardHeader
        title="Pace vs spin"
        subtitle="How this batter scores and survives against seam vs spin (career)"
        right={
          weaker && (
            <Badge tone="ball">
              weaker vs {weaker}
            </Badge>
          )
        }
      />
      <div className="grid grid-cols-2 gap-3 p-4 sm:grid-cols-4">
        {seam && (
          <>
            <StatTile label="vs Pace — SR" value={fmt(seam.sr, 1)} hint={`${seam.balls} balls`} />
            <StatTile
              label="vs Pace — gets out"
              value={outEvery(seam)}
              hint={`${seam.outs} dismissals · out on ${fmt(seam.out_rate, 2)}% of balls faced`}
            />
          </>
        )}
        {spin && (
          <>
            <StatTile label="vs Spin — SR" value={fmt(spin.sr, 1)} hint={`${spin.balls} balls`} />
            <StatTile
              label="vs Spin — gets out"
              value={outEvery(spin)}
              hint={`${spin.outs} dismissals · out on ${fmt(spin.out_rate, 2)}% of balls faced`}
            />
          </>
        )}
      </div>
    </Card>
  );
}

export function Matchups() {
  const { collection } = useStore();
  const { options, players, byId, nameOf, loading: playersLoading } = usePlayers(collection);
  const batCols = useMemo(() => withNames(BAT_COLS, "bowler", nameOf), [nameOf]);
  const bowlCols = useMemo(() => withNames(BOWL_COLS, "batter", nameOf), [nameOf]);
  // player + min-balls live in the URL (`?player=…&minballs=…`) so a link reproduces the view
  const [cid, setCid] = useUrlId("player", byId, players.length > 0);
  const [minBalls, setMinBalls] = useUrlNumber("minballs", 6, { min: 1 });
  const { data, loading, error } = useAsync<MatchupsData | null>(
    () => (cid ? getMatchups(collection, cid) : Promise.resolve(null)),
    [collection, cid],
  );

  const asBatter = useMemo(
    () => (data?.as_batter ?? []).filter((r) => r.balls >= minBalls),
    [data, minBalls],
  );
  const asBowler = useMemo(
    () => (data?.as_bowler ?? []).filter((r) => r.balls >= minBalls),
    [data, minBalls],
  );

  return (
    <>
      <PageTitle
        title="Matchups"
        icon={<Crosshair className="h-6 w-6" />}
        desc="Pick a player to see their toughest and favourite head-to-heads — ball-by-ball as a batter and as a bowler — plus how a batter fares against pace versus spin."
      />

      <div className="mb-6 flex flex-wrap items-center gap-3">
        <Combobox
          options={options}
          value={cid}
          onChange={setCid}
          placeholder={playersLoading ? "Loading players…" : "Search a player…"}
          className="max-w-md flex-1"
        />
        <label className="flex items-center gap-2 text-sm text-muted">
          <span>Min balls</span>
          <input
            type="number"
            min={1}
            value={minBalls}
            onChange={(e) => setMinBalls(Math.max(1, Number(e.target.value) || 1))}
            className="input w-20 py-1.5"
          />
        </label>
      </div>

      {!cid ? (
        <Empty>Pick a player to see their matchups.</Empty>
      ) : loading && !data ? (
        <Spinner label="Loading matchups…" />
      ) : error && !error.startsWith("Not available") ? (
        <ErrorBox message={error} />
      ) : !data ? (
        <Empty>No matchup data for this player (needs enough balls faced/bowled).</Empty>
      ) : (
        <div className="space-y-5 animate-fade-up">
          <Splits splits={data.splits} />

          {asBatter.length > 0 && (
            <div>
              <div className="mb-2 flex items-center gap-2 text-sm font-semibold text-fg">
                <Zap className="h-4 w-4 text-accent" /> As a batter — opponents faced
              </div>
              <DataTable
                rows={asBatter as unknown as Row[]}
                cols={batCols}
                initialSort={{ key: "balls", dir: "desc" }}
              />
            </div>
          )}

          {asBowler.length > 0 && (
            <div>
              <div className="mb-2 flex items-center gap-2 text-sm font-semibold text-fg">
                <Disc className="h-4 w-4 text-ball" /> As a bowler — batters faced
              </div>
              <DataTable
                rows={asBowler as unknown as Row[]}
                cols={bowlCols}
                initialSort={{ key: "balls", dir: "desc" }}
              />
            </div>
          )}

          {asBatter.length === 0 && asBowler.length === 0 && (
            <Empty>No head-to-heads at ≥ {minBalls} balls — lower the min.</Empty>
          )}
        </div>
      )}
    </>
  );
}
