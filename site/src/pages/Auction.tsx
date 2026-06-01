import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Gavel, Wallet, Users, CheckCircle2, AlertTriangle, Dices, Plane } from "lucide-react";
import { useStore } from "@/lib/store";
import { usePlayers } from "@/lib/usePlayers";
import { useAsync } from "@/lib/useAsync";
import { getRatings } from "@/lib/data";
import {
  buildPool,
  solve,
  simulateAuction,
  ARCHETYPES,
  IPL_TEAMS_DEFAULT,
  type PoolPlayer,
} from "@/lib/auction";
import { PageTitle, Card, CardHeader, Spinner, Badge, StatTile, Empty, InfoTip } from "@/components/ui";
import { cn, fmt } from "@/lib/utils";

const ROLE_TONE: Record<string, "accent" | "willow" | "muted" | "ball"> = {
  batter: "accent",
  bowler: "ball",
  all_rounder: "willow",
  keeper: "muted",
};

function NumberField({ label, value, onChange, min = 0, max = 999, step = 1, suffix }: {
  label: string; value: number; onChange: (v: number) => void; min?: number; max?: number; step?: number; suffix?: string;
}) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs font-medium text-muted">{label}</span>
      <div className="flex items-center gap-2">
        <input type="number" className="input" value={value} min={min} max={max} step={step}
          onChange={(e) => onChange(Number(e.target.value))} />
        {suffix && <span className="text-xs text-muted">{suffix}</span>}
      </div>
    </label>
  );
}

export function Auction() {
  const { collection } = useStore();
  const navigate = useNavigate();
  const { players } = usePlayers(collection);
  const ratings = useAsync(() => getRatings(collection), [collection]);
  const [mode, setMode] = useState<"build" | "simulate">("build");

  const pool = useMemo<PoolPlayer[]>(
    () => (ratings.data && players.length ? buildPool(players, ratings.data) : []),
    [ratings.data, players],
  );

  return (
    <>
      <PageTitle
        title="Auction room"
        icon={<Gavel className="h-6 w-6" />}
        desc="A T20 auction is a constrained optimisation: build the strongest XI-plus-squad you can under a fixed purse, a squad size, role minimums, and an overseas-player cap. Two tools here — optimise YOUR squad, or simulate the whole auction against the ten IPL franchises, each bidding to its own personality."
      />

      {/* what is this for */}
      <Card className="mb-5 px-5 py-4 text-sm leading-relaxed text-muted">
        <span className="font-semibold text-fg">What it's for: </span>
        Player values + estimated prices come from the Bayesian skill model. <b>Build my squad</b> runs
        a value-per-credit optimiser to assemble the best squad your purse allows. <b>Simulate the
        auction</b> drops every player under the hammer and lets all ten franchises bid by their
        archetype (marquee-chaser, value-hunter, overseas-heavy…), repeated hundreds of times, so you
        see who likely lands each marquee name and how each squad shapes up.
      </Card>

      <div className="mb-5 flex gap-2">
        {(["build", "simulate"] as const).map((m) => (
          <button
            key={m}
            onClick={() => setMode(m)}
            className={cn(
              "rounded-lg border px-4 py-2 text-sm font-medium transition-all",
              mode === m
                ? "border-accent/40 bg-accent/10 text-accent-glow shadow-glow"
                : "border-border bg-surface text-muted hover:text-fg",
            )}
          >
            {m === "build" ? "Build my squad" : "Simulate the auction"}
          </button>
        ))}
      </div>

      {ratings.loading ? (
        <Spinner label="Pricing the pool…" />
      ) : pool.length === 0 ? (
        <Empty>No rated pool available for {collection}.</Empty>
      ) : mode === "build" ? (
        <BuildSquad pool={pool} navigate={navigate} />
      ) : (
        <Simulate pool={pool} navigate={navigate} />
      )}
    </>
  );
}

