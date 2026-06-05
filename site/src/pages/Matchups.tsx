import { useState } from "react";
import { Crosshair, Zap, Disc } from "lucide-react";
import { useStore } from "@/lib/store";
import { useAsync } from "@/lib/useAsync";
import { getMatchups, type Matchups as MatchupsData } from "@/lib/data";
import { usePlayers } from "@/lib/usePlayers";
import { Combobox } from "@/components/Combobox";
import { DataTable, type Col } from "@/components/DataTable";
import { PageTitle, Card, CardHeader, Spinner, Empty, StatTile, Badge } from "@/components/ui";
import { fmt } from "@/lib/utils";

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
              label="vs Pace — out rate"
              value={`${fmt(seam.out_rate, 2)}%`}
              hint={`${seam.outs} dismissals`}
            />
          </>
        )}
        {spin && (
          <>
            <StatTile label="vs Spin — SR" value={fmt(spin.sr, 1)} hint={`${spin.balls} balls`} />
            <StatTile
              label="vs Spin — out rate"
              value={`${fmt(spin.out_rate, 2)}%`}
              hint={`${spin.outs} dismissals`}
            />
          </>
        )}
      </div>
    </Card>
  );
}

export function Matchups() {
  const { collection } = useStore();
  const { options, loading: playersLoading } = usePlayers(collection);
  const [cid, setCid] = useState<string | null>(null);
  const { data, loading, error } = useAsync<MatchupsData | null>(
    () => (cid ? getMatchups(collection, cid) : Promise.resolve(null)),
    [collection, cid],
  );

  return (
    <>
      <PageTitle
        title="Matchups"
        icon={<Crosshair className="h-6 w-6" />}
        desc="Pick a player to see their toughest and favourite head-to-heads — ball-by-ball as a batter and as a bowler — plus how a batter fares against pace versus spin."
      />

      <div className="mb-6 max-w-md">
        <Combobox
          options={options}
          value={cid}
          onChange={setCid}
          placeholder={playersLoading ? "Loading players…" : "Search a player…"}
        />
      </div>

      {!cid ? (
        <Empty>Pick a player to see their matchups.</Empty>
      ) : loading ? (
        <Spinner />
      ) : error || !data ? (
        <Empty>No matchup data for this player (needs enough balls faced/bowled).</Empty>
      ) : (
        <div className="space-y-5 animate-fade-up">
          <Splits splits={data.splits} />

          {data.as_batter.length > 0 && (
            <div>
              <div className="mb-2 flex items-center gap-2 text-sm font-semibold text-fg">
                <Zap className="h-4 w-4 text-accent" /> As a batter — opponents faced
              </div>
              <DataTable
                rows={data.as_batter as unknown as Row[]}
                cols={BAT_COLS}
                initialSort={{ key: "balls", dir: "desc" }}
              />
            </div>
          )}

          {data.as_bowler.length > 0 && (
            <div>
              <div className="mb-2 flex items-center gap-2 text-sm font-semibold text-fg">
                <Disc className="h-4 w-4 text-ball" /> As a bowler — batters faced
              </div>
              <DataTable
                rows={data.as_bowler as unknown as Row[]}
                cols={BOWL_COLS}
                initialSort={{ key: "balls", dir: "desc" }}
              />
            </div>
          )}

          {data.as_batter.length === 0 && data.as_bowler.length === 0 && (
            <Empty>No qualifying head-to-heads for this player.</Empty>
          )}
        </div>
      )}
    </>
  );
}
