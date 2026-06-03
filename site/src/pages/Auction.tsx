import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Gavel, Wallet, Users, CheckCircle2, AlertTriangle, Dices, Plane, Calculator } from "lucide-react";
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
  type SimResult,
  type AuctionMode,
} from "@/lib/auction";
import { PageTitle, Card, CardHeader, Spinner, Badge, StatTile, Empty, InfoTip, Collapsible } from "@/components/ui";
import { cn, fmt } from "@/lib/utils";

function Step({ n, title, children }: { n: number; title: string; children: React.ReactNode }) {
  return (
    <div className="flex gap-3">
      <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full border border-accent/30 bg-accent/10 text-xs font-bold text-accent-glow">
        {n}
      </span>
      <div className="min-w-0">
        <div className="text-sm font-semibold text-fg">{title}</div>
        <div className="mt-1 text-sm leading-relaxed text-muted">{children}</div>
      </div>
    </div>
  );
}

function Code({ children }: { children: React.ReactNode }) {
  return (
    <pre className="mt-2 overflow-auto rounded-lg border border-border bg-bg/60 px-3 py-2 font-mono text-xs leading-relaxed text-fg">
      {children}
    </pre>
  );
}

function AuctionMath() {
  return (
    <Collapsible title="How the auction math works (plain English)" icon={<Calculator className="h-4 w-4" />}>
      <div className="space-y-6">
        <p className="text-sm leading-relaxed text-muted">
          The data only knows how <b>good</b> a player is (a skill rating) — never what he{" "}
          <b>costs</b>. So step zero is inventing a fair price from skill, then everything builds on
          that.
        </p>

        <div>
          <div className="mb-2 text-xs font-bold uppercase tracking-wider text-accent">
            Part 1 · Skill → price tag
          </div>
          <div className="space-y-3">
            <Step n={1} title="Make skill multiply (e^skill)">
              Skill is a small number (avg 0, stars positive). Exponentiate so it scales like a market:
              skill 0 → ×1.00, +0.3 → ×1.35, −0.3 → ×0.74.
            </Step>
            <Step n={2} title="Scale to crore">
              Multiply by a role weight (all-rounders rarer → higher) and a constant, so the best land
              ~10–12 cr. Out comes <b>projected value</b> (worth) and a <b>base price</b> snapped to IPL
              bands (0.3 / 0.5 / 0.75 / 1 / 1.5 / 2 cr).
            </Step>
            <Step n={3} title="Value per credit = value ÷ base price">
              Quality per rupee. High = bargain. This is what the optimiser ranks by.
            </Step>
          </div>
          <Code>{`"Player X", skill +0.25:
  e^0.25                = 1.28
  × 0.5 (batter) × 4    = 2.56 cr   ← projected value
  opening tag           = 0.50 cr   ← base price
  value per credit = 2.56 / 0.50 = 5.1   (cheap & good)`}</Code>
        </div>

        <div>
          <div className="mb-2 text-xs font-bold uppercase tracking-wider text-accent">
            Part 2 · Build my squad (you, shopping smart)
          </div>
          <p className="text-sm leading-relaxed text-muted">
            A "fill a cart on a budget" problem (a knapsack) with extra rules: squad size, overseas
            cap, minimum players per role. The greedy strategy:
          </p>
          <div className="mt-3 space-y-3">
            <Step n={1} title="Cover the minimums first">
              For each role, buy the highest value-per-credit players until its minimum is met — skipping
              anyone you can't afford or who'd break the overseas cap.
            </Step>
            <Step n={2} title="Spend the rest on best value">
              Fill the leftover slots with the best value-per-credit players regardless of role, until
              the squad is full or money runs out.
            </Step>
          </div>
          <p className="mt-3 text-sm leading-relaxed text-muted">
            When cash is the bottleneck, "most quality per rupee" is the right ranking — near-optimal and
            instant. Lower the overseas cap → it swaps imports for the next-best Indians.
          </p>
        </div>

        <div>
          <div className="mb-2 text-xs font-bold uppercase tracking-wider text-accent">
            Part 3 · Simulate the auction (the whole room, many times)
          </div>
          <p className="mb-2 text-sm leading-relaxed text-muted">
            First, <b>retentions</b>: each franchise keeps its top players (by value) from its current
            Cricsheet roster — <b>Mega</b> keeps ~5, <b>Mini</b> keeps most of the squad. Retained
            players leave the pool and draw their cost from the purse (and count toward the overseas
            cap). Only the rest goes under the hammer — and only <b>active</b> players.
          </p>
          <p className="text-sm leading-relaxed text-muted">
            Then the remaining players go up one at a time, stars first. Each team sets a <b>max bid</b>:
          </p>
          <Code>{`max bid = value × aggression × need × overseas-bias × luck`}</Code>
          <ul className="mt-2 space-y-1 text-sm text-muted">
            <li>• <b className="text-fg">aggression</b> — team style (MarqueeChaser 1.35 splurges, ValueHunter 0.85 holds back)</li>
            <li>• <b className="text-fg">need</b> — 1.5 if it still needs that role, else 0.7</li>
            <li>• <b className="text-fg">overseas-bias</b> — higher for imports if the team loves them; 1 for Indians</li>
            <li>• <b className="text-fg">luck</b> — small random nudge sized by the team's risk; makes runs differ</li>
            <li>• capped at the team's remaining money / squad / overseas slots</li>
          </ul>
          <p className="mt-3 text-sm leading-relaxed text-muted">
            Highest max bid wins — but pays just <b>above the second-highest bid</b> (like a real
            auction, you stop when everyone else drops).
          </p>
          <Code>{`Bidding for Player X (worth 10):
  MI  (MarqueeChaser, needs a batter): 10 × 1.35 × 1.5 × 1 = 20.3
  CSK (Balanced, batters full):        10 × 1.00 × 0.7 × 1 =  7.0
  → MI wins, pays ≈ 7.1 cr (just over CSK), not its full 20.3`}</Code>
          <p className="mt-3 text-sm leading-relaxed text-muted">
            That's one mock auction. Run it ~300 times (reshuffled slightly) and average → each team's
            typical spend & squad, and each star's win-share ("Bumrah → MI 62%, CSK 21%" = your odds in
            a bidding war).
          </p>
        </div>

        <p className="rounded-lg border border-willow/20 bg-willow/5 px-3 py-2 text-xs leading-relaxed text-muted">
          <b className="text-willow">Honest caveat:</b> prices are invented from skill, not real auction
          data — so this models auction <i>behaviour</i> and relative outcomes, it doesn't predict the
          actual crore amounts.
        </p>
      </div>
    </Collapsible>
  );
}

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
  const navigate = useNavigate();
  // Auction is IPL-only — the ten franchises + retentions are IPL concepts,
  // so it always uses IPL data regardless of the global collection.
  const { players } = usePlayers("ipl");
  const ratings = useAsync(() => getRatings("ipl"), []);
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
        desc="An IPL auction is a constrained optimisation under a fixed purse, squad size, role minimums and an overseas cap — over ACTIVE players only. Two tools: optimise YOUR squad from scratch, or simulate the real auction where each of the ten franchises first RETAINS its core (Mega = small retention, Mini = keep most of the squad) and then bids for the rest by its own personality."
      />

      {/* what is this for */}
      <Card className="mb-5 px-5 py-4 text-sm leading-relaxed text-muted">
        <span className="font-semibold text-fg">What it's for: </span>
        Values + estimated prices come from the Bayesian skill model, over <b>active</b> players only.{" "}
        <b>Build my squad</b> drafts the best value-per-credit squad your purse allows, from scratch.{" "}
        <b>Simulate the auction</b> first has each franchise <b>retain</b> its top core (by value, from
        its current Cricsheet roster) — <b>Mega</b> keeps ~5, <b>Mini</b> keeps most of the squad —
        then the ten teams bid for everyone else by personality, repeated hundreds of times, so you see
        who lands each remaining star and how each squad shapes up.
      </Card>

      <AuctionMath />

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
        <Empty>No rated IPL pool available.</Empty>
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

