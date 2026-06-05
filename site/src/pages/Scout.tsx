import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Network, Users, Sprout, Plane, Gem, Gavel } from "lucide-react";
import { usePlayers } from "@/lib/usePlayers";
import { useAsync } from "@/lib/useAsync";
import { getScoutIndex, type ScoutPlayer, type ScoutIndex } from "@/lib/data";
import { estValue, type PriceTier, type Role } from "@/lib/auction";
import { similarTo, isGem, gemThreshold, type SimilarRow } from "@/lib/scout";
import { Combobox } from "@/components/Combobox";
import { PageTitle, Card, CardHeader, Spinner, Empty, Badge, Collapsible } from "@/components/ui";
import { fmt } from "@/lib/utils";

const POS = {
  opener: "Opener",
  no3: "No. 3",
  middle: "Middle",
  finisher: "Finisher",
  lower: "Lower",
  tailender: "Tailender",
} as Record<string, string>;

const ROLE_OPTS: { value: Role; label: string }[] = [
  { value: "batter", label: "Batter" },
  { value: "all_rounder", label: "All-rounder" },
  { value: "keeper", label: "Keeper" },
  { value: "bowler", label: "Bowler" },
];

// The look-alike tiers, rendered one panel each. IPL peers are profile-linkable;
// the rest are free agents you can draft. SMAT carries the uncapped-gem flag.
const TIERS: {
  key: keyof ScoutIndex;
  title: string;
  subtitle: string;
  icon: React.ReactNode;
  linkable: boolean;
  draftable: boolean;
  gem: boolean;
}[] = [
  { key: "ipl", title: "IPL peers", subtitle: "Most-similar active IPL players", icon: <Users className="h-4 w-4 text-accent" />, linkable: true, draftable: false, gem: false },
  { key: "smat", title: "Uncapped · SMAT", subtitle: "Domestic Indian prospects of the same mould", icon: <Sprout className="h-4 w-4 text-willow" />, linkable: false, draftable: true, gem: true },
  { key: "bbl", title: "Overseas · BBL", subtitle: "Big Bash (Australia) of the same mould", icon: <Plane className="h-4 w-4 text-accent" />, linkable: false, draftable: true, gem: false },
  { key: "sa20", title: "Overseas · SA20", subtitle: "SA20 (South Africa) of the same mould", icon: <Plane className="h-4 w-4 text-accent" />, linkable: false, draftable: true, gem: false },
  { key: "cpl", title: "Overseas · CPL", subtitle: "Caribbean Premier League of the same mould", icon: <Plane className="h-4 w-4 text-accent" />, linkable: false, draftable: true, gem: false },
  { key: "blast", title: "Overseas · T20 Blast", subtitle: "English county T20 of the same mould", icon: <Plane className="h-4 w-4 text-accent" />, linkable: false, draftable: true, gem: false },
];

// similarTo / isGem / gemThreshold are the parity-locked engine from
// `@/lib/scout` (mirrored bit-for-bit by the Python port) — single source of
// truth across every surface.

function ScoutMath() {
  return (
    <Collapsible title="How the scout works (plain English)" icon={<Network className="h-4 w-4" />}>
      <div className="space-y-3 text-sm leading-relaxed text-muted">
        <p>
          Pick an active IPL player. We find players of the <b>same archetype</b> (same role; for
          bowlers, same seam/spin type) at three levels and rank them by how close their{" "}
          <b>skill standing</b> is to your pick.
        </p>
        <ul className="space-y-1.5">
          <li>• <b className="text-fg">IPL peers</b> — who else in the IPL is most like them.</li>
          <li>• <b className="text-fg">Uncapped (SMAT)</b> — domestic Indian prospects of the same mould — the "next one".</li>
          <li>• <b className="text-fg">Overseas</b> — Big Bash (BBL), SA20, CPL &amp; T20 Blast players of the same mould.</li>
        </ul>
        <p>
          "Skill standing" is the player's Bayesian value expressed as a z-score <i>within its own
          competition</i> (mean 0, sd 1), so a star in SMAT and a star in the IPL line up even though
          the raw numbers aren't comparable across tiers. Similarity = how close those standings are.
        </p>
        <p>
          Each row shows an <b>estimated crore price</b> (the same skill→price curve the Auction room
          uses, discounted for the weaker tier). For SMAT/BBL look-alikes we also show the{" "}
          <b>saving</b> versus your (expensive) IPL pick — the budget-swap case. A{" "}
          <Gem className="inline h-3 w-3 text-willow" /> <b className="text-willow">gem</b> flags an
          uncapped prospect with unusually high standing for how little he's played — a moneyball
          punt. Hit <b>Draft</b> to drop a prospect straight into the Auction room as a retention.
        </p>
      </div>
    </Collapsible>
  );
}

