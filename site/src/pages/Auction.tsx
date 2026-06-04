import { useEffect, useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { Gavel, Dices, Plane, Calculator, X, Users } from "lucide-react";
import { useAsync } from "@/lib/useAsync";
import { getAuctionPool, getRetentions } from "@/lib/data";
import {
  buildPool,
  simulateAuction,
  defaultRetentions,
  ARCHETYPES,
  IPL_TEAMS_DEFAULT,
  type PoolPlayer,
  type SimResult,
  type AuctionMode,
} from "@/lib/auction";
import { PageTitle, Card, CardHeader, Spinner, Badge, Empty, InfoTip, Collapsible } from "@/components/ui";
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
            Part 1 · Skill → crore price
          </div>
          <div className="space-y-3">
            <Step n={1} title="Amplify skill exponentially">
              Skill is a compressed number (avg 0, stars ~+0.5). Exponentiate and scale so the spread
              matches real money — top players land ~27 cr, the median ~3–4 cr. All-rounders/keepers get
              a small scarcity premium.
            </Step>
            <Step n={2} title="Decay for staleness">
              A player who's barely featured lately (last game years ago) is worth less now — value
              decays with time since their last match (a few months' grace, then ramps). Keeps
              has-beens out of the top buys.
            </Step>
            <Step n={3} title="Base price">
              The opening tag, snapped to IPL bands (0.3 / 0.5 / 0.75 / 1 / 1.5 / 2 cr). Bidding pushes
              the final price up from there.
            </Step>
          </div>
          <Code>{`"Player X", skill +0.25:
  1.6 × e^(5.8 × 0.25)        ≈ 6.5 cr   ← projected value
  (− recency penalty if stale)
  opening tag                 = 0.75 cr  ← base price`}</Code>
        </div>

        <div>
          <div className="mb-2 text-xs font-bold uppercase tracking-wider text-accent">
            Part 2 · Who's in the pool
          </div>
          <p className="text-sm leading-relaxed text-muted">
            The whole active T20 world an IPL auction draws from — not just IPL:
          </p>
          <ul className="mt-2 space-y-1 text-sm text-muted">
            <li>• <b className="text-fg">IPL players</b> — retainable, carry their current franchise.</li>
            <li>• <b className="text-fg">Free agents</b> — overseas via the <b>BBL</b>, <b>SA20</b> &amp; <b>CPL</b>, uncapped Indians via <b>SMAT</b>.</li>
            <li>• Active only (last ~3 years), ≥150 balls (cuts tiny-sample flukes).</li>
            <li>• Excludes men's-T20I associate noise + non-IPL nations (PAK).</li>
          </ul>
          <p className="mt-2 text-sm leading-relaxed text-muted">
            Value isn't comparable across tiers (runs vs weak attacks ≠ vs IPL), so lower tiers are
            penalised (BBL/SA20 −0.07, CPL −0.10, SMAT −0.20) before pricing.
          </p>
        </div>

        <div>
          <div className="mb-2 text-xs font-bold uppercase tracking-wider text-accent">
            Part 3 · Retentions, then the auction
          </div>
          <p className="mb-2 text-sm leading-relaxed text-muted">
            First, <b>retentions</b> (editable per team): <b>Mega</b> = the real 2025 lists (~5 each,
            drawn from the 120 cr purse via slabs); <b>Mini</b> = keep most of the squad (already
            paid-for — teams bid a small leftover purse). Retained players leave the pool and count
            toward the overseas cap. Everyone else goes under the hammer.
          </p>
          <p className="text-sm leading-relaxed text-muted">
            Then players go up one at a time, stars first. Each team sets a <b>max bid</b>:
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
            Two passes so the pool is shared fairly: every team first fills to a <b>20-man minimum</b>,
            then tops up toward the <b>25 cap</b>. That's one mock auction. Run it ~300 times (reshuffled
            slightly) and average → each team's typical spend &amp; squad, and each star's win-share
            ("Bumrah → MI 62%, CSK 21%" = your odds in a bidding war).
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
  // ?draft=<cricsheet_id> arrives from the Scout room ("draft this prospect").
  const [params] = useSearchParams();
  const draftId = params.get("draft");
  // Auction is IPL-only — the ten franchises + retentions are IPL concepts.
  // Uses the big auction_pool (every active rated player), not players.json.
  const poolData = useAsync(() => getAuctionPool("ipl"), []);
  const retentions = useAsync(() => getRetentions("ipl"), []);

  const pool = useMemo<PoolPlayer[]>(
    () => (poolData.data ? buildPool(poolData.data) : []),
    [poolData.data],
  );

  // real 2025 retention ids + prices per team, from retentions.json
  const { megaIds, realPrices } = useMemo(() => {
    const ids: Record<string, string[]> = {};
    const prices: Record<string, number> = {};
    const mega = retentions.data?.mega ?? {};
    for (const [team, rows] of Object.entries(mega)) {
      ids[team] = rows.map((r) => r.cricsheet_id);
      for (const r of rows) prices[r.cricsheet_id] = r.price;
    }
    return { megaIds: ids, realPrices: prices };
  }, [retentions.data]);

  return (
    <>
      <PageTitle
        title="Auction room"
        icon={<Gavel className="h-6 w-6" />}
        desc="Simulate the real IPL auction over ACTIVE players. Each franchise first RETAINS its core (Mega = ~5 keepers, the real 2025 lists; Mini = keep most of the squad) — editable below — then the ten teams bid for everyone else by their own personality, hundreds of times, so you see who lands each remaining star and how each squad shapes up."
      />

      {/* what is this for */}
      <Card className="mb-5 px-5 py-4 text-sm leading-relaxed text-muted">
        <span className="font-semibold text-fg">What it's for: </span>
        Player values + estimated crore prices come from the Bayesian skill model (calibrated to recent
        auction prices), over <b>active</b> players only. Pick <b>Mega</b> or <b>Mini</b>, tweak any
        team's <b>retentions</b>, then run — each of the ten franchises bids for the un-retained pool by
        its personality (marquee-chaser, value-hunter…), repeated hundreds of times, showing who likely
        lands each remaining star and how every squad ends up.
      </Card>

      <AuctionMath />

      {poolData.loading || retentions.loading ? (
        <Spinner label="Pricing the pool…" />
      ) : pool.length === 0 ? (
        <Empty>No rated IPL pool available.</Empty>
      ) : (
        <Simulate pool={pool} megaIds={megaIds} realPrices={realPrices} draftId={draftId} navigate={navigate} />
      )}
    </>
  );
}

