import { useEffect, useMemo } from "react";
import { useNavigate } from "react-router-dom";
import { Network, Users, Sprout, Plane, Gem, Gavel } from "lucide-react";
import { usePlayers } from "@/lib/usePlayers";
import { useStore } from "@/lib/store";
import { useAsync } from "@/lib/useAsync";
import { displayName, getAuctionPool, getLeagues, getScoutIndex, type ScoutPlayer, type ScoutIndex } from "@/lib/data";
import { scoutPools, type LeagueRegistry, type ScoutGroup } from "@/lib/leagues";
import { scoutPrice, type Role } from "@/lib/auction";
import {
  similarTo,
  isGem,
  gemThreshold,
  slotBand,
  BAND_LABEL,
  SAME_SLOT,
  type SimilarRow,
  type CountryMode,
} from "@/lib/scout";
import { Combobox } from "@/components/Combobox";
import { PageTitle, Card, CardHeader, Spinner, Empty, Badge, Collapsible, ErrorBox, Segmented, StaleBadge } from "@/components/ui";
import { fmt, profilePath } from "@/lib/utils";
import { hasKey, useUrlId, useUrlParams } from "@/lib/useUrlState";

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

// The look-alike pools come from the league registry (leagues.json, from config/leagues.toml), one
// panel each, keyed by tier as scout_index.json is. The `peers` pool (IPL) is profile-linkable;
// draftable pools are free agents you can draft; the gem pool carries the uncapped-gem flag.
interface TierDef {
  key: string;
  title: string;
  subtitle: string;
  icon: React.ReactNode;
  linkable: boolean;
  draftable: boolean;
  gem: boolean;
}

const GROUP_ICON: Record<ScoutGroup, React.ReactNode> = {
  peers: <Users className="h-4 w-4 text-accent" />,
  uncapped: <Sprout className="h-4 w-4 text-willow" />,
  overseas: <Plane className="h-4 w-4 text-accent" />,
};

function tierDefs(reg: LeagueRegistry | null): TierDef[] {
  return scoutPools(reg).map((l) => ({
    key: l.tier as string,
    title: l.scout_title ?? l.short,
    subtitle: l.scout_subtitle ?? l.name,
    icon: GROUP_ICON[l.scout_group ?? "overseas"],
    linkable: l.scout_group === "peers",
    draftable: l.draftable,
    gem: l.gem_pool,
  }));
}

/** "BBL, SA20, CPL & T20 Blast" — the overseas pools' short names. */
function overseasNames(reg: LeagueRegistry | null): string {
  const names = scoutPools(reg)
    .filter((l) => l.scout_group === "overseas")
    .map((l) => l.short);
  return names.length > 1 ? `${names.slice(0, -1).join(", ")} & ${names[names.length - 1]}` : (names[0] ?? "");
}

// similarTo / isGem / gemThreshold are the parity-locked engine from
// `@/lib/scout` (mirrored bit-for-bit by the Python port) — single source of
// truth across every surface.

