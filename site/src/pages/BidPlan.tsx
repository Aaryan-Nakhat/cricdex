import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  ClipboardList,
  Calculator,
  Download,
  Link2,
  RotateCcw,
  Plane,
  Printer,
  AlertTriangle,
  Check,
  ArrowRight,
  Scale,
  Users,
  SlidersHorizontal,
  X,
} from "lucide-react";
import { useAsync } from "@/lib/useAsync";
import { fetchBidplanRivals, getAuctionPool, getAuctionRegister, getKeep, type AuctionPoolRow } from "@/lib/data";
import { buildPool } from "@/lib/auction";
import { cr, fmtNum, STALE_REASON_MIN, toCsv, type Decision, type KeepData } from "@/lib/keep";
import {
  DEFAULT_NEEDS,
  gapCosts,
  type GapCost,
  NEED_LABEL,
  NEED_ORDER,
  OPEN_SLOTS,
  REPLACEMENT,
  SLOT_LABEL,
  TEAM_BALLS,
  TRIALS,
  XI_OVERSEAS,
  buildContext,
  plan,
  toCsvRows,
  type BidContext,
  type BidPlan as Plan,
  type Need,
  type RegisterEntry,
  type RivalBids,
} from "@/lib/bidplan";
import { useUrlParams } from "@/lib/useUrlState";
import { PageTitle, Card, CardHeader, Spinner, Badge, Empty, InfoTip, Collapsible, ErrorBox, StatTile, StaleShareBadge } from "@/components/ui";
import { Combobox } from "@/components/Combobox";
import { cn, profilePath } from "@/lib/utils";

const ROLE_LABEL: Record<string, string> = { batter: "Batter", bowler: "Bowler", all_rounder: "All-rounder", keeper: "Keeper" };
const TRIAL_CHOICES = [100, 200, 400];
const splitIds = (s: string) => new Set(s.split(",").map((x) => x.trim()).filter(Boolean));
const dateLabel = (iso: string) =>
  new Date(`${iso}T00:00:00`).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
const pct = (x: number) => `${fmtNum(100 * x, 0)}%`;

function NumberField({ label, value, onChange, min = 0, max = 999, step = 1, suffix, hint }: {
  label: string; value: number; onChange: (v: number) => void; min?: number; max?: number; step?: number; suffix?: string; hint?: string;
}) {
  const [text, setText] = useState(String(value));
  useEffect(() => setText(String(value)), [value]);
  const commit = () => {
    const n = Number(text);
    const v = Number.isFinite(n) && text.trim() !== "" ? Math.min(max, Math.max(min, n)) : value;
    setText(String(v));
    if (v !== value) onChange(v);
  };
  return (
    <label className="block min-w-0" title={hint}>
      <span className="mb-1 block truncate text-xs font-medium text-muted">{label}</span>
      <div className="flex items-center gap-2">
        <input type="number" className="input" value={text} min={min} max={max} step={step}
          onChange={(e) => setText(e.target.value)} onBlur={commit} onKeyDown={(e) => e.key === "Enter" && commit()} />
        {suffix && <span className="text-xs text-muted">{suffix}</span>}
      </div>
    </label>
  );
}

/** A max-bid cell you can type over (blank = the plan's own figure). */
function MaxBidInput({ value, mine, onCommit }: { value: number; mine: boolean; onCommit: (v: number | null) => void }) {
  const [text, setText] = useState(mine ? String(value) : "");
  useEffect(() => setText(mine ? String(value) : ""), [value, mine]);
  const commit = () => {
    const t = text.trim();
    if (t === "") {
      if (mine) onCommit(null);
      return;
    }
    const n = Number(t);
    if (Number.isFinite(n) && n >= 0 && n <= 100) onCommit(Math.round(n * 100) / 100);
    else setText(mine ? String(value) : "");
  };
  return (
    <input
      type="number"
      inputMode="decimal"
      step={0.25}
      min={0}
      aria-label="Your max bid (cr)"
      placeholder={cr(value)}
      className={cn("input h-7 w-20 px-2 py-0.5 text-right text-xs print:hidden", mine && "border-gold/50 text-gold")}
      value={text}
      onChange={(e) => setText(e.target.value)}
      onBlur={commit}
      onKeyDown={(e) => e.key === "Enter" && commit()}
    />
  );
}

