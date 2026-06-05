import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { FlaskConical, Users, Gavel, Replace, Plane, Sprout } from "lucide-react";
import { useStore } from "@/lib/store";
import { useAsync } from "@/lib/useAsync";
import {
  getAuctionPool,
  getLeaderboard,
  getPlayers,
  getScoutIndex,
  type ScoutPlayer,
  type ScoutIndex,
} from "@/lib/data";
import { estValue } from "@/lib/auction";
import { bestXI, type BestXIPlayer } from "@/lib/bestxi";
import { analyzeSquad, type SquadPlayer } from "@/lib/squad";
import { replacementByNeed } from "@/lib/scout";
import { usePlayers } from "@/lib/usePlayers";
import { Combobox } from "@/components/Combobox";
import { DataTable, type Col } from "@/components/DataTable";
import { PageTitle, Card, CardHeader, Spinner, Empty, StatTile, Badge, InfoTip } from "@/components/ui";
import { cn, fmt } from "@/lib/utils";

type Row = Record<string, unknown>;
const ROLE_KEYS = ["batter", "bowler", "all_rounder", "keeper"] as const;
type RoleKey = (typeof ROLE_KEYS)[number];
const ROLE_LABEL: Record<string, string> = {
  batter: "Batters",
  bowler: "Bowlers",
  all_rounder: "All-rounders",
  keeper: "Keepers",
};
const REPL_TIERS: { key: keyof ScoutIndex; label: string; icon: React.ReactNode }[] = [
  { key: "smat", label: "SMAT", icon: <Sprout className="h-3.5 w-3.5 text-willow" /> },
  { key: "bbl", label: "BBL", icon: <Plane className="h-3.5 w-3.5 text-accent" /> },
  { key: "sa20", label: "SA20", icon: <Plane className="h-3.5 w-3.5 text-accent" /> },
  { key: "cpl", label: "CPL", icon: <Plane className="h-3.5 w-3.5 text-accent" /> },
  { key: "blast", label: "Blast", icon: <Plane className="h-3.5 w-3.5 text-accent" /> },
];

const XI_COLS: Col<Row>[] = [
  { key: "name", label: "Player", primary: false },
  { key: "role", label: "Role", primary: false, render: (r) => ROLE_LABEL[String(r.role)] ?? String(r.role) },
  {
    key: "overseas",
    label: "O/S",
    align: "right",
    sortable: false,
    render: (r) => (r.is_overseas ? <Badge tone="ball">O/S</Badge> : <span className="text-muted">—</span>),
  },
  { key: "ngi", label: "NGI", align: "right", digits: 2, primary: true },
  { key: "price", label: "Price (cr)", align: "right", digits: 1 },
];