function ScoutMath({ reg }: { reg: LeagueRegistry | null }) {
  return (
    <Collapsible title="How the scout works (plain English)" icon={<Network className="h-4 w-4" />}>
      <div className="space-y-3 text-sm leading-relaxed text-muted">
        <p>
          Pick an active IPL player. We find players of the <b>same type</b> across{" "}
          {scoutPools(reg).length || "every"} pools — same role, the same bowling type for anyone who bowls (a
          seam-bowling all-rounder only gets seam-bowling all-rounders), and by default the same part of the batting
          order (top 1–3, middle 4–7, lower 8–11) — and rank them by how close their <b>skill standing</b> is to your
          pick. The country filter starts on the pick's own country; switch to <b>Overseas</b> or <b>All</b> to widen it.
        </p>
        <ul className="space-y-1.5">
          <li>• <b className="text-fg">IPL peers</b> — who else in the IPL is most like them.</li>
          <li>• <b className="text-fg">Uncapped (SMAT)</b> — domestic Indian prospects of the same mould — the "next one".</li>
          <li>• <b className="text-fg">Overseas</b> — {overseasNames(reg) || "overseas league"} players of the same mould.</li>
        </ul>
        <p>
          "Skill standing" is the player's Bayesian value <i>for his role</i> (batting for batters and
          keepers, bowling for bowlers, both for all-rounders) expressed as a z-score among the listed
          players of that role <i>in his own competition</i> (mean 0, sd 1), so a star in SMAT and a
          star in the IPL line up even though
          the raw numbers aren't comparable across tiers. Similarity = how close those standings are.
        </p>
        <p>
          Each row shows an <b>estimated crore price</b> (the same skill→price curve the Auction room
          uses, discounted for the weaker tier). For every non-IPL look-alike we also show the{" "}
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
  selPrice,
  gemMedian,
  linkable,
  draftable,
  inPool,
  navigate,
  stale,
}: {
  title: string;
  icon: React.ReactNode;
  subtitle: string;
  rows: SimilarRow[];
  selPrice: number | null;
  gemMedian: number | null;
  linkable: boolean;
  draftable: boolean;
  /** cricsheet ids in the auction pool — only these can be drafted */
  inPool: Set<string>;
  navigate: (path: string) => void;
  /** The pool's last data date when its league feed is stale (null = fresh). */
  stale: string | null;
}) {
  return (
    <Card>
      <CardHeader
        title={
          <span className="flex flex-wrap items-center gap-2">
            {icon}
            {title}
            {stale && <StaleBadge asOf={stale} />}
          </span>
        }
        subtitle={subtitle}
      />
      <div className="p-2">
        {rows.length === 0 ? (
          <div className="px-3 py-6 text-center text-sm text-muted">No close match of this archetype.</div>
        ) : (
          rows.map((p, i) => {
            const sim = p.sim;
            const price = scoutPrice(p);
            const saving = selPrice != null && price < selPrice ? selPrice - price : 0;
            const gem = isGem(p, gemMedian);
            return (
              <div key={p.cricsheet_id} className="rounded-md px-3 py-2 hover:bg-surface">
                {/* line 1: rank + full-width name + similarity */}
                <div className="flex items-center justify-between gap-2 text-sm">
                  <span className="flex min-w-0 items-center gap-2">
                    <span className="stat-num w-4 shrink-0 text-xs text-muted">{i + 1}</span>
                    {p.profile_collection || linkable ? (
                      <button
                        onClick={() => navigate(profilePath(p.cricsheet_id, p.profile_collection ?? "ipl"))}
                        title="Open profile"
                        className="truncate text-left text-fg hover:text-accent-glow"
                      >
                        {displayName(p)}
                      </button>
                    ) : (
                      <span className="truncate text-fg">{displayName(p)}</span>
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
                  {draftable && inPool.has(p.cricsheet_id) && (
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
function GemsBoard({
  gems,
  navigate,
  inPool,
  stale,
}: {
  gems: ScoutPlayer[];
  navigate: (p: string) => void;
  inPool: Set<string>;
  stale: string | null;
}) {
  if (!gems.length) return null;
  return (
    <Card className="mb-5">
      <CardHeader
        title={
          <span className="flex items-center gap-2">
            <Gem className="h-4 w-4 text-willow" /> The next big things
            {stale && <StaleBadge asOf={stale} />}
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
            {p.profile_collection ? (
              <button
                onClick={() => navigate(profilePath(p.cricsheet_id, p.profile_collection))}
                className="font-medium text-fg hover:text-accent-glow"
                title="Open profile"
              >
                {displayName(p)}
              </button>
            ) : (
              <span className="font-medium text-fg">{displayName(p)}</span>
            )}
            {p.country && <span className="text-[11px] text-muted">{p.country}</span>}
            <Badge tone="willow">standing {fmt(p.z, 2)}</Badge>
            <span className="text-[11px] text-muted">{p.balls} balls</span>
            <span className="stat-num ml-auto text-[11px] text-muted">
              ≈{fmt(scoutPrice(p), 1)}cr
            </span>
            {inPool.has(p.cricsheet_id) ? (
              <button
                onClick={() => navigate(`/auction?draft=${p.cricsheet_id}`)}
                title="Draft into the Auction room as a retention"
                className="inline-flex shrink-0 items-center gap-1 rounded-md border border-accent/30 bg-accent/10 px-1.5 py-0.5 text-[11px] text-accent-glow hover:border-accent/50"
              >
                <Gavel className="h-3 w-3" /> Draft
              </button>
            ) : (
              <span className="text-[11px] text-faint" title="Not in this year's auction pool">not in pool</span>
            )}
          </div>
        ))}
      </div>
    </Card>
  );
}

export function Scout() {
  const rawNavigate = useNavigate();
  const { collection } = useStore();
  // profile links carry their own league (`?c=<profile_collection>`), so they open in the right place
  const navigate = (path: string) => rawNavigate(path);
  const { options } = usePlayers("ipl"); // nice full-name search
  const idx = useAsync<ScoutIndex>(() => getScoutIndex("ipl"), []);
  // the registry: which pools to show (prices come translated onto the IPL in the data)
  const reg = useAsync<LeagueRegistry>(() => getLeagues(), []);
  const tiers = useMemo(() => tierDefs(reg.data).filter((t) => idx.data && t.key in idx.data), [reg.data, idx.data]);
  const gemTier = reg.data?.gem_tier ?? null;
  const pool = useAsync(() => getAuctionPool("ipl"), []);
  const inPool = useMemo(() => new Set((pool.data ?? []).map((r) => String(r.cricsheet_id))), [pool.data]);
  const iplById = useMemo(() => {
    const m = new Map<string, ScoutPlayer>();
    for (const p of idx.data?.ipl ?? []) m.set(p.cricsheet_id, p);
    return m;
  }, [idx.data]);

  // only IPL players that exist in the scout index are pickable
  const pickOptions = useMemo(() => options.filter((o) => iplById.has(o.value)), [options, iplById]);
  // pick, role and slot live in the URL (`?pick=…&role=…&pos=…`) so a link reproduces the search
  const { params, update } = useUrlParams();
  const [cid] = useUrlId("pick", iplById, !!idx.data);
  const sel = cid ? iplById.get(cid) : null;
  // a new pick starts from its own role and any slot
  const setCid = (v: string | null) => update({ pick: v, role: null, pos: null, country: null }, { replace: false });

  // the role filter defaults to the pick's own role; only a different one is written to the URL
  const urlRole = params.get("role");
  const roleOk = !!urlRole && ROLE_OPTS.some((r) => r.value === urlRole);
  const roleSel: Role = roleOk ? (urlRole as Role) : (sel?.role ?? "batter");
  const setRoleSel = (r: Role) => update({ role: sel && r === sel.role ? null : r });
  const urlPos = params.get("pos") ?? "";

  // median exposure in the gem pool (SMAT) → the gem cutoff (high standing, below-median balls)
  const gemPool = useMemo(() => (gemTier ? (idx.data?.[gemTier] ?? []) : []), [idx.data, gemTier]);
  const gemMedian = useMemo(() => gemThreshold(gemPool), [gemPool]);

  // headline "next X" board — the standout uncapped gems, pick-independent
  const gems = useMemo(
    () =>
      gemPool
        // a capped international is never an "uncapped gem" (needs the export's capped flag)
        .filter((p) => isGem(p, gemMedian) && p.capped !== true)
        .sort((a, b) => b.z - a.z)
        .slice(0, 12),
    [gemPool, gemMedian],
  );

  // the pick's own est. IPL price — the baseline the savings compare against
  const selPrice = sel ? scoutPrice(sel) : null;
  const posDisabled = roleSel === "bowler";
  // batting slot: by default the pick's own band (top / middle / lower order); "any" or one exact slot on demand.
  // Meaningless for a bowler match, so it's dropped rather than kept filtering invisibly.
  const selBand = slotBand(sel?.batting_position);
  const posDefault = selBand ? SAME_SLOT : "any";
  const posValue = posDisabled ? "" : urlPos === "any" || hasKey(POS, urlPos) ? urlPos : posDefault;
  const posSel = posValue === "any" ? "" : posValue;
  const setPosSel = (p: string) => update({ pos: p === posDefault ? null : p });
  // country: the pick's own by default; overseas or all on demand
  const urlCountry = params.get("country");
  const countryOk = urlCountry === "overseas" || urlCountry === "all";
  const countrySel: CountryMode = sel?.country ? (countryOk ? (urlCountry as CountryMode) : "same") : "all";
  const setCountrySel = (c: CountryMode) => update({ country: c === "same" ? null : c });
  // tidy unknown / meaningless role, slot and country values out of the URL
  const badRole = !!urlRole && !roleOk;
  const badPos = !!urlPos && urlPos !== "any" && !hasKey(POS, urlPos);
  const badCountry = !!urlCountry && !countryOk;
  useEffect(() => {
    if (badRole || badPos || badCountry)
      update({
        ...(badRole ? { role: null } : {}),
        ...(badPos ? { pos: null } : {}),
        ...(badCountry ? { country: null } : {}),
      });
  }, [badRole, badPos, badCountry, update]);

  const results = useMemo(() => {
    if (!sel || !idx.data) return [];
    return tiers.map((t) => ({
      t,
      rows: similarTo(sel, idx.data![t.key], roleSel, posSel, 8, {
        country: countrySel,
        // the uncapped pool is domestic: a player with no country on file is from the pick's country
        fallbackCountry: t.gem ? sel.country : null,
      }),
    }));
  }, [sel, idx.data, tiers, roleSel, posSel, countrySel]);
  const shown = results.filter((r) => r.rows.length > 0);
  // a pool whose league feed has stopped updating (rows carry `stale` + `data_as_of`): its last data date
  const staleOf = (tier: string): string | null => {
    const row = (idx.data?.[tier] ?? []).find((r) => r.stale);
    return row ? (row.data_as_of ?? "") : null;
  };
  const empty = results.filter((r) => r.rows.length === 0);
  const bowlsType = sel && (sel.role === "bowler" || sel.role === "all_rounder") ? sel.bowling_category : null;

  return (
    <>
      <PageTitle
        title="Scout"
        icon={<Network className="h-6 w-6" />}
        desc={`Pick an active IPL player and find others of the same mould across every pool — IPL peers, uncapped Indian prospects (SMAT), and overseas options (${overseasNames(reg.data) || "overseas leagues"}) — with an estimated price, the saving vs your pick, and a one-click draft into the Auction room.`}
      />

      <ScoutMath reg={reg.data} />

      {collection !== "ipl" && (
        <div className="mb-4 rounded-xl border border-gold/30 bg-gold/5 px-4 py-2.5 text-sm text-muted">
          Scout always uses <b className="text-fg">IPL</b> data (it prices players for the IPL auction), whatever league the header shows.
        </div>
      )}

      {gemTier && reg.data && (
        <GemsBoard gems={gems} navigate={navigate} inPool={inPool} stale={staleOf(gemTier)} />
      )}

      <div className="mb-4 flex flex-wrap items-center gap-3">
        <Combobox options={pickOptions} value={cid} onChange={setCid} placeholder="Search an active IPL player…" className="max-w-md flex-1" />
        {sel && (
          <div className="flex flex-wrap items-center gap-2 text-sm text-muted">
            <Badge tone="accent">{sel.role.replace("_", "-")}</Badge>
            {bowlsType && (
              <Badge tone={bowlsType === "spin" ? "willow" : "ball"}>{bowlsType === "spin" ? "spin bowling" : "seam bowling"}</Badge>
            )}
            {sel.batting_position && <Badge>{POS[sel.batting_position] ?? sel.batting_position}</Badge>}
            {sel.country && <Badge>{sel.country}</Badge>}
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
              value={posValue}
              disabled={posDisabled}
              title={posDisabled ? "Batting slot doesn't apply when matching bowlers" : undefined}
              onChange={(e) => setPosSel(e.target.value)}
              className="input w-auto cursor-pointer py-1 text-xs disabled:opacity-40"
            >
              {posDisabled && <option value="" className="bg-card">n/a for bowlers</option>}
              {selBand && (
                <option value={SAME_SLOT} className="bg-card">Same as pick — {BAND_LABEL[selBand]}</option>
              )}
              <option value="any" className="bg-card">Any slot</option>
              {Object.entries(POS).map(([k, v]) => (
                <option key={k} value={k} className="bg-card">{v}</option>
              ))}
            </select>
          </label>
          <div className="flex items-center gap-2">
            <span className="text-xs font-medium text-muted">Country</span>
            {sel.country ? (
              <Segmented<CountryMode>
                label="Country"
                value={countrySel}
                onChange={setCountrySel}
                options={[
                  { value: "same", label: `Same (${sel.country})` },
                  { value: "overseas", label: "Overseas" },
                  { value: "all", label: "All" },
                ]}
              />
            ) : (
              <span className="text-xs text-faint">all (pick's country unknown)</span>
            )}
          </div>
          {(roleSel !== sel.role || urlPos || urlCountry) && (
            <button
              onClick={() => update({ role: null, pos: null, country: null })}
              className="text-xs text-accent-glow hover:underline"
            >
              reset
            </button>
          )}
        </div>
      )}

      {(idx.loading && !idx.data) || (reg.loading && !reg.data) ? (
        <Spinner label="Loading scout index…" />
      ) : idx.error || reg.error ? (
        <ErrorBox message={(idx.error || reg.error) as string} />
      ) : !sel ? (
        <Empty>Pick an IPL player to scout look-alikes across IPL, SMAT &amp; overseas ({overseasNames(reg.data)}).</Empty>
      ) : (
        <div className="animate-fade-up">
          {empty.length > 0 && (
            <div className="mb-4 rounded-xl border border-border bg-surface/50 px-4 py-2.5 text-sm text-muted">
              No {countrySel === "same" ? `${sel.country} ` : countrySel === "overseas" ? "overseas " : ""}match of this
              type in {empty.map((r) => r.t.title.replace(/^.*·\s*/, "")).join(", ")}
              {countrySel !== "all" ? (
                <>
                  {" "}— switch Country to{" "}
                  <button className="text-accent-glow hover:underline" onClick={() => setCountrySel("all")}>
                    All
                  </button>{" "}
                  to see them.
                </>
              ) : (
                "."
              )}
            </div>
          )}
          <div className="grid grid-cols-1 gap-5 lg:grid-cols-3">
            {shown.map(({ t, rows }) => (
              <TierPanel
                key={t.key}
                title={t.title}
                icon={t.icon}
                subtitle={t.subtitle}
                rows={rows}
                selPrice={selPrice}
                gemMedian={t.gem ? gemMedian : null}
                linkable={t.linkable}
                draftable={t.draftable}
                inPool={inPool}
                navigate={navigate}
                stale={staleOf(t.key)}
              />
            ))}
          </div>
        </div>
      )}
    </>
  );
}