function BuildSquad({ pool, navigate }: { pool: PoolPlayer[]; navigate: (p: string) => void }) {
  const [purse, setPurse] = useState(100);
  const [squadSize, setSquadSize] = useState(18);
  const [overseasCap, setOverseasCap] = useState(8);
  const [minBat, setMinBat] = useState(6);
  const [minBowl, setMinBowl] = useState(5);
  const [minAr, setMinAr] = useState(2);
  const [minKp, setMinKp] = useState(1);

  const result = useMemo(
    () =>
      solve(pool, {
        purse,
        squadSize,
        overseasCap,
        roleMins: { batter: minBat, bowler: minBowl, all_rounder: minAr, keeper: minKp },
      }),
    [pool, purse, squadSize, overseasCap, minBat, minBowl, minAr, minKp],
  );

  const roleCounts = result.selected.reduce(
    (a, p) => ((a[p.role] = (a[p.role] ?? 0) + 1), a),
    {} as Record<string, number>,
  );

  return (
    <div className="grid grid-cols-1 gap-5 lg:grid-cols-[300px_1fr]">
      <div className="space-y-4">
        <Card className="space-y-4 p-5">
          <div className="flex items-center gap-2 text-sm font-semibold text-fg">
            <Wallet className="h-4 w-4 text-accent" /> Constraints
          </div>
          <NumberField label="Purse" value={purse} onChange={setPurse} min={10} max={500} step={5} suffix="cr" />
          <div className="grid grid-cols-2 gap-2">
            <NumberField label="Squad size" value={squadSize} onChange={setSquadSize} min={5} max={30} />
            <NumberField label="Overseas cap" value={overseasCap} onChange={setOverseasCap} min={0} max={11} />
          </div>
          <div className="grid grid-cols-4 gap-2">
            <NumberField label="Bat" value={minBat} onChange={setMinBat} min={0} max={11} />
            <NumberField label="Bowl" value={minBowl} onChange={setMinBowl} min={0} max={11} />
            <NumberField label="AR" value={minAr} onChange={setMinAr} min={0} max={11} />
            <NumberField label="WK" value={minKp} onChange={setMinKp} min={0} max={4} />
          </div>
        </Card>
      </div>

      <div className="space-y-4">
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-5">
          <StatTile label="Squad" value={`${result.selected.length}`} hint={`/ ${squadSize}`} />
          <StatTile label="Spend" value={`${fmt(result.spend, 1)} cr`} hint={`of ${purse}`} />
          <StatTile label="Value" value={`${fmt(result.totalValue, 1)} cr`} />
          <StatTile label="Overseas" value={`${result.overseas}`} hint={`/ ${overseasCap}`} />
          <StatTile label="Bat/Bowl/AR/WK" value={`${roleCounts.batter ?? 0}/${roleCounts.bowler ?? 0}/${roleCounts.all_rounder ?? 0}/${roleCounts.keeper ?? 0}`} />
        </div>
        <div className={cn("flex items-center gap-2 rounded-lg border px-4 py-2.5 text-sm",
          result.feasible ? "border-accent/30 bg-accent/5 text-accent-glow" : "border-ball/30 bg-ball/5 text-ball")}>
          {result.feasible ? <CheckCircle2 className="h-4 w-4" /> : <AlertTriangle className="h-4 w-4" />}
          {result.note}
        </div>
        <SquadTable rows={result.selected} navigate={navigate} />
      </div>
    </div>
  );
}