function TierPanel({
  title,
  icon,
  subtitle,
  rows,
  tier,
  selPrice,
  gemMedian,
  linkable,
  draftable,
  navigate,
}: {
  title: string;
  icon: React.ReactNode;
  subtitle: string;
  rows: SimilarRow[];
  tier: PriceTier;
  selPrice: number | null;
  gemMedian: number | null;
  linkable: boolean;
  draftable: boolean;
  navigate: (path: string) => void;
}) {
  return (
    <Card>
      <CardHeader title={<span className="flex items-center gap-2">{icon}{title}</span>} subtitle={subtitle} />
      <div className="p-2">
        {rows.length === 0 ? (
          <div className="px-3 py-6 text-center text-sm text-muted">No close match of this archetype.</div>
        ) : (
          rows.map((p, i) => {
            const sim = p.sim;
            const price = estValue(p.value, p.role, tier);
            const saving = selPrice != null && price < selPrice ? selPrice - price : 0;
            const gem = isGem(p, gemMedian);
            return (
              <div key={p.cricsheet_id} className="rounded-md px-3 py-2 hover:bg-surface">
                {/* line 1: rank + full-width name + similarity */}
                <div className="flex items-center justify-between gap-2 text-sm">
                  <span className="flex min-w-0 items-center gap-2">
                    <span className="stat-num w-4 shrink-0 text-xs text-muted">{i + 1}</span>
                    {linkable ? (
                      <button
                        onClick={() => navigate(`/player?cid=${p.cricsheet_id}`)}
                        className="truncate text-left text-fg hover:text-accent-glow"
                      >
                        {p.name}
                      </button>
                    ) : (
                      <span className="truncate text-fg">{p.name}</span>
                    )}
                    {gem && (
                      <span title="Uncapped gem — high standing for very few balls played (moneyball)">
                        <Gem className="h-3.5 w-3.5 shrink-0 text-willow" />
                      </span>
                    )}
                  </span>
                  <Badge tone={sim > 0.8 ? "accent" : sim > 0.6 ? "willow" : "muted"}>
                    {Math.round(sim * 100)}%
                  </Badge>
                </div>
                {/* line 2: meta (country · price · saving · draft) */}
                <div className="mt-1 flex flex-wrap items-center gap-x-2.5 gap-y-1 pl-6 text-[11px] text-muted">
                  {p.country && <span>{p.country}</span>}
                  {p.last_match_date && <span className="stat-num">{p.last_match_date.slice(0, 4)}</span>}
                  <span className="stat-num">≈{fmt(price, 1)}cr</span>
                  {saving > 0 && <span className="stat-num text-willow">save {fmt(saving, 1)}</span>}
                  {draftable && (
                    <button
                      onClick={() => navigate(`/auction?draft=${p.cricsheet_id}`)}
                      title="Draft into the Auction room as a retention"
                      className="ml-auto inline-flex shrink-0 items-center gap-1 rounded-md border border-accent/30 bg-accent/10 px-1.5 py-0.5 text-accent-glow hover:border-accent/50"
                    >
                      <Gavel className="h-3 w-3" /> Draft
                    </button>
                  )}
                </div>
              </div>
            );
          })
        )}
      </div>
    </Card>
  );
}

// "The next X" — uncapped SMAT prospects that punch above their sample.
function GemsBoard({ gems, navigate }: { gems: ScoutPlayer[]; navigate: (p: string) => void }) {
  if (!gems.length) return null;
  return (
    <Card className="mb-5">
      <CardHeader
        title={
          <span className="flex items-center gap-2">
            <Gem className="h-4 w-4 text-willow" /> The next big things
          </span>
        }
        subtitle="Uncapped SMAT prospects punching above their sample — high standing on below-median exposure (moneyball)"
      />
      <div className="grid grid-cols-1 gap-x-4 p-2 sm:grid-cols-2">
        {gems.map((p, i) => (
          <div
            key={p.cricsheet_id}
            className="flex flex-wrap items-center gap-x-2.5 gap-y-1 rounded-md px-3 py-2 text-sm hover:bg-surface"
          >
            <span className="stat-num w-4 shrink-0 text-xs text-muted">{i + 1}</span>
            <span className="font-medium text-fg">{p.name}</span>
            {p.country && <span className="text-[11px] text-muted">{p.country}</span>}
            <Badge tone="willow">standing {fmt(p.z, 2)}</Badge>
            <span className="text-[11px] text-muted">{p.balls} balls</span>
            <span className="stat-num ml-auto text-[11px] text-muted">
              ≈{fmt(estValue(p.value, p.role, "smat"), 1)}cr
            </span>
            <button
              onClick={() => navigate(`/auction?draft=${p.cricsheet_id}`)}
              title="Draft into the Auction room as a retention"
              className="inline-flex shrink-0 items-center gap-1 rounded-md border border-accent/30 bg-accent/10 px-1.5 py-0.5 text-[11px] text-accent-glow hover:border-accent/50"
            >
              <Gavel className="h-3 w-3" /> Draft
            </button>
          </div>
        ))}
      </div>
    </Card>
  );
}

