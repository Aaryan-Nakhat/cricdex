import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Gavel, Wallet, Users, CheckCircle2, AlertTriangle } from "lucide-react";
import { useStore } from "@/lib/store";
import { usePlayers } from "@/lib/usePlayers";
import { useAsync } from "@/lib/useAsync";
import { getRatings } from "@/lib/data";
import { buildPool, solve, type PoolPlayer } from "@/lib/auction";
import { PageTitle, Card, CardHeader, Spinner, Badge, StatTile, Empty } from "@/components/ui";
import { cn, fmt } from "@/lib/utils";

function NumberField({
  label,
  value,
  onChange,
  min = 0,
  max = 999,
  step = 1,
  suffix,
}: {
  label: string;
  value: number;
  onChange: (v: number) => void;
  min?: number;
  max?: number;
  step?: number;
  suffix?: string;
}) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs font-medium text-muted">{label}</span>
      <div className="flex items-center gap-2">
        <input
          type="number"
          className="input"
          value={value}
          min={min}
          max={max}
          step={step}
          onChange={(e) => onChange(Number(e.target.value))}
        />
        {suffix && <span className="text-xs text-muted">{suffix}</span>}
      </div>
    </label>
  );
}

const ROLE_TONE: Record<string, "accent" | "willow" | "muted"> = {
  batter: "accent",
  bowler: "willow",
  all_rounder: "muted",
};

export function Auction() {
  const { collection } = useStore();
  const navigate = useNavigate();
  const { players } = usePlayers(collection);
  const ratings = useAsync(() => getRatings(collection), [collection]);

  const [purse, setPurse] = useState(100);
  const [squadSize, setSquadSize] = useState(18);
  const [minBat, setMinBat] = useState(6);
  const [minBowl, setMinBowl] = useState(5);
  const [minAr, setMinAr] = useState(2);

  const pool = useMemo<PoolPlayer[]>(
    () => (ratings.data && players.length ? buildPool(players, ratings.data) : []),
    [ratings.data, players],
  );

  const result = useMemo(
    () =>
      pool.length
        ? solve(pool, {
            purse,
            squadSize,
            roleMins: { batter: minBat, bowler: minBowl, all_rounder: minAr },
          })
        : null,
    [pool, purse, squadSize, minBat, minBowl, minAr],
  );

  const roleCounts = result
    ? result.selected.reduce(
        (a, p) => ((a[p.role] = (a[p.role] ?? 0) + 1), a),
        {} as Record<string, number>,
      )
    : {};

  return (
    <>
      <PageTitle
        title="Auction room"
        icon={<Gavel className="h-6 w-6" />}
        desc="Build the highest-value squad you can afford. Set the purse, squad size and role minimums; the optimiser fills the best value-per-credit players within your constraints. Prices and values are model-estimated from Bayesian skill."
      />

      {ratings.loading ? (
        <Spinner label="Pricing the pool…" />
      ) : pool.length === 0 ? (
        <Empty>No rated pool available for {collection}.</Empty>
      ) : (
        <div className="grid grid-cols-1 gap-5 lg:grid-cols-[300px_1fr]">
          {/* controls */}
          <div className="space-y-4">
            <Card className="space-y-4 p-5">
              <div className="flex items-center gap-2 text-sm font-semibold text-fg">
                <Wallet className="h-4 w-4 text-accent" /> Constraints
              </div>
              <NumberField label="Purse" value={purse} onChange={setPurse} min={10} max={500} step={5} suffix="cr" />
              <NumberField label="Squad size" value={squadSize} onChange={setSquadSize} min={5} max={30} />
              <div className="grid grid-cols-3 gap-2">
                <NumberField label="Min bat" value={minBat} onChange={setMinBat} min={0} max={15} />
                <NumberField label="Min bowl" value={minBowl} onChange={setMinBowl} min={0} max={15} />
                <NumberField label="Min AR" value={minAr} onChange={setMinAr} min={0} max={10} />
              </div>
            </Card>
            <Card className="p-4 text-xs leading-relaxed text-muted">
              <AlertTriangle className="mb-1 inline h-3.5 w-3.5 text-willow" /> The web optimiser is a
              fast value-per-credit heuristic. The desktop CLI/TUI solves this exactly as a mixed-integer
              program, adds the overseas-player cap, and runs a Monte-Carlo simulation of rival franchises.
            </Card>
          </div>

          {/* result */}
          <div className="space-y-4">
            {result && (
              <>
                <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                  <StatTile label="Squad" value={`${result.selected.length}`} hint={`/ ${squadSize}`} />
                  <StatTile label="Spend" value={`${fmt(result.spend, 1)} cr`} hint={`of ${purse} cr`} />
                  <StatTile label="Projected value" value={`${fmt(result.totalValue, 1)} cr`} />
                  <StatTile
                    label="Composition"
                    value={`${roleCounts.batter ?? 0}/${roleCounts.bowler ?? 0}/${roleCounts.all_rounder ?? 0}`}
                    hint="bat / bowl / AR"
                  />
                </div>

                <div
                  className={cn(
                    "flex items-center gap-2 rounded-lg border px-4 py-2.5 text-sm",
                    result.feasible
                      ? "border-accent/30 bg-accent/5 text-accent-glow"
                      : "border-ball/30 bg-ball/5 text-ball",
                  )}
                >
                  {result.feasible ? <CheckCircle2 className="h-4 w-4" /> : <AlertTriangle className="h-4 w-4" />}
                  {result.note}
                </div>

                <Card className="overflow-hidden">
                  <CardHeader
                    title="Selected squad"
                    subtitle="Ranked by projected value — click a player for their dossier"
                    right={<Users className="h-4 w-4 text-muted" />}
                  />
                  <div className="overflow-auto" style={{ maxHeight: "60vh" }}>
                    <table className="w-full border-collapse">
                      <thead>
                        <tr>
                          <th className="th w-10 text-right">#</th>
                          <th className="th">Player</th>
                          <th className="th">Role</th>
                          <th className="th text-right">Proj. value</th>
                          <th className="th text-right">Est. price</th>
                          <th className="th text-right">Value / cr</th>
                        </tr>
                      </thead>
                      <tbody>
                        {result.selected.map((p, i) => (
                          <tr
                            key={p.cricsheet_id}
                            className="cursor-pointer hover:bg-surface/60"
                            onClick={() => navigate(`/player?cid=${p.cricsheet_id}`)}
                          >
                            <td className="td text-right stat-num text-muted">{i + 1}</td>
                            <td className="td font-medium text-fg">{p.name}</td>
                            <td className="td">
                              <Badge tone={ROLE_TONE[p.role]}>{p.role.replace("_", "-")}</Badge>
                            </td>
                            <td className="td stat-num text-right">{fmt(p.projected_value, 1)}</td>
                            <td className="td stat-num text-right text-muted">{fmt(p.base_price, 2)}</td>
                            <td className="td stat-num text-right text-accent-glow">{fmt(p.vpc, 2)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </Card>
              </>
            )}
          </div>
        </div>
      )}
    </>
  );
}