const MODE_BLURB: Record<AuctionMode, string> = {
  mega: "Mega auction — each franchise retains only ~5 core players; almost everyone else is up for grabs.",
  mini: "Mini auction — franchises keep most of their squad; only a handful of slots are auctioned.",
};

function Simulate({
  pool,
  megaIds,
  realPrices,
  draftId,
  navigate,
}: {
  pool: PoolPlayer[];
  megaIds: Record<string, string[]>;
  realPrices: Record<string, number>;
  draftId: string | null;
  navigate: (p: string) => void;
}) {
  const [teams, setTeams] = useState(IPL_TEAMS_DEFAULT);
  const [mode, setSimMode] = useState<AuctionMode>("mega");
  const [purse, setPurse] = useState(120);
  const [squadSize, setSquadSize] = useState(25);
  const [overseasCap, setOverseasCap] = useState(8);
  const [trials, setTrials] = useState(300);
  const [focus, setFocus] = useState(0);
  const [q, setQ] = useState(""); // player-lookup search
  const [result, setResult] = useState<SimResult | null>(null);
  const [running, setRunning] = useState(false);
  // a player drafted in from the Scout room (?draft=), and which team keeps him
  const [draftCid, setDraftCid] = useState<string | null>(draftId);
  const [draftTeam, setDraftTeam] = useState(IPL_TEAMS_DEFAULT[0].team);
  const draftPlayer = draftCid ? pool.find((p) => p.cricsheet_id === draftCid) : null;
  // editable retentions per team — reset to the mode's default when mode/pool changes
  const [retentions, setRetentions] = useState<Record<string, string[]>>({});
  useEffect(() => {
    const base = defaultRetentions(pool, teams, mode, megaIds);
    // Inject a Scout-drafted prospect as an extra retention for the chosen team.
    if (draftCid && pool.some((p) => p.cricsheet_id === draftCid)) {
      const cur = base[draftTeam] ?? [];
      if (!cur.includes(draftCid)) base[draftTeam] = [...cur, draftCid];
    }
    setRetentions(base);
    // Mega = full 120cr purse (retentions drawn from it). Mini = the squad is
    // already paid for; teams bid from a small leftover purse.
    setPurse(mode === "mega" ? 120 : 30);
    setResult(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode, pool, megaIds, draftCid, draftTeam]);

  // roster per team (active players on that team), best-value first, for the editor
  const rosters = useMemo(() => {
    const m: Record<string, PoolPlayer[]> = {};
    for (const t of teams) m[t.team] = pool.filter((p) => p.team === t.team).sort((a, b) => b.value - a.value);
    return m;
  }, [pool, teams]);
  const byId = useMemo(() => new Map(pool.map((p) => [p.cricsheet_id, p])), [pool]);

  // Mega: retention cost (real price or slab). Mini: carried over, free.
  const retCost = (cid: string, i: number) =>
    mode === "mini" ? 0 : (realPrices[cid] ?? [18, 14, 11, 18, 14][i] ?? 4);

  function run() {
    setRunning(true);
    setTimeout(() => {
      setResult(
        simulateAuction(pool, teams, { purse, squadSize, overseasCap, trials, mode, retentions, realPrices }),
      );
      setRunning(false);
    }, 20);
  }

  const draft = result?.sampleDraft[focus];

  return (
    <div className="space-y-5">
      {/* drafted-from-Scout banner */}
      {draftCid &&
        (draftPlayer ? (
          <Card className="flex flex-wrap items-center gap-2 border-accent/40 bg-accent/5 px-4 py-3 text-sm">
            <Gavel className="h-4 w-4 shrink-0 text-accent" />
            <span className="text-muted">
              Drafted <b className="text-fg">{draftPlayer.name}</b> from Scout — locked as a retention for
            </span>
            <select
              value={draftTeam}
              onChange={(e) => setDraftTeam(e.target.value)}
              className="input w-auto cursor-pointer py-1 text-xs"
            >
              {teams.map((t) => (
                <option key={t.team} value={t.team} className="bg-card">{t.team}</option>
              ))}
            </select>
            <button onClick={() => setDraftCid(null)} className="ml-auto inline-flex items-center gap-1 text-xs text-muted hover:text-ball">
              <X className="h-3 w-3" /> release
            </button>
          </Card>
        ) : (
          <Card className="flex flex-wrap items-center gap-2 border-ball/30 bg-ball/5 px-4 py-3 text-sm text-muted">
            That player isn't in the priced auction pool (too few balls, or a non-IPL nation), so he
            can't be drafted.
            <button onClick={() => setDraftCid(null)} className="ml-auto inline-flex items-center gap-1 text-xs hover:text-ball">
              <X className="h-3 w-3" /> dismiss
            </button>
          </Card>
        ))}

      {/* mode */}
      <Card className="p-5">
        <div className="mb-3 flex flex-wrap items-center gap-2 text-sm font-semibold text-fg">
          Auction type
          <InfoTip title="Mega vs Mini">
            <div className="space-y-1.5">
              <div><b className="text-fg">Mega</b>: {MODE_BLURB.mega} Defaults to the <b>real 2025 retention lists</b>.</div>
              <div><b className="text-fg">Mini</b>: {MODE_BLURB.mini} Defaults to each team's top 18 by value (squad already paid for — they bid a small leftover purse).</div>
              <div className="text-muted/80">Retentions are <b>editable</b> below — they lock those players and draw their cost from the purse before bidding.</div>
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
        {/* editable retentions */}
        <div className="mb-2 mt-5 flex items-center gap-2 text-sm font-semibold text-fg">
          <Users className="h-4 w-4 text-accent" /> Retentions
          <span className="text-xs font-normal text-muted">— click ✕ to release, or add from the roster; purse drops by each cost</span>
        </div>
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
          {teams.map((t) => {
            const ids = retentions[t.team] ?? [];
            const cost = ids.reduce((s, cid, i) => s + retCost(cid, i), 0);
            const overs = ids.filter((cid) => byId.get(cid)?.is_overseas).length;
            const addable = (rosters[t.team] ?? []).filter((p) => !ids.includes(p.cricsheet_id));
            return (
              <div key={t.team} className="rounded-lg border border-border bg-surface/50 p-2.5">
                <div className="mb-1.5 flex items-baseline justify-between">
                  <span className="text-xs font-bold text-fg">{t.team}</span>
                  <span className="stat-num text-[11px] text-muted">{ids.length} · {fmt(cost, 0)}cr · {overs} o/s</span>
                </div>
                <div className="flex flex-wrap gap-1">
                  {ids.length === 0 && <span className="text-[11px] text-muted">none</span>}
                  {ids.map((cid, i) => {
                    const p = byId.get(cid);
                    if (!p) return null;
                    return (
                      <span key={cid} className="inline-flex items-center gap-1 rounded-md border border-accent/30 bg-accent/10 px-1.5 py-0.5 text-[11px] text-accent-glow">
                        {p.name}<span className="text-muted/70">{fmt(retCost(cid, i), 0)}</span>
                        <button onClick={() => { setRetentions((r) => ({ ...r, [t.team]: (r[t.team] ?? []).filter((x) => x !== cid) })); setResult(null); }} className="hover:text-ball"><X className="h-3 w-3" /></button>
                      </span>
                    );
                  })}
                </div>
                <select
                  value=""
                  onChange={(e) => { if (e.target.value) { setRetentions((r) => ({ ...r, [t.team]: [...(r[t.team] ?? []), e.target.value] })); setResult(null); } }}
                  className="input mt-1.5 w-full cursor-pointer py-1 text-[11px]"
                >
                  <option value="" className="bg-card">+ add player…</option>
                  {addable.map((p) => (
                    <option key={p.cricsheet_id} value={p.cricsheet_id} className="bg-card">{p.name} ({fmt(p.projected_value, 0)}cr)</option>
                  ))}
                </select>
              </div>
            );
          })}
        </div>

        <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
          <NumberField label="Purse / team" value={purse} onChange={setPurse} min={10} max={500} step={5} suffix="cr" />
          <NumberField label="Squad cap" value={squadSize} onChange={setSquadSize} min={20} max={25} />
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
                  <td className="td stat-num text-right">{Math.round(t.avgBought)}</td>
                  <td className="td stat-num text-right">{fmt(t.avgSpend, 1)} cr</td>
                  <td className="td stat-num text-right text-accent-glow">{fmt(t.avgValue, 1)}</td>
                  <td className="td stat-num text-right">{Math.round(t.avgOverseas)}</td>
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

      {/* player lookup — works for both mega & mini */}
      <Card className="overflow-hidden">
        <CardHeader title="Find a player" subtitle="Where did anyone land, for how much, or did they go unsold?" />
        <div className="p-3">
          <input
            className="input w-full max-w-sm"
            placeholder="Search a player…"
            value={q}
            onChange={(e) => setQ(e.target.value)}
          />
          {q.trim().length < 2 ? (
            <p className="mt-2 text-xs text-muted">
              Type 2+ letters — searches every retained, sold &amp; unsold player in this run.
            </p>
          ) : (
            (() => {
              const needle = q.trim().toLowerCase();
              const hits = result.outcomes.filter((o) => o.name.toLowerCase().includes(needle));
              if (hits.length === 0)
                return <p className="mt-3 text-sm text-muted">No player matches “{q}”.</p>;
              return (
                <div className="mt-3 overflow-auto" style={{ maxHeight: "45vh" }}>
                  <table className="w-full border-collapse">
                    <thead>
                      <tr>
                        <th className="th">Player</th>
                        <th className="th">Role</th>
                        <th className="th">Status</th>
                        <th className="th text-right">Avg price</th>
                        <th className="th text-right">Sold %</th>
                        <th className="th">Where</th>
                      </tr>
                    </thead>
                    <tbody>
                      {hits.slice(0, 40).map((o) => (
                        <tr key={o.cricsheet_id} className="hover:bg-surface/50">
                          <td className="td font-medium text-fg">{o.name}</td>
                          <td className="td"><Badge tone={ROLE_TONE[o.role]}>{o.role.replace("_", "-")}</Badge></td>
                          <td className="td">
                            {o.status === "retained" ? (
                              <Badge tone="willow">retained</Badge>
                            ) : o.status === "unsold" ? (
                              <Badge tone="ball">unsold</Badge>
                            ) : (
                              <Badge tone="accent">sold</Badge>
                            )}
                          </td>
                          <td className="td stat-num text-right">{o.status === "unsold" ? "—" : `${fmt(o.avgPrice, 1)} cr`}</td>
                          <td className="td stat-num text-right">{o.status === "sold" ? `${o.soldPct.toFixed(0)}%` : "—"}</td>
                          <td className="td">
                            {o.status === "retained" ? (
                              <span className="text-xs"><b className="text-fg">{o.team}</b> · retained</span>
                            ) : o.status === "unsold" ? (
                              <span className="text-xs text-muted">went unsold</span>
                            ) : (
                              <span className="flex flex-wrap gap-1.5">
                                {o.winners.map((w) => (
                                  <span key={w.team} className="inline-flex items-center gap-1 rounded-md border border-border bg-surface px-1.5 py-0.5 text-xs">
                                    <span className="font-semibold text-fg">{w.team}</span>
                                    <span className="text-muted">{w.pct.toFixed(0)}%</span>
                                  </span>
                                ))}
                              </span>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  {hits.length > 40 && (
                    <p className="mt-2 text-xs text-muted">{hits.length - 40} more — refine the search.</p>
                  )}
                </div>
              );
            })()
          )}
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