export function Scout() {
  const navigate = useNavigate();
  const { options } = usePlayers("ipl"); // nice full-name search
  const idx = useAsync<ScoutIndex>(() => getScoutIndex("ipl"), []);
  const [cid, setCid] = useState<string | null>(null);
  const [roleSel, setRoleSel] = useState<Role>("batter");
  const [posSel, setPosSel] = useState("");

  const iplById = useMemo(() => {
    const m = new Map<string, ScoutPlayer>();
    for (const p of idx.data?.ipl ?? []) m.set(p.cricsheet_id, p);
    return m;
  }, [idx.data]);

  // only IPL players that exist in the scout index are pickable
  const pickOptions = useMemo(() => options.filter((o) => iplById.has(o.value)), [options, iplById]);
  const sel = cid ? iplById.get(cid) : null;

  // default the role filter to the pick's own role whenever the pick changes
  useEffect(() => {
    if (sel) setRoleSel(sel.role);
    setPosSel("");
  }, [sel]);

  // median SMAT exposure → the gem cutoff (high standing, below-median balls)
  const gemMedian = useMemo(() => gemThreshold(idx.data?.smat ?? []), [idx.data]);

  // headline "next X" board — the standout uncapped gems, pick-independent
  const gems = useMemo(
    () =>
      (idx.data?.smat ?? [])
        .filter((p) => isGem(p, gemMedian))
        .sort((a, b) => b.z - a.z)
        .slice(0, 12),
    [idx.data, gemMedian],
  );

  // the pick's own est. IPL price — the baseline the savings compare against
  const selPrice = sel ? estValue(sel.value, sel.role, "ipl") : null;
  const posDisabled = roleSel === "bowler";

  return (
    <>
      <PageTitle
        title="Scout"
        icon={<Network className="h-6 w-6" />}
        desc="Pick an active IPL player and find others of the same mould at three levels — IPL peers, uncapped Indian prospects (SMAT), and overseas options (BBL, SA20, CPL & T20 Blast) — with an estimated price, the saving vs your pick, and a one-click draft into the Auction room."
      />

      <ScoutMath />

      <GemsBoard gems={gems} navigate={navigate} />

      <div className="mb-4 flex flex-wrap items-center gap-3">
        <Combobox options={pickOptions} value={cid} onChange={setCid} placeholder="Search an active IPL player…" className="max-w-md flex-1" />
        {sel && (
          <div className="flex flex-wrap items-center gap-2 text-sm text-muted">
            <Badge tone="accent">{sel.role.replace("_", "-")}</Badge>
            {sel.role === "bowler" && sel.bowling_category && (
              <Badge tone={sel.bowling_category === "spin" ? "willow" : "ball"}>{sel.bowling_category}</Badge>
            )}
            {sel.batting_position && <Badge>{POS[sel.batting_position] ?? sel.batting_position}</Badge>}
            <span className="text-xs">standing {fmt(sel.z, 2)}</span>
            {selPrice != null && <span className="text-xs">· ≈{fmt(selPrice, 1)}cr</span>}
          </div>
        )}
      </div>

      {/* role / position filters — match a different mould, or narrow by slot */}
      {sel && (
        <div className="mb-4 flex flex-wrap items-center gap-3 text-sm">
          <label className="flex items-center gap-2">
            <span className="text-xs font-medium text-muted">Match role</span>
            <select
              value={roleSel}
              onChange={(e) => setRoleSel(e.target.value as Role)}
              className="input w-auto cursor-pointer py-1 text-xs"
            >
              {ROLE_OPTS.map((r) => (
                <option key={r.value} value={r.value} className="bg-card">{r.label}</option>
              ))}
            </select>
          </label>
          <label className="flex items-center gap-2">
            <span className="text-xs font-medium text-muted">Batting slot</span>
            <select
              value={posSel}
              disabled={posDisabled}
              onChange={(e) => setPosSel(e.target.value)}
              className="input w-auto cursor-pointer py-1 text-xs disabled:opacity-40"
            >
              <option value="" className="bg-card">Any</option>
              {Object.entries(POS).map(([k, v]) => (
                <option key={k} value={k} className="bg-card">{v}</option>
              ))}
            </select>
          </label>
          {(roleSel !== sel.role || posSel) && (
            <button
              onClick={() => { setRoleSel(sel.role); setPosSel(""); }}
              className="text-xs text-accent-glow hover:underline"
            >
              reset
            </button>
          )}
        </div>
      )}

      {idx.loading ? (
        <Spinner label="Loading scout index…" />
      ) : !sel ? (
        <Empty>Pick an IPL player to scout look-alikes across IPL, SMAT &amp; overseas (BBL, SA20, CPL, T20 Blast).</Empty>
      ) : (
        <div className="grid grid-cols-1 gap-5 animate-fade-up lg:grid-cols-3">
          {TIERS.map((t) => (
            <TierPanel
              key={t.key}
              title={t.title}
              icon={t.icon}
              subtitle={t.subtitle}
              rows={similarTo(sel, idx.data![t.key], roleSel, posSel)}
              tier={t.key}
              selPrice={selPrice}
              gemMedian={t.gem ? gemMedian : null}
              linkable={t.linkable}
              draftable={t.draftable}
              navigate={navigate}
            />
          ))}
        </div>
      )}
    </>
  );
}