function SquadTable({ rows, navigate }: { rows: PoolPlayer[]; navigate: (p: string) => void }) {
  return (
    <Card className="overflow-hidden">
      <CardHeader title="Selected squad" subtitle="Ranked by projected value — click for the dossier" right={<Users className="h-4 w-4 text-muted" />} />
      <div className="overflow-auto" style={{ maxHeight: "55vh" }}>
        <table className="w-full border-collapse">
          <thead>
            <tr>
              <th className="th w-10 text-right">#</th>
              <th className="th">Player</th>
              <th className="th">Role</th>
              <th className="th">Nat</th>
              <th className="th text-right">Value</th>
              <th className="th text-right">Price</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((p, i) => (
              <tr key={p.cricsheet_id} className="cursor-pointer hover:bg-surface/60" onClick={() => navigate(`/player?cid=${p.cricsheet_id}`)}>
                <td className="td text-right stat-num text-muted">{i + 1}</td>
                <td className="td font-medium text-fg">{p.name}</td>
                <td className="td"><Badge tone={ROLE_TONE[p.role]}>{p.role.replace("_", "-")}</Badge></td>
                <td className="td">{p.is_overseas ? <span className="inline-flex items-center gap-1 text-xs text-willow"><Plane className="h-3 w-3" />{p.country}</span> : <span className="text-xs text-muted">{p.country}</span>}</td>
                <td className="td stat-num text-right">{fmt(p.projected_value, 1)}</td>
                <td className="td stat-num text-right text-muted">{fmt(p.base_price, 2)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

function Simulate({ pool, navigate }: { pool: PoolPlayer[]; navigate: (p: string) => void }) {
  const [teams, setTeams] = useState(IPL_TEAMS_DEFAULT);
  const [purse, setPurse] = useState(90);
  const [squadSize, setSquadSize] = useState(18);
  const [overseasCap, setOverseasCap] = useState(8);
  const [trials, setTrials] = useState(300);
  const [focus, setFocus] = useState(0); // which team's sample squad to show

  const result = useMemo(
    () => simulateAuction(pool, teams, { purse, squadSize, overseasCap, trials }),
    [pool, teams, purse, squadSize, overseasCap, trials],
  );

  const draft = result.sampleDraft[focus];

  return (
    <div className="space-y-5">
      {/* team personalities */}
      <Card className="p-5">
        <div className="mb-3 flex items-center gap-2 text-sm font-semibold text-fg">
          <Dices className="h-4 w-4 text-accent" /> Franchise personalities
          <InfoTip title="Bidding archetypes">
            <div className="space-y-1">
              {ARCHETYPES.map((a) => (
                <div key={a.id}><b className="text-fg">{a.id}</b>: {a.blurb}</div>
              ))}
            </div>
          </InfoTip>
        </div>
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-5">
          {teams.map((t, i) => (
            <div key={t.team} className="rounded-lg border border-border bg-surface/50 p-2">
              <div className="mb-1 text-xs font-bold text-fg">{t.team}</div>
              <select
                value={t.personality}
                onChange={(e) => setTeams((ts) => ts.map((x, j) => (j === i ? { ...x, personality: e.target.value } : x)))}
                className="input w-full cursor-pointer py-1 text-xs"
              >
                {ARCHETYPES.map((a) => (
                  <option key={a.id} value={a.id} className="bg-card">{a.id}</option>
                ))}
              </select>
            </div>
          ))}
        </div>
        <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
          <NumberField label="Purse / team" value={purse} onChange={setPurse} min={10} max={500} step={5} suffix="cr" />
          <NumberField label="Squad size" value={squadSize} onChange={setSquadSize} min={5} max={30} />
          <NumberField label="Overseas cap" value={overseasCap} onChange={setOverseasCap} min={0} max={11} />
          <NumberField label="Trials" value={trials} onChange={setTrials} min={50} max={1000} step={50} />
        </div>
      </Card>

      {/* per-team outcomes */}
      <Card className="overflow-hidden">
        <CardHeader title="How each squad shapes up" subtitle={`Averaged over ${trials} simulated auctions`} />
        <div className="overflow-auto">
          <table className="w-full border-collapse">
            <thead>
              <tr>
                <th className="th">Team</th>
                <th className="th">Personality</th>
                <th className="th text-right">Avg spend</th>
                <th className="th text-right">Avg value</th>
                <th className="th text-right">Squad</th>
                <th className="th text-right">Overseas</th>
              </tr>
            </thead>
            <tbody>
              {[...result.teams].sort((a, b) => b.avgValue - a.avgValue).map((t) => (
                <tr key={t.team} className="hover:bg-surface/50">
                  <td className="td font-bold text-fg">{t.team}</td>
                  <td className="td"><Badge tone="accent">{t.personality}</Badge></td>
                  <td className="td stat-num text-right">{fmt(t.avgSpend, 1)} cr</td>
                  <td className="td stat-num text-right text-accent-glow">{fmt(t.avgValue, 1)}</td>
                  <td className="td stat-num text-right">{fmt(t.avgSize, 1)}</td>
                  <td className="td stat-num text-right">{fmt(t.avgOverseas, 1)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      {/* marquee battles */}
      <Card className="overflow-hidden">
        <CardHeader title="Who lands the marquee names" subtitle="Win share across the simulated auctions" />
        <div className="overflow-auto" style={{ maxHeight: "50vh" }}>
          <table className="w-full border-collapse">
            <thead>
              <tr>
                <th className="th">Player</th>
                <th className="th">Role</th>
                <th className="th text-right">Value</th>
                <th className="th">Most likely landing spot</th>
              </tr>
            </thead>
            <tbody>
              {result.marquee.map(({ player, winners }) => (
                <tr key={player.cricsheet_id} className="hover:bg-surface/50">
                  <td className="td cursor-pointer font-medium text-fg hover:text-accent-glow" onClick={() => navigate(`/player?cid=${player.cricsheet_id}`)}>{player.name}</td>
                  <td className="td"><Badge tone={ROLE_TONE[player.role]}>{player.role.replace("_", "-")}</Badge></td>
                  <td className="td stat-num text-right">{fmt(player.projected_value, 1)}</td>
                  <td className="td">
                    <span className="flex flex-wrap gap-1.5">
                      {winners.length === 0 ? <span className="text-xs text-muted">unsold</span> : winners.map((w) => (
                        <span key={w.team} className="inline-flex items-center gap-1 rounded-md border border-border bg-surface px-1.5 py-0.5 text-xs">
                          <span className="font-semibold text-fg">{w.team}</span>
                          <span className="text-muted">{w.pct.toFixed(0)}%</span>
                        </span>
                      ))}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      {/* a sample draft */}
      {draft && (
        <Card className="overflow-hidden">
          <CardHeader
            title="A representative draft"
            subtitle="One sampled auction — pick a team to see the squad it walked away with"
            right={
              <select value={focus} onChange={(e) => setFocus(Number(e.target.value))} className="input w-auto cursor-pointer py-1 text-xs">
                {result.sampleDraft.map((d, i) => (
                  <option key={d.team} value={i} className="bg-card">{d.team}</option>
                ))}
              </select>
            }
          />
          <div className="flex flex-wrap gap-2 p-4">
            {draft.squad.length === 0 ? (
              <span className="text-sm text-muted">No buys in this sample.</span>
            ) : (
              draft.squad.map((p) => (
                <button key={p.cricsheet_id} onClick={() => navigate(`/player?cid=${p.cricsheet_id}`)}
                  className="inline-flex items-center gap-1.5 rounded-md border border-border bg-surface px-2 py-1 text-xs hover:border-accent/40">
                  <span className="text-fg">{p.name}</span>
                  <Badge tone={ROLE_TONE[p.role]}>{p.role.replace("_", "-")}</Badge>
                  {p.is_overseas && <Plane className="h-3 w-3 text-willow" />}
                </button>
              ))
            )}
          </div>
          <div className="border-t border-border px-4 py-2 text-xs text-muted">
            Spend {fmt(draft.spend, 1)} cr · {draft.squad.length} players · {draft.overseas} overseas
          </div>
        </Card>
      )}
    </div>
  );
}