function HowItWorks({ res }: { res: Plan | null }) {
  return (
    <Collapsible title="How the plan is made (plain English)" icon={<Calculator className="h-4 w-4" />}>
      <div className="space-y-4 text-sm leading-relaxed text-muted">
        <p>
          <b className="text-fg">1. Who's in the auction.</b> Every free agent in the auction pool (not under contract with a
          franchise; not retired, by an announced retirement with its source; a T20 match somewhere in the last three
          years), plus every player the ten franchises release under their Keep-or-release plans (yours with your own Keep /
          Release calls). Before a mini
          auction teams clear room, so each plan opens at least the number of places you set ({OPEN_SLOTS} by default, the
          median number a team bought at the 2023, 2024 and 2026 mini auctions), releasing its lowest-valued players first.
          When the official auction list is published it replaces this guess.
        </p>
        <p>
          <b className="text-fg">2. What rivals would pay.</b> The other nine franchises, each with its own squad and purse,
          run through the Auction room's simulator {res ? res.trials : TRIALS} times, bidding by its demand model fitted on
          real auctions (whether a team bids at all and how high, from its open places by role and overseas, its purse per
          place, how much he'd improve its squad, his market and last price; how hot a player is varies from run to run).
          For every player that gives the price a rival would have paid in each run: the price you'd have to beat (one
          ladder step above the best rival's bid). "Rivals
          pay" is the middle of those runs, "usually enough" what wins him in 9 runs of 10, "P(≤ max)" the share of runs in
          which your max bid is enough. Your own releases are never bought back: if one is worth more to your squad than
          his salary, the plan says "reconsider keeping".
        </p>
        <p>
          <b className="text-fg">3. Squad strength.</b> The best XI's expected runs per match above a replacement
          player: each player's batting value at the balls he faces a match plus his bowling value at the balls he
          bowls, times his chance of playing (a lot's as a free agent: how often players like him play at all) (an opener
          faces about 21, a No. 7 about 9, a frontline bowler bowls about 23), the XI's balls held to a side's{" "}
          {TEAM_BALLS} a innings; at most {XI_OVERSEAS} overseas, a keeper, five bowling and six batting options; a place
          your squad can't fill goes to a replacement-level player ({fmtNum(REPLACEMENT, 0)}). Depth: the XI misses the
          matches its players don't play (1 − their chance of playing, added up), and the bench fills them, best first: a
          squad player up to one appearance a match, an auction lot only as often as players like him play at all (a
          retired-looking veteran with a 4% chance fills 4% of a match, not a whole one).
          Role needs (keepers, openers, death bowlers, spinners, pace) are targets the plan reports against; they don't
          change the strength. For a role still short after the likely buys, the sheet can price the gap: the target
          who fills it best, his usual price, and what the best plan built around him gains or gives up.
        </p>
        <pre className="overflow-auto rounded-lg border border-border bg-bg/60 px-3 py-2 font-mono text-xs leading-relaxed text-fg">{`strength = best XI + the bench filling the XI's missed matches
gain     = strength with him − strength without him
max bid  = the price at which he gives up as much as he adds: the later
           lots his money and his place would have bought instead`}</pre>
        <p>
          <b className="text-fg">4. The bidding rule.</b> In each rival run the lots come up stars first. A player is
          worth what he adds to your likely squad minus what paying for him gives up: the later lots that his money
          and his squad place (an overseas place, if he is overseas) would have bought at their expected prices. You
          bid up to the price where the two are equal, as long as the purse (keeping 0.3 cr for each place still
          needed to reach the squad minimum), the squad and the overseas cap allow. His gain counts the likely buys
          still to come, so an early lot isn't overpaid while a cheaper fit is due later; if a likely buy goes
          elsewhere, his substitutes bid higher{res ? <> (a crore is worth <b className="text-fg">{fmtNum(res.lam, 2)} runs a match</b> at the start)</> : null}.
          Money left after the auction buys nothing for the season (a replacement's fee is capped at the fee of the
          player he replaces and sits outside the cap: an assumption, from one press report, not the published
          regulations), but a place you fill is a place a later, better lot can't take, so a max bid stays finite
          even when the money outlasts the places.
        </p>
        <p>
          <b className="text-fg">5. The plan.</b> Targets are the players the rule lands in at least 5% of the runs (or that
          you give a max bid). <b className="text-fg">Max bid</b> = the price where he gives up as much as he adds (the
          median over the runs): above it the money and the place buy more elsewhere. <b className="text-fg">Fallback chains</b> list a
          role's targets in priority order, each with his max bid if everyone before him has gone for more (so with
          the money still there: these bids sit high). Priority = P(≤ max) × his gain × (1 − the price you'd expect
          to pay ÷ his max bid).
        </p>
        <p className="rounded-lg border border-willow/20 bg-willow/5 px-3 py-2 text-xs">
          <b className="text-willow">Honest caveat:</b> the rivals bid by a demand model chosen on the 2019–24 auctions, but
          prices rest on the market model, which can't see scouting, injury or brand; values are ratings, not certainties.
          Replayed on the 2024 auction (full purse, before the rule was chosen) its squads beat the real ones on
          the next season for 7 of 10 teams; on 2025 and 2026 at the real team's spend, for 2 of 10 and 1 of 10
          (those two seasons have been looked at many times while building it): see{" "}
          <a className="text-accent-glow underline" href="https://github.com/Aaryan-Nakhat/cricdex/blob/main/docs/METHODOLOGY.md#12-bid-plan-draft" target="_blank" rel="noreferrer">the methodology, section 12</a>.
          Treat it as a starting sheet for the war room, not a verdict.
        </p>
      </div>
    </Collapsible>
  );
}

export function BidPlan() {
  const keep = useAsync(() => getKeep("ipl"), []);
  const poolData = useAsync(() => getAuctionPool("ipl"), []);
  const reg = useAsync(() => getAuctionRegister("ipl"), []);
  const rivals = useAsync(() => fetchBidplanRivals("ipl"), []);
  return (
    <>
      <PageTitle
        title="Bid plan (draft)"
        icon={<ClipboardList className="h-6 w-6" />}
        desc="Whom to bid for at the auction, and how high. Your squad from Keep or release, rivals bidding hundreds of times in the Auction room's simulator, and the targets that add the most to your best XI for the purse: each with a max bid, the odds of landing him under it, and a fallback if he goes too high."
      />
      <Card className="mb-4 border-gold/40 bg-gold/5 px-4 py-3 text-sm leading-relaxed text-muted">
        <Badge tone="gold" className="mr-2">Draft</Badge>
        <b className="text-fg">A starting sheet, not a verdict.</b> The plan spends like real teams do and its
        max bids now differ player by player (each is what the player adds against what his money and place
        would buy later). Two known gaps: a few cheap batters with a thin IPL record are overrated, so they sit
        high on many sheets; and each sheet is planned as if the other nine weren't chasing the same names.
        Replaying real auctions with only what was known beforehand, its squads beat the real ones on the next
        season for 7 of 10 teams in 2024, but only 2 of 10 in 2025 and 1 of 10 in 2026 at the real franchise's
        spend. Use it to explore targets and fallbacks. Full results in{" "}
        <a className="text-accent-glow underline" href="https://github.com/Aaryan-Nakhat/cricdex/blob/main/docs/METHODOLOGY.md#12-bid-plan-draft" target="_blank" rel="noreferrer">the methodology (section 12)</a>.
      </Card>
      {keep.error || poolData.error ? (
        <ErrorBox message={(keep.error || poolData.error)!} />
      ) : !keep.data || !poolData.data || reg.loading || rivals.loading ? (
        <Spinner label="Loading the squads and the auction pool…" />
      ) : keep.data.players.length === 0 ? (
        <Empty>No squads exported yet.</Empty>
      ) : (
        <Planner data={keep.data} raw={poolData.data} register={reg.data ?? null} rivalBids={rivals.data ?? null} />
      )}
    </>
  );
}