export function TeamLab() {
  const { collection } = useStore();
  const navigate = useNavigate();
  const pool = useAsync(() => getAuctionPool(collection), [collection]);
  const ngi = useAsync(() => getLeaderboard(collection, "ngi", "all"), [collection]);
  const players = useAsync(() => getPlayers(collection), [collection]);

  // ---- Best XI controls -----------------------------------------------------
  const [budget, setBudget] = useState(100);
  const [overseasCap, setOverseasCap] = useState(4); // real IPL playing-XI rule
  const [roleMins, setRoleMins] = useState<Record<RoleKey, number>>({
    batter: 3,
    bowler: 3,
    all_rounder: 1,
    keeper: 1,
  });

  const ngiByCid = useMemo(() => {
    const m = new Map<string, number>();
    for (const r of ngi.data ?? []) {
      const cid = r.cricsheet_id;
      const v = Number(r.ngi_total);
      if (typeof cid === "string" && Number.isFinite(v)) m.set(cid, v);
    }
    return m;
  }, [ngi.data]);

  const posByCid = useMemo(() => {
    const m = new Map<string, string | null>();
    for (const p of players.data ?? []) m.set(p.cricsheet_id, p.batting_position);
    return m;
  }, [players.data]);

  const xiPlayers: BestXIPlayer[] = useMemo(() => {
    if (!pool.data) return [];
    return pool.data
      .filter((r) => ngiByCid.has(r.cricsheet_id))
      .map((r) => ({
        cricsheet_id: r.cricsheet_id,
        name: r.name,
        role: r.role,
        is_overseas: r.is_overseas,
        ngi: ngiByCid.get(r.cricsheet_id)!,
        price: estValue(r.value, r.role, "ipl"),
      }));
  }, [pool.data, ngiByCid]);

  const xi = useMemo(
    () => bestXI(xiPlayers, budget, overseasCap, roleMins, 11, 40),
    [xiPlayers, budget, overseasCap, roleMins],
  );

  const squad = useMemo(() => {
    if (!xi.feasible) return null;
    const rows: SquadPlayer[] = xi.players.map((p) => ({
      role: p.role,
      is_overseas: p.is_overseas,
      batting_position: posByCid.get(p.cricsheet_id) ?? null,
    }));
    return analyzeSquad(rows, roleMins, overseasCap);
  }, [xi, posByCid, roleMins, overseasCap]);

  // ---- Replacement-by-need --------------------------------------------------
  const idx = useAsync<ScoutIndex>(() => getScoutIndex(collection), [collection]);
  const { options } = usePlayers(collection);
  const [replCid, setReplCid] = useState<string | null>(null);
  const iplById = useMemo(() => {
    const m = new Map<string, ScoutPlayer>();
    for (const p of idx.data?.ipl ?? []) m.set(p.cricsheet_id, p);
    return m;
  }, [idx.data]);
  const replOptions = useMemo(() => options.filter((o) => iplById.has(o.value)), [options, iplById]);
  const replSel = replCid ? iplById.get(replCid) : null;
  const replPrice = replSel ? estValue(replSel.value, replSel.role, "ipl") : null;

  const replacements = useMemo(() => {
    if (!replSel || !idx.data) return [];
    const out: (ScoutPlayer & { sim: number; est_cr: number; saving: number; tier: string })[] = [];
    for (const t of REPL_TIERS) {
      for (const r of replacementByNeed(replSel, idx.data[t.key], t.key)) {
        out.push({ ...r, tier: t.label });
      }
    }
    out.sort((a, b) => b.saving - a.saving || b.sim - a.sim);
    return out.slice(0, 12);
  }, [replSel, idx.data]);

  const baseLoading = pool.loading || ngi.loading || players.loading;
  const baseError = pool.error || ngi.error || players.error;

  return (
    <>
      <PageTitle
        title="Team Lab"
        icon={<FlaskConical className="h-6 w-6" />}
        desc="Build the optimal playing XI under a budget and overseas cap (exact knapsack on Net Game Impact), check the squad's balance, and find cheaper same-mould replacements for any player."
      />

      {/* ============================ Best XI ============================ */}
      <Card className="mb-5">
        <CardHeader
          title={
            <span className="flex items-center gap-2">
              <Gavel className="h-4 w-4 text-accent" /> Optimal XI builder
            </span>
          }
          subtitle="Maximise total NGI subject to budget, overseas cap and per-role minimums"
          right={
            <InfoTip title="How the XI is picked">
              Exact branch-and-bound (knapsack) over the top candidates per role. It maximises total
              Net Game Impact while keeping spend ≤ budget, overseas ≤ cap, and each role at/above its
              minimum. The same engine runs identically on the desktop apps.
            </InfoTip>
          }
        />
        <div className="flex flex-wrap items-end gap-5 p-4">
          <label className="flex flex-col gap-1 text-xs text-muted">
            <span>Budget: <b className="text-fg">{budget} cr</b></span>
            <input
              type="range"
              min={20}
              max={200}
              step={5}
              value={budget}
              onChange={(e) => setBudget(Number(e.target.value))}
              className="w-44 cursor-pointer accent-[#34d399]"
            />
          </label>
          <label className="flex flex-col gap-1 text-xs text-muted">
            <span>Overseas cap: <b className="text-fg">{overseasCap}</b></span>
            <input
              type="range"
              min={0}
              max={11}
              value={overseasCap}
              onChange={(e) => setOverseasCap(Number(e.target.value))}
              className="w-32 cursor-pointer accent-[#34d399]"
            />
          </label>
          {ROLE_KEYS.map((rk) => (
            <label key={rk} className="flex flex-col gap-1 text-xs text-muted">
              <span>Min {ROLE_LABEL[rk].toLowerCase()}</span>
              <input
                type="number"
                min={0}
                max={11}
                value={roleMins[rk]}
                onChange={(e) =>
                  setRoleMins((m) => ({ ...m, [rk]: Math.max(0, Number(e.target.value)) }))
                }
                className="input w-16 py-1.5"
              />
            </label>
          ))}
        </div>

        {baseLoading ? (
          <Spinner />
        ) : baseError ? (
          <div className="px-4 pb-4 text-sm text-ball">Couldn't load the player pool.</div>
        ) : !xi.feasible ? (
          <div className="px-4 pb-5 text-sm text-ball">
            No valid XI under these constraints — raise the budget/overseas cap or lower the role
            minimums (they must sum to ≤ 11).
          </div>
        ) : (
          <div className="space-y-4 px-4 pb-5">
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              <StatTile label="Total NGI" value={fmt(xi.total_ngi, 2)} />
              <StatTile label="Total spend" value={`${fmt(xi.total_price, 1)} cr`} hint={`of ${budget} cr`} />
              <StatTile label="Overseas" value={`${xi.overseas} / ${overseasCap}`} />
              <StatTile label="Players" value={String(xi.players.length)} />
            </div>
            <DataTable
              rows={xi.players as unknown as Row[]}
              cols={XI_COLS}
              rankCol={false}
              initialSort={{ key: "ngi", dir: "desc" }}
              onRowClick={(r) => navigate(`/player?cid=${String(r.cricsheet_id)}`)}
            />
          </div>
        )}
      </Card>

      {/* ========================= Squad balance ========================= */}
      {squad && (
        <Card className="mb-5">
          <CardHeader
            title={
              <span className="flex items-center gap-2">
                <Users className="h-4 w-4 text-accent" /> Squad balance
              </span>
            }
            subtitle="Role mix, batting-slot coverage and gaps for the XI above"
            right={
              squad.balanced ? (
                <Badge tone="willow">balanced</Badge>
              ) : (
                <Badge tone="ball">{squad.gaps.length} gap{squad.gaps.length === 1 ? "" : "s"}</Badge>
              )
            }
          />
          <div className="space-y-4 p-4">
            <div className="flex flex-wrap gap-2">
              {ROLE_KEYS.map((rk) => (
                <Badge key={rk} tone="muted">
                  {ROLE_LABEL[rk]}: {squad.roles[rk] ?? 0}
                </Badge>
              ))}
              <Badge tone="muted">Overseas: {squad.overseas}/{squad.overseas_cap}</Badge>
            </div>
            {Object.keys(squad.slots).length > 0 && (
              <div className="flex flex-wrap gap-2">
                {Object.entries(squad.slots).map(([s, n]) => (
                  <Badge key={s} tone="accent">{s}: {n}</Badge>
                ))}
              </div>
            )}
            {squad.gaps.length > 0 ? (
              <ul className="space-y-1 text-sm text-ball">
                {squad.gaps.map((g) => (
                  <li key={g}>• {g}</li>
                ))}
              </ul>
            ) : (
              <p className="text-sm text-willow">Meets every role minimum, the overseas cap and slot coverage.</p>
            )}
          </div>
        </Card>
      )}

      {/* ====================== Replacement by need ====================== */}
      <Card>
        <CardHeader
          title={
            <span className="flex items-center gap-2">
              <Replace className="h-4 w-4 text-accent" /> Replacement by need
            </span>
          }
          subtitle="Cheaper players of the same mould (role / seam-spin / slot) — the budget-swap case"
        />
        <div className="p-4">
          <Combobox
            options={replOptions}
            value={replCid}
            onChange={setReplCid}
            placeholder={idx.loading ? "Loading…" : "Search an IPL player to replace…"}
            className="mb-4 max-w-md"
          />
          {!replSel ? (
            <Empty>Pick an IPL player to find cheaper same-mould replacements.</Empty>
          ) : replacements.length === 0 ? (
            <Empty>No cheaper same-mould option found across the scouted leagues.</Empty>
          ) : (
            <div className="space-y-1.5">
              <div className="mb-2 text-xs text-muted">
                Replacing <b className="text-fg">{replSel.name}</b>
                {replPrice != null && <> (≈{fmt(replPrice, 1)}cr) </>} — cheaper options, biggest saving first:
              </div>
              {replacements.map((r) => (
                <div
                  key={`${r.tier}:${r.cricsheet_id}`}
                  className="flex flex-wrap items-center gap-x-2.5 gap-y-1 rounded-md px-3 py-2 text-sm hover:bg-surface"
                >
                  <span className="font-medium text-fg">{r.name}</span>
                  <span className="inline-flex items-center gap-1 text-[11px] text-muted">
                    {REPL_TIERS.find((t) => t.label === r.tier)?.icon}
                    {r.tier}
                  </span>
                  {r.country && <span className="text-[11px] text-muted">{r.country}</span>}
                  <Badge tone={r.sim > 0.8 ? "accent" : r.sim > 0.6 ? "willow" : "muted"}>
                    {Math.round(r.sim * 100)}%
                  </Badge>
                  <span className="stat-num ml-auto text-[11px] text-muted">≈{fmt(r.est_cr, 1)}cr</span>
                  {r.saving > 0 && (
                    <span className="stat-num text-[11px] text-willow">save {fmt(r.saving, 1)}</span>
                  )}
                  <button
                    onClick={() => navigate(`/auction?draft=${r.cricsheet_id}`)}
                    title="Draft into the Auction room"
                    className={cn(
                      "inline-flex shrink-0 items-center gap-1 rounded-md border border-accent/30",
                      "bg-accent/10 px-1.5 py-0.5 text-[11px] text-accent-glow hover:border-accent/50",
                    )}
                  >
                    <Gavel className="h-3 w-3" /> Draft
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>
      </Card>
    </>
  );
}