const MODE_BLURB: Record<AuctionMode, string> = {
  mega: "Mega auction — each franchise retains only ~5 core players; almost everyone else is up for grabs.",
  mini: "Mini auction — franchises keep most of their squad; only a handful of slots are auctioned.",
};

function Simulate({ pool, navigate }: { pool: PoolPlayer[]; navigate: (p: string) => void }) {
  const [teams, setTeams] = useState(IPL_TEAMS_DEFAULT);
  const [mode, setSimMode] = useState<AuctionMode>("mega");
  const [purse, setPurse] = useState(120);
  const [squadSize, setSquadSize] = useState(18);
  const [overseasCap, setOverseasCap] = useState(8);
  const [trials, setTrials] = useState(300);
  const [focus, setFocus] = useState(0);
  const [result, setResult] = useState<SimResult | null>(null);
  const [running, setRunning] = useState(false);

  function run() {
    setRunning(true);
    setTimeout(() => {
      setResult(simulateAuction(pool, teams, { purse, squadSize, overseasCap, trials, mode }));
      setRunning(false);
    }, 20);
  }

  const draft = result?.sampleDraft[focus];

  return (
    <div className="space-y-5">
      {/* mode */}
      <Card className="p-5">
        <div className="mb-3 flex flex-wrap items-center gap-2 text-sm font-semibold text-fg">
          Auction type
          <InfoTip title="Mega vs Mini">
            <div className="space-y-1.5">
              <div><b className="text-fg">Mega</b>: {MODE_BLURB.mega}</div>
              <div><b className="text-fg">Mini</b>: {MODE_BLURB.mini}</div>
              <div className="text-muted/80">Retentions = each team's top players by Bayesian value from its current Cricsheet roster; they're locked and draw down the purse before bidding starts.</div>
            </div>
          </InfoTip>
        </div>
        <div className="flex gap-2">
          {(["mega", "mini"] as const).map((m) => (
            <button
              key={m}
              onClick={() => setSimMode(m)}
              className={cn(
                "rounded-lg border px-4 py-2 text-sm font-medium transition-all",
                m === mode ? "border-accent/40 bg-accent/10 text-accent-glow shadow-glow" : "border-border bg-surface text-muted hover:text-fg",
              )}
            >
              {m === "mega" ? "Mega auction" : "Mini auction"}
            </button>
          ))}
        </div>
        <p className="mt-2 text-xs text-muted">{MODE_BLURB[mode]}</p>

        {/* team personalities */}
        <div className="mb-3 mt-5 flex items-center gap-2 text-sm font-semibold text-fg">
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
        <button onClick={run} disabled={running} className="btn btn-accent mt-4">
          <Dices className={cn("h-4 w-4", running && "animate-spin")} />
          {running ? "Simulating…" : result ? "Re-run simulation" : "Run simulation"}
        </button>
      </Card>

      {!result ? (
        <Empty>Pick the auction type &amp; personalities, then <b className="mx-1 text-accent-glow">Run simulation</b>.</Empty>
      ) : (
        <>
      {/* per-team outcomes */}
      <Card className="overflow-hidden">
        <CardHeader title="How each squad shapes up" subtitle={`${result.mode === "mega" ? "Mega" : "Mini"} auction · ${result.poolSize} players under the hammer · averaged over ${trials} runs`} />
        <div className="overflow-auto">
          <table className="w-full border-collapse">
            <thead>
              <tr>
                <th className="th">Team</th>
                <th className="th">Personality</th>
                <th className="th text-right">Retained</th>
                <th className="th text-right">Bought</th>
                <th className="th text-right">Auction spend</th>
                <th className="th text-right">Squad value</th>
                <th className="th text-right">Overseas</th>
              </tr>
            </thead>
            <tbody>
              {[...result.teams].sort((a, b) => b.avgValue - a.avgValue).map((t) => (
                <tr key={t.team} className="hover:bg-surface/50">
                  <td className="td font-bold text-fg">{t.team}</td>
                  <td className="td"><Badge tone="accent">{t.personality}</Badge></td>
                  <td className="td stat-num text-right text-muted">{t.retained}</td>
                  <td className="td stat-num text-right">{fmt(t.avgBought, 1)}</td>
                  <td className="td stat-num text-right">{fmt(t.avgSpend, 1)} cr</td>
                  <td className="td stat-num text-right text-accent-glow">{fmt(t.avgValue, 1)}</td>
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
            title="A representative squad"
            subtitle="One sampled auction — retained core (locked) + auction buys"
            right={
              <select value={focus} onChange={(e) => setFocus(Number(e.target.value))} className="input w-auto cursor-pointer py-1 text-xs">
                {result.sampleDraft.map((d, i) => (
                  <option key={d.team} value={i} className="bg-card">{d.team}</option>
                ))}
              </select>
            }
          />
          <div className="space-y-3 p-4">
            <div>
              <div className="mb-1.5 text-xs font-semibold uppercase tracking-wider text-muted">Retained ({draft.retained.length})</div>
              <div className="flex flex-wrap gap-2">
                {draft.retained.length === 0 ? <span className="text-xs text-muted">none</span> : draft.retained.map((p) => (
                  <button key={p.cricsheet_id} onClick={() => navigate(`/player?cid=${p.cricsheet_id}`)}
                    className="inline-flex items-center gap-1.5 rounded-md border border-accent/30 bg-accent/10 px-2 py-1 text-xs hover:border-accent/50">
                    <span className="text-accent-glow">{p.name}</span>
                    <Badge tone={ROLE_TONE[p.role]}>{p.role.replace("_", "-")}</Badge>
                    {p.is_overseas && <Plane className="h-3 w-3 text-willow" />}
                  </button>
                ))}
              </div>
            </div>
            <div>
              <div className="mb-1.5 text-xs font-semibold uppercase tracking-wider text-muted">Bought ({draft.bought.length})</div>
              <div className="flex flex-wrap gap-2">
                {draft.bought.length === 0 ? <span className="text-xs text-muted">no buys in this sample</span> : draft.bought.map((p) => (
                  <button key={p.cricsheet_id} onClick={() => navigate(`/player?cid=${p.cricsheet_id}`)}
                    className="inline-flex items-center gap-1.5 rounded-md border border-border bg-surface px-2 py-1 text-xs hover:border-accent/40">
                    <span className="text-fg">{p.name}</span>
                    <Badge tone={ROLE_TONE[p.role]}>{p.role.replace("_", "-")}</Badge>
                    {p.is_overseas && <Plane className="h-3 w-3 text-willow" />}
                  </button>
                ))}
              </div>
            </div>
          </div>
          <div className="border-t border-border px-4 py-2 text-xs text-muted">
            {draft.retained.length + draft.bought.length} total · {draft.overseas} overseas · auction spend {fmt(draft.spent, 1)} cr
          </div>
        </Card>
      )}
        </>
      )}
    </div>
  );
}