function Planner({ data, raw, register, rivalBids }: { data: KeepData; raw: AuctionPoolRow[]; register: RegisterEntry[] | null; rivalBids: RivalBids | null }) {
  const comp = data.competition;
  const teams = data.teams;
  const { params, update } = useUrlParams();
  const teamParam = params.get("team") ?? "";
  const team = teams.includes(teamParam) ? teamParam : teams[0] ?? "";
  const keepIds = params.get("keep") ?? "";
  const relIds = params.get("rel") ?? "";
  const num = (k: string, lo: number, hi: number) => {
    const v = Number(params.get(k));
    return params.get(k) !== null && Number.isFinite(v) && v >= lo && v <= hi ? v : null;
  };
  const purse = num("purse", 1, 1000) ?? comp.rules.purse;
  const openSlots = num("open", 0, 25) ?? OPEN_SLOTS;
  const squadMax = num("smax", 11, 40) ?? comp.rules.squad_max;
  const squadMin = Math.min(num("smin", 11, 40) ?? comp.rules.squad_min, squadMax);
  const osMax = num("os", 0, 25) ?? comp.rules.overseas_max;
  const trials = TRIAL_CHOICES.includes(num("trials", 1, 1000) ?? -1) ? (num("trials", 1, 1000) as number) : TRIALS;
  const needParam = params.get("need") ?? "";
  const maxParam = params.get("max") ?? "";
  const needs = useMemo(() => {
    const out: Partial<Record<Need, number>> = {};
    for (const part of needParam.split(",")) {
      const [k, v] = part.split(":");
      if ((NEED_ORDER as string[]).includes(k) && /^\d{1,2}$/.test(v ?? "")) out[k as Need] = Number(v);
    }
    return out;
  }, [needParam]);
  const overrides = useMemo(() => {
    const out: Record<string, number> = {};
    for (const part of maxParam.split(",")) {
      const i = part.lastIndexOf(":");
      if (i <= 0) continue;
      const v = Number(part.slice(i + 1));
      if (Number.isFinite(v) && v >= 0 && v <= 100) out[part.slice(0, i)] = v;
    }
    return out;
  }, [maxParam]);
  const decisions = useMemo(() => {
    const d: Record<string, Decision> = {};
    for (const k of splitIds(keepIds)) d[k] = "keep";
    for (const k of splitIds(relIds)) d[k] = "release";
    return d;
  }, [keepIds, relIds]);
  const pool = useMemo(() => buildPool(raw), [raw]);
  const display = useMemo(() => {
    const out: Record<string, string> = {};
    for (const r of raw) if (r.display_name) out[r.cricsheet_id] = r.display_name;
    return out;
  }, [raw]);
  const profileOf = useMemo(() => new Map(raw.map((r) => [r.cricsheet_id, r.profile_collection ?? null])), [raw]);
  const squadIds = useMemo(() => new Set(data.players.map((p) => p.id).filter(Boolean)), [data.players]);

  const ctx: BidContext | null = useMemo(() => {
    try {
      return buildContext(data, pool, team, decisions, purse, openSlots,
        { squad_max: squadMax, squad_min: squadMin, overseas_max: osMax }, register, display, rivalBids);
    } catch {
      return null;
    }
  }, [data, pool, team, decisions, purse, openSlots, squadMax, squadMin, osMax, register, display, rivalBids]);

  // the plan runs a few hundred rival auctions: compute it off the render, show "working" meanwhile
  const runKey = JSON.stringify([team, keepIds, relIds, purse, openSlots, squadMax, squadMin, osMax, needParam, maxParam, trials, !!register]);
  const [result, setResult] = useState<{ key: string; res: Plan } | null>(null);
  const [failed, setFailed] = useState<string | null>(null);
  useEffect(() => {
    if (!ctx) return;
    setFailed(null);
    const id = window.setTimeout(() => {
      try {
        setResult({ key: runKey, res: plan(ctx, needs, overrides, trials) });
      } catch (e) {
        setFailed(e instanceof Error ? e.message : String(e));
      }
    }, 40);
    return () => window.clearTimeout(id);
  }, [ctx, needs, overrides, trials, runKey]);
  const res = result?.res ?? null;
  const busy = !failed && (!result || result.key !== runKey);
  const [copied, setCopied] = useState(false);

  const setNeed = (t: Need, v: number) => {
    const next = { ...needs, [t]: v };
    const parts = NEED_ORDER.filter((x) => next[x] !== undefined && next[x] !== DEFAULT_NEEDS[x]).map((x) => `${x}:${next[x]}`);
    update({ need: parts.join(",") || null });
  };
  const setOverride = (id: string, v: number | null) => {
    const next = { ...overrides };
    if (v === null) delete next[id];
    else next[id] = v;
    update({ max: Object.entries(next).map(([k, x]) => `${k}:${x}`).join(",") || null });
  };
  const pickTeam = (t: string) =>
    update({ team: t === teams[0] ? null : t, keep: null, rel: null, need: null, max: null }, { replace: false });
  const reset = () => update({ keep: null, rel: null, need: null, max: null, purse: null, open: null, smax: null, smin: null, os: null, trials: null });
  const keepLink = (() => {
    const q = new URLSearchParams();
    if (team !== teams[0]) q.set("team", team);
    if (keepIds) q.set("keep", keepIds);
    if (relIds) q.set("rel", relIds);
    if (params.get("purse")) q.set("purse", String(purse));
    const s = q.toString();
    return `/keep${s ? `?${s}` : ""}`;
  })();
  const download = () => {
    if (!res) return;
    const blob = new Blob([toCsv(toCsvRows(res))], { type: "text/csv;charset=utf-8" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `bid-plan-${team}-${comp.key}.csv`;
    a.click();
    URL.revokeObjectURL(a.href);
  };
  const copyLink = () => {
    void navigator.clipboard?.writeText(window.location.href).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    });
  };
  const assumed = new Set(comp.assumed);
  const addOptions = useMemo(
    () => (ctx ? ctx.available.map((r) => ({ value: r.cricsheet_id, label: r.name, hint: `${ROLE_LABEL[r.role] ?? r.role}${r.from_team ? ` · from ${r.from_team}` : ""} · ${cr(r.projected_value)} cr` })) : []),
    [ctx],
  );
  const staleOf = useMemo(() => new Map(raw.map((r) => [r.cricsheet_id, r])), [raw]);
  const nameLink = (id: string, name: string) => {
    const pc = profileOf.get(id);
    const where = pc ?? (squadIds.has(id) ? "ipl" : null);
    const link = where ? (
      <Link to={profilePath(id, where)} className="font-medium text-fg hover:text-accent-glow">{name}</Link>
    ) : (
      <span className="font-medium text-fg">{name}</span>
    );
    // a rating resting on stale SMAT data says so (issue I7)
    const r = staleOf.get(id);
    return r?.stale_note && (r.stale_share ?? 0) >= STALE_REASON_MIN ? (
      <>
        {link}
        <StaleShareBadge className="ml-1.5" share={r.stale_share ?? 0} note={r.stale_note} />
      </>
    ) : (
      link
    );
  };
  const customised = !!(keepIds || relIds || needParam || maxParam || params.get("purse") || params.get("open") || params.get("smax") || params.get("smin") || params.get("os") || params.get("trials"));

  return (
    <div className="space-y-5">
      <Card className="px-5 py-4 text-sm leading-relaxed text-muted">
        <span className="font-semibold text-fg">{comp.name}: </span>
        the auction is {assumed.has("auction_date") ? "likely " : ""}on <b className="text-fg">{dateLabel(comp.auction_date)}</b> in{" "}
        {comp.auction_venue}, after retention lists are due on {dateLabel(comp.retention_deadline)}. A mini auction: each
        franchise brings the squad it kept and the purse that leaves ({cr(comp.rules.purse)} cr in all
        {assumed.has("purse") && <>, <span className="text-gold">assumed</span>: no 2027 figure published; about 130 cr is plausible as the salary cap rises 151 → 157 cr, which adds the same to every purse left: set it with the purse box to see the plan move</>}),{" "}
        {comp.squad_min}–{comp.squad_max} players, {comp.overseas_max} overseas.{" "}
        {register ? (
          <b className="text-fg">The official auction list is loaded: the pool is exactly those players.</b>
        ) : (
          <>The pool is our guess (free agents + every plan's releases) until the official auction list is published.</>
        )}
      </Card>

      <HowItWorks res={res} />

      <Card className="p-5 print:hidden">
        <div className="mb-2 flex flex-wrap items-center gap-2 text-sm font-semibold text-fg">
          Franchise
          <InfoTip title="Your squad going in">
            The squad and purse come from Keep or release: its calls for this team, plus any Keep / Release flips you made
            there (they travel in the link). Use "Edit the squad" to change them.
          </InfoTip>
        </div>
        <div className="flex flex-wrap gap-1.5">
          {teams.map((t) => (
            <button key={t} onClick={() => pickTeam(t)}
              className={cn("rounded-lg border px-3 py-1.5 text-sm font-medium transition-all",
                t === team ? "border-accent/40 bg-accent/10 text-accent-glow shadow-glow" : "border-border bg-surface text-muted hover:text-fg")}>
              {t}
            </button>
          ))}
        </div>
        <div className="mt-4 flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-faint">
          <SlidersHorizontal className="h-3.5 w-3.5" /> Assumptions (all editable)
        </div>
        <div className="mt-2 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
          <NumberField label="Purse (every team)" value={purse} min={1} max={1000} suffix="cr"
            onChange={(v) => update({ purse: v === comp.rules.purse ? null : v })} />
          <NumberField label="Places each team opens" value={openSlots} min={0} max={25}
            hint="Every franchise's plan releases its lowest-valued players until at least this many squad places are open (0 = Keep or release's plan exactly)."
            onChange={(v) => update({ open: v === OPEN_SLOTS ? null : v })} />
          <NumberField label="Squad maximum" value={squadMax} min={11} max={40}
            onChange={(v) => update({ smax: v === comp.rules.squad_max ? null : v })} />
          <NumberField label="Squad minimum" value={squadMin} min={11} max={40}
            onChange={(v) => update({ smin: v === comp.rules.squad_min ? null : v })} />
          <NumberField label="Overseas cap" value={osMax} min={0} max={25}
            onChange={(v) => update({ os: v === comp.rules.overseas_max ? null : v })} />
          <label className="block min-w-0">
            <span className="mb-1 block truncate text-xs font-medium text-muted">Rival runs</span>
            <select className="input" value={trials} onChange={(e) => update({ trials: Number(e.target.value) === TRIALS ? null : e.target.value })}>
              {TRIAL_CHOICES.map((n) => <option key={n} value={n}>{n}</option>)}
            </select>
          </label>
        </div>
        <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
          {NEED_ORDER.map((t) => (
            <NumberField key={t} label={`${NEED_LABEL[t]} wanted`} min={0} max={12}
              value={needs[t] ?? DEFAULT_NEEDS[t]} onChange={(v) => setNeed(t, v)} />
          ))}
        </div>
        <div className="mt-4 flex flex-wrap items-center gap-2">
          <Link className="btn" to={keepLink}><Scale className="h-4 w-4" /> Edit the squad in Keep or release</Link>
          <button className="btn" onClick={download} disabled={!res}><Download className="h-4 w-4" /> Export CSV</button>
          <button className="btn" onClick={() => window.print()} disabled={!res}><Printer className="h-4 w-4" /> Print / PDF</button>
          <button className="btn" onClick={copyLink}>{copied ? <Check className="h-4 w-4" /> : <Link2 className="h-4 w-4" />} {copied ? "Copied" : "Copy link"}</button>
          <button className="btn" onClick={reset} disabled={!customised}><RotateCcw className="h-4 w-4" /> Back to defaults</button>
        </div>
      </Card>

      {!ctx ? (
        <ErrorBox message="This franchise isn't in the squads data." />
      ) : (
        <>
          <SquadGoingIn ctx={ctx} team={team} openSlots={openSlots} />
          {failed ? (
            <ErrorBox message={`The plan failed: ${failed}`} />
          ) : busy && !res ? (
            <Spinner label={`Running ${trials} rival auctions and the plan…`} />
          ) : res ? (
            <div className={cn("space-y-5 transition-opacity", busy && "opacity-60")} aria-busy={busy}>
              {busy && <div role="status" className="text-xs text-muted print:hidden">Updating the plan…</div>}
              <Summary ctx={ctx} res={res} needs={needs} overrides={overrides} />
              <Targets res={res} ctx={ctx} overrides={overrides} setOverride={setOverride} nameLink={nameLink}
                addOptions={addOptions} />
              <Chains res={res} />
              <Rivals ctx={ctx} />
              <Assumptions ctx={ctx} res={res} data={data} openSlots={openSlots} trials={trials} register={!!register} />
            </div>
          ) : null}
        </>
      )}
      <Card className="space-y-2 px-5 py-4 text-xs leading-relaxed text-muted">
        <p>
          Same squads, pool and optimiser as <code className="text-fg">cricdex bidplan --team {team}</code> on the command
          line (one implementation in Python and the browser, locked by a parity test). A model's view for discussion, not
          advice. Ratings data to the end of the 2026 IPL.
        </p>
      </Card>
    </div>
  );
}

function SquadGoingIn({ ctx, team, openSlots }: { ctx: BidContext; team: string; openSlots: number }) {
  const released = ctx.squad.filter((p) => !p.kept);
  const opened = released.filter((p) => p.auto_release === "open");
  return (
    <Card className="px-5 py-4 text-sm">
      <div className="mb-2 flex items-center gap-2 font-semibold text-fg">
        <Users className="h-4 w-4 text-accent" /> {team} going in: {ctx.kept.length} kept ({ctx.kept.filter((p) => p.os).length} overseas),{" "}
        {cr(ctx.purse_left)} cr left
      </div>
      <p className="text-xs leading-relaxed text-muted">
        <span className="text-fg">Kept:</span> {ctx.kept.map((p) => p.name).join(", ") || "nobody"}.
      </p>
      <p className="mt-1 text-xs leading-relaxed text-muted">
        <span className="text-fg">Released:</span>{" "}
        {released.length === 0
          ? "nobody"
          : released.map((p) => `${p.name}${p.auto_release === "open" ? "*" : p.overridden ? " (your call)" : ""}`).join(", ")}
        .{opened.length > 0 && <> * released to open {openSlots} places (lowest value first).</>}
      </p>
      {ctx.warnings.map((w) => (
        <div key={w} className="mt-2 flex items-start gap-2 text-xs text-fg"><AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-gold" />{w}</div>
      ))}
    </Card>
  );
}

function Summary({ ctx, res, needs, overrides }: {
  ctx: BidContext;
  res: Plan;
  needs: Partial<Record<Need, number>>;
  overrides: Record<string, number>;
}) {
  // what filling each role still short costs (bidplan gapCosts): a plan rebuilt per candidate, so only on request
  const [gaps, setGaps] = useState<{ res: Plan; rows: GapCost[] } | null>(null);
  const [pricing, setPricing] = useState(false);
  const shown = gaps && gaps.res === res ? gaps.rows : null;
  const priceGaps = () => {
    setPricing(true);
    window.setTimeout(() => {
      try {
        setGaps({ res, rows: gapCosts(ctx, res, needs, overrides) });
      } finally {
        setPricing(false);
      }
    }, 30);
  };
  return (
    <>
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <StatTile label="Purse left" value={`${cr(ctx.purse_left)} cr`} hint={`${cr(ctx.salary_kept)} cr kept salaries`} />
        <StatTile label="Open places" value={`${res.slots_open}`} hint={`${res.overseas_open} overseas · squad ${ctx.rules.squad_min}–${ctx.rules.squad_max}`} />
        <StatTile label="Strength now → expected" value={`${fmtNum(res.before.total, 1)} → ${fmtNum(res.mean_strength, 1)}`}
          hint={`best XI ${fmtNum(res.before.xi, 1)} → ${fmtNum(res.mean_xi, 1)} (runs a match above replacement)`} />
        <StatTile label="Expected spend" value={`${cr(res.mean_spend)} cr`} hint={`squad ${fmtNum(res.mean_squad, 1)} on average · λ ${fmtNum(res.lam, 2)} runs/cr`} />
      </div>
      <Card className="px-5 py-4 text-sm">
        <div className="mb-1 flex items-center gap-2 font-semibold text-fg">
          The likely squad
          <InfoTip title="The likely squad">
            Your kept players plus everyone the plan lands in at least half of the rival runs (at his average price). Each
            role need: the share of runs in which the plan meets it.
          </InfoTip>
        </div>
        <p className="text-xs leading-relaxed text-muted">
          <span className="text-fg">Likely buys ({res.likely.length}, about {cr(res.likely_spend)} cr):</span>{" "}
          {res.likely.length ? res.likely.map((x) => `${x.name} ~${cr(x.price)}`).join(", ") : "none"}.
          {" "}Strength of that squad: {fmtNum(res.after_likely.total, 0)} (best XI {fmtNum(res.after_likely.xi, 0)}
          {res.after_likely.fillers > 0 ? `, ${res.after_likely.fillers} XI place${res.after_likely.fillers === 1 ? "" : "s"} still at replacement level` : ""}).
        </p>
        <div className="mt-2 flex flex-wrap gap-1.5">
          {NEED_ORDER.map((n) => (
            <Badge key={n} tone={res.need_met[n] >= 0.9 ? "willow" : res.need_met[n] >= 0.5 ? "gold" : "ball"}>
              {NEED_LABEL[n]} {res.needs[n]}: {pct(res.need_met[n])}
            </Badge>
          ))}
        </div>
        {!res.converged && (
          <div className="mt-2 flex items-start gap-2 text-xs text-fg">
            <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-gold" />
            The likely buys didn't settle: after {res.rounds} rounds each round's likely squad still changed
            the next one's bids, so the likely buys and max bids shown are from the last round, not a fixed
            point. Treat the names near the 50% line as uncertain.
          </div>
        )}
        {res.topped_up_share > 0 && (
          <div className="mt-2 flex items-start gap-2 text-xs text-fg">
            <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-gold" />
            In {pct(res.topped_up_share)} of the runs the plan ended short of {ctx.rules.squad_min} players and
            filled the rest at the lowest base price from the accelerated rounds.
          </div>
        )}
        {res.missing.length > 0 && (
          <div className="mt-2 space-y-1">
            {res.missing.map((m) => (
              <div key={m.need} className="flex items-start gap-2 text-xs text-fg">
                <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-gold" />
                Still missing after the likely buys: {m.label.toLowerCase()} ({m.have} of {m.target}).
              </div>
            ))}
            {!shown && (
              <button className="btn mt-1 text-xs" onClick={priceGaps} disabled={pricing}>
                <Calculator className="h-3.5 w-3.5" /> {pricing ? "Rebuilding the plan…" : "What filling each one costs"}
              </button>
            )}
            {shown?.map((g) => (
              <div key={g.need} className="ml-5 text-xs text-muted">
                {g.id === null ? (
                  <>No target fills {g.label.toLowerCase()} within the purse.</>
                ) : (
                  <>
                    {g.label}: <b className="text-fg">{g.name}</b>, usually {cr(g.expected_price as number)} cr
                    ({cr(g.enough_90 as number)} cr to be sure in 9 runs of 10). Bought at that price, the best plan
                    around him is {fmtNum(Math.abs(g.cost as number), 2)} runs a match{" "}
                    {(g.cost as number) > 0 ? "weaker" : "stronger"} than this one, and has {g.label.toLowerCase()} in{" "}
                    {pct(g.need_met)} of the runs.
                  </>
                )}
              </div>
            ))}
          </div>
        )}
        {res.reconsider.length > 0 && (
          <div className="mt-3 rounded-lg border border-gold/30 bg-gold/5 px-3 py-2 text-xs text-fg">
            <div className="mb-1 flex items-center gap-1.5 font-semibold">
              <AlertTriangle className="h-3.5 w-3.5 text-gold" /> Reconsider keeping
              <InfoTip title="Why the plan never buys back your releases">
                A player you release goes into the auction, and the plan doesn't bid for him: if he's worth that much to
                you, keeping him at his salary is the cheaper route (no bidding war, no risk of losing him). These are
                your releases whose worth to the likely squad (gain ÷ λ) is at least their salary. Set your own max bid to
                chase one anyway.
              </InfoTip>
            </div>
            {res.reconsider.map((x) => (
              <div key={x.id}>
                {x.name}: worth about {cr(x.worth)} cr to your squad, paid {cr(x.salary)} cr
                {x.auto_release === "open" ? " (released only to open a place)" : ""}.
              </div>
            ))}
          </div>
        )}
        {res.slots_open <= 0 && (
          <div className="mt-2 flex items-start gap-2 text-xs text-fg">
            <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-gold" />
            No open places: release players in Keep or release, or raise "Places each team opens".
          </div>
        )}
      </Card>
    </>
  );
}

function Targets({ res, ctx, overrides, setOverride, nameLink, addOptions }: {
  res: Plan;
  ctx: BidContext;
  overrides: Record<string, number>;
  setOverride: (id: string, v: number | null) => void;
  nameLink: (id: string, name: string) => JSX.Element;
  addOptions: { value: string; label: string; hint?: string }[];
}) {
  const extra = Object.keys(overrides).filter((id) => !res.targets.some((t) => t.id === id));
  const nameOf = new Map(ctx.available.map((r) => [r.cricsheet_id, r.name]));
  return (
    <Card className="overflow-hidden">
      <CardHeader
        title={`Targets: ${res.targets.length}, in priority order`}
        subtitle="Max bid is the most he's worth to your likely squad; type over it to set your own (blank = ours, 0 = never bid). Everything updates."
        right={
          <InfoTip title="Reading the table">
            <b>Rivals pay</b>: the middle of the prices rivals would pay across the runs (the price to beat).{" "}
            <b>Usually enough</b>: a bid that wins him in 9 runs of 10. <b>Max bid</b> is your walk-away price: what he
            is worth to your squad (in an open auction you keep bidding while the price is below that); expect to pay
            near "rivals pay".{" "}
            <b>P(≤ max)</b>: the share of runs in which your max bid is enough. <b>In plan</b>: how often the bidding rule
            actually lands him (it can't buy everyone: purse, places and overseas slots run out).{" "}
            <b>Gain</b>: what he adds to the likely squad's strength. A "purse" max bid is cut to what the purse leaves after
            the other likely buys. <b>Market price</b> is the fitted model's median for players like him, with the chance a
            franchise buys him at all.
          </InfoTip>
        }
      />
      <div className="overflow-auto">
        <table className="w-full border-collapse">
          <thead>
            <tr>
              <th className="th text-right">#</th>
              <th className="th">Player</th>
              <th className="th">Slot</th>
              <th className="th text-right">Value</th>
              <th className="th text-right">Market price</th>
              <th className="th text-right">Rivals pay</th>
              <th className="th text-right">Usually enough</th>
              <th className="th text-right">Max bid</th>
              <th className="th text-right print:hidden">Your max</th>
              <th className="th text-right">P(≤ max)</th>
              <th className="th text-right">In plan</th>
              <th className="th text-right">Gain</th>
            </tr>
          </thead>
          <tbody>
            {res.targets.map((x) => (
              <tr key={x.id} className="hover:bg-surface/50">
                <td className="td stat-num text-right text-muted">{x.priority}</td>
                <td className="td">
                  <div className="flex items-center gap-1.5 whitespace-nowrap">
                    {nameLink(x.id, x.name)}
                    {x.overseas && <Plane className="h-3 w-3 shrink-0 text-willow" aria-label="overseas" />}
                    {x.likely && <Badge tone="willow">likely</Badge>}
                    {x.eligibility && (
                      <span title={x.eligibility}>
                        <Badge tone="gold">eligibility?</Badge>
                      </span>
                    )}
                  </div>
                  <div className="mt-0.5 text-[11px] text-muted">
                    {ROLE_LABEL[x.role] ?? x.role} · {x.from_team ? (x.from_team === ctx.team ? "released by you" : `released by ${x.from_team}`) : "free agent"}
                  </div>
                  {x.eligibility && <div className="mt-0.5 max-w-[22rem] whitespace-normal text-[11px] text-gold">{x.eligibility}</div>}
                </td>
                <td className="td whitespace-nowrap text-xs text-muted">{SLOT_LABEL[x.slot]}</td>
                <td className="td stat-num whitespace-nowrap text-right">
                  {x.value_now !== null && x.value_now !== undefined ? (
                    <>
                      {fmtNum(x.value_now, 1)}
                      <div className="text-[11px] text-muted">career {fmtNum(x.value, 1)}</div>
                    </>
                  ) : x.value === null || x.value === undefined ? "—" : fmtNum(x.value, 1)}
                </td>
                <td className="td stat-num whitespace-nowrap text-right">
                  {cr(x.price)}
                  {x.p_bought !== null && x.p_bought !== undefined && <div className="text-[11px] text-muted">{pct(x.p_bought)} bought</div>}
                </td>
                <td className="td stat-num text-right">{cr(x.expected_price)}</td>
                <td className="td stat-num text-right text-muted">{cr(x.enough_90)}</td>
                <td className="td stat-num whitespace-nowrap text-right font-semibold text-fg">
                  {cr(x.max_bid)}
                  {x.override ? <div className="text-[10px] font-normal text-gold">yours</div> : x.purse_bound ? <div className="text-[10px] font-normal text-muted">purse</div> : null}
                </td>
                <td className="td text-right print:hidden">
                  <MaxBidInput value={x.max_bid} mine={x.override} onCommit={(v) => setOverride(x.id, v)} />
                </td>
                <td className={cn("td stat-num text-right", x.p_le_max >= 0.8 ? "text-willow" : x.p_le_max >= 0.4 ? "text-gold" : "text-ball")}>{pct(x.p_le_max)}</td>
                <td className="td stat-num text-right text-muted">{pct(x.p_land)}</td>
                <td className="td stat-num text-right">{fmtNum(x.gain, 1)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="flex flex-wrap items-center gap-3 border-t border-border px-5 py-3 print:hidden">
        <span className="text-xs text-muted">Bid for someone else:</span>
        <Combobox className="w-full max-w-xs" options={addOptions} value={null} label="Add a player with your own max bid"
          placeholder="Add a player…" onChange={(id) => id && setOverride(id, Math.max(0.3, ctx.available.find((r) => r.cricsheet_id === id)?.projected_value ?? 0.3))} />
        {extra.map((id) => (
          <span key={id} className="inline-flex items-center gap-1 text-xs text-muted">
            <Badge tone="gold">{nameOf.get(id) ?? id}: {cr(overrides[id])} cr{overrides[id] === 0 ? " (never)" : ""}</Badge>
            <button aria-label={`Remove your max bid for ${nameOf.get(id) ?? id}`} onClick={() => setOverride(id, null)} className="text-muted hover:text-fg"><X className="h-3.5 w-3.5" /></button>
          </span>
        ))}
      </div>
    </Card>
  );
}

function Chains({ res }: { res: Plan }) {
  return (
    <Card className="overflow-hidden">
      <CardHeader
        title="Fallback chains"
        subtitle="Per role, in priority order: if a name goes above his max bid, the next one is worth this much to you"
        right={
          <InfoTip title="How a chain reads">
            Each step's max bid assumes every name before it in the chain went for more than his max: the gap he leaves
            makes the next player worth more to you (up to what the purse allows). The percentage is the share of rival runs
            in which that bid is enough.
          </InfoTip>
        }
      />
      <div className="divide-y divide-border">
        {res.chains.length === 0 && <div className="px-5 py-4 text-sm text-muted">No targets yet.</div>}
        {res.chains.map((ch) => (
          <div key={ch.slot} className="flex flex-col gap-2 px-5 py-3 sm:flex-row sm:items-start">
            <div className="w-40 shrink-0 text-sm font-semibold text-fg">{ch.label}</div>
            <div className="flex flex-wrap items-center gap-1.5 text-sm">
              {ch.steps.map((s, k) => (
                <span key={s.id} className="inline-flex items-center gap-1.5">
                  {k > 0 && <ArrowRight className="h-3.5 w-3.5 text-faint" aria-label="if he goes above that" />}
                  <span className="rounded-lg border border-border bg-surface px-2 py-1">
                    <span className="text-fg">{s.name}</span>{" "}
                    <span className="stat-num font-semibold text-accent-glow">≤ {cr(s.max_bid)} cr</span>{" "}
                    <span className="text-[11px] text-muted">({pct(s.p_le_max)})</span>
                  </span>
                </span>
              ))}
            </div>
          </div>
        ))}
      </div>
    </Card>
  );
}

function Rivals({ ctx }: { ctx: BidContext }) {
  return (
    <Collapsible title="The nine rivals in the simulation" icon={<Users className="h-4 w-4" />}>
      <div className="overflow-auto">
        <table className="w-full border-collapse text-sm">
          <thead>
            <tr>
              <th className="th">Team</th>
              <th className="th text-right">Kept</th>
              <th className="th text-right">Open places</th>
              <th className="th text-right">Purse left</th>
            </tr>
          </thead>
          <tbody>
            {ctx.rivals.map((r) => (
              <tr key={r.team}>
                <td className="td font-medium text-fg">{r.team}</td>
                <td className="td stat-num text-right">{r.kept.length}</td>
                <td className="td stat-num text-right">{Number(ctx.rules.squad_max) - r.kept.length}</td>
                <td className="td stat-num text-right">{cr(r.purse_left)} cr</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="mt-3 text-xs text-muted">
        Each keeps Keep or release's default calls for its squad, opens the same number of places, and bids by the Auction
        room's fitted demand model (its squad, overseas places and purse at each lot). {ctx.available.length} players are in the pool.
      </p>
    </Collapsible>
  );
}

function Assumptions({ ctx, res, data, openSlots, trials, register }: {
  ctx: BidContext; res: Plan; data: KeepData; openSlots: number; trials: number; register: boolean;
}) {
  const c = data.competition;
  const assumed = new Set(c.assumed);
  const rows: [string, string, boolean][] = [
    ["Purse", `${cr(ctx.rules.purse)} cr per team`, assumed.has("purse")],
    ["Squad", `${ctx.rules.squad_min}–${ctx.rules.squad_max} players, ${ctx.rules.overseas_max} overseas`, assumed.has("squad_min")],
    ["Places each team opens", openSlots ? `at least ${openSlots}, lowest-valued players released first` : "none: Keep or release's plans exactly", true],
    ["The pool", register ? "the official auction list" : "free agents + every plan's releases (our guess)", !register],
    ["Rivals", `the Auction room's simulator, ${trials} runs, its fitted demand model`, false],
    ["Best XI", `≤ ${XI_OVERSEAS} overseas, a keeper, 5 bowling and 6 batting options`, false],
    ["Replacement level", `${fmtNum(REPLACEMENT, 0)} (contributions are runs a match above it)`, false],
    ["XI balls", `held to ${TEAM_BALLS} a side's innings, faced and bowled`, false],
    ["Depth", "the bench fills the matches the XI misses (its chance of playing); role needs reported, not scored", false],
    ["Exchange rate λ", `${fmtNum(res.lam, 2)} runs per crore at the start (what a crore still buys; it changes lot by lot)`, false],
    ["Unspent purse", "worth what the later lots can still buy at their expected prices; nothing after the auction", false],
    ["Plan converged", res.converged ? `yes, in ${res.rounds} round${res.rounds === 1 ? "" : "s"}` : `stopped after ${res.rounds} rounds`, false],
  ];
  return (
    <Collapsible title="Every assumption behind this plan" icon={<SlidersHorizontal className="h-4 w-4" />}>
      <div className="grid grid-cols-1 gap-x-6 gap-y-1.5 text-sm sm:grid-cols-2">
        {rows.map(([k, v, a]) => (
          <div key={k} className="flex flex-wrap items-baseline gap-x-2">
            <span className="text-muted">{k}:</span>
            <span className="font-medium text-fg">{v}</span>
            {a && <Badge tone="gold">assumed</Badge>}
          </div>
        ))}
      </div>
      <p className="mt-3 text-xs leading-relaxed text-muted">
        Rules come from <code className="text-fg">config/competitions.toml</code> (sources on the Keep or release page). The
        model's constants are in <code className="text-fg">src/cricdex/web_parity/bidplan.py</code> ⇄{" "}
        <code className="text-fg">site/src/lib/bidplan.ts</code>.
      </p>
    </Collapsible>
  );
}
