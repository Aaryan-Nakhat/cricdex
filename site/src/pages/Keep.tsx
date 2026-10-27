import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { Scale, Calculator, Download, Link2, RotateCcw, Plane, ScrollText, AlertTriangle, Check, ClipboardList } from "lucide-react";
import { useAsync } from "@/lib/useAsync";
import { getAuctionPool, getKeep } from "@/lib/data";
import { buildPool } from "@/lib/auction";
import {
  BORDER_BAND,
  DEFAULT_NEEDS,
  KEEP_CALL,
  FORECAST_FLAG,
  TAG_LABEL,
  TAG_ORDER,
  cr,
  crExact,
  evaluate,
  fmtNum,
  marketFor,
  signed,
  toCsv,
  toCsvRows,
  type AssessedPlayer,
  type Decision,
  type KeepData,
  type Tag,
  NO_DATA_LABEL,
  SHOULD_LABEL,
} from "@/lib/keep";
import { useUrlParams, useUrlState } from "@/lib/useUrlState";
import { PageTitle, Card, CardHeader, Spinner, Badge, Empty, InfoTip, Collapsible, ErrorBox, StatTile } from "@/components/ui";
import { cn, profilePath } from "@/lib/utils";

type SortKey = "kept" | "should" | "surplus" | "price" | "onfield" | "outlook" | "salary" | "value" | "age" | "name";
const SORTS: SortKey[] = ["kept", "should", "surplus", "price", "onfield", "outlook", "salary", "value", "age", "name"];

const REC_TONE = { keep: "willow", release: "ball", borderline: "gold" } as const;
const REC_LABEL = { keep: "Keep", release: "Release", borderline: "Borderline" } as const;
const SHOULD_TONE = { yes: "willow", no: "ball", close: "gold" } as const;
const ROLE_LABEL: Record<string, string> = { batter: "Batter", bowler: "Bowler", all_rounder: "All-rounder", keeper: "Keeper" };
const FIELD_LABEL: Record<string, string> = {
  retention_deadline: "Retention deadline",
  auction_date: "Auction date",
  auction_venue: "Auction venue",
  purse: "Purse",
  squad_min: "Squad minimum",
  squad_max: "Squad maximum",
  overseas_max: "Overseas cap",
  max_retained: "Retention limit",
  max_overseas_retained: "Overseas retention limit",
  rtm_cards: "Right-to-match cards",
  retained_cost: "What a kept player costs",
  replacements_retainable: "Replacement signings keepable",
  overseas_fee_cap: "Overseas fee cap",
  min_purse_spend_share: "Minimum spend",
  general: "Background",
};

const dateLabel = (iso: string) =>
  new Date(`${iso}T00:00:00`).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });

/** "id1,id2" ↔ Set, for the keep / release overrides in the URL. */
const splitIds = (s: string) => new Set(s.split(",").map((x) => x.trim()).filter(Boolean));

function NumberField({ label, value, onChange, min = 0, max = 999, step = 1, suffix }: {
  label: string; value: number; onChange: (v: number) => void; min?: number; max?: number; step?: number; suffix?: string;
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
    <label className="block min-w-0">
      <span className="mb-1 block truncate text-xs font-medium text-muted">{label}</span>
      <div className="flex items-center gap-2">
        <input type="number" className="input" value={text} min={min} max={max} step={step}
          onChange={(e) => setText(e.target.value)} onBlur={commit} onKeyDown={(e) => e.key === "Enter" && commit()} />
        {suffix && <span className="text-xs text-muted">{suffix}</span>}
      </div>
    </label>
  );
}

function HowItWorks({ data }: { data: KeepData }) {
  const f = data.form;
  return (
    <Collapsible title="How each number is computed (plain English)" icon={<Calculator className="h-4 w-4" />}>
      <div className="space-y-4 text-sm leading-relaxed text-muted">
        <p>
          <b className="text-fg">Value</b> is the player's skill from the Bayesian model, in{" "}
          <b>runs per 100 balls</b> above an average IPL ball (+10 = ten runs better every 100 balls; the best
          regulars sit around +20 to +25). Batters get the runs they add plus the wickets they don't lose, priced
          in runs where they bat; bowlers the runs they save plus their extra wickets. The ± is the model's
          uncertainty: a short record has a wide one. It is the same value the Auction room's pool uses
          (several leagues blended for a thin IPL record).
        </p>
        <p>
          <b className="text-fg">Market price</b> is what players like him have fetched at real IPL auctions: a
          model fitted to every sale 2018–2026 (Wikipedia's personnel pages) on his value, international caps
          (all, and in the last two years), age, IPL experience, captaincy and the auction type, with each
          mega-auction retention counted as a <b>floor</b> (the franchise paid at least that to keep him, so his
          worth is at least that), at the median for his kind of player. It uses a <b>cautious</b> value
          (value − ½ × uncertainty). At the top it follows what the market really paid for the dearest lots
          (a monotone calibration fitted out of fold), not a straight-line extrapolation, so it needs no
          ceiling. Under it, the chance a franchise buys a player like him if he's released (which also
          weighs the price he last fetched). The recipe was chosen on auctions up to 2024. On the 2025–26
          auctions it is off by a factor of about 1.9 on a typical player, but those two seasons have since
          been looked at several times while building CricDex, so treat that figure as optimistic. <b className="text-fg">On-field worth</b> is the older
          skill-only curve (4.03 × e^(0.0743 × cautious value) × role weight), shown for comparison only.
        </p>
        <pre className="overflow-auto rounded-lg border border-border bg-bg/60 px-3 py-2 font-mono text-xs leading-relaxed text-fg">{`market price = purse × e^(calibrated ln share of the purse)   (at least 0.3 cr)
upper figure = the upper quartile of that ≈ 2 × market price
cost         = what keeping him takes from the purse: his salary, or for a 2025
               retention what releasing him would free (retention slabs)
P(kept)      = the chance a franchise keeps a player like him, from market price
               vs cost, his 3-season Form forecast, his ties to the franchise and
               his status (fitted on every retention deadline 2018-2026)`}</pre>
        <p>
          <b className="text-fg">The call</b> is what franchises actually do. A model fitted to every real
          retention deadline since 2018 (who each franchise kept from its squad, and who it let go) gives the
          chance a franchise keeps a player like him, from: his market price against what keeping him costs;
          his three-season Form forecast (its average and the chance he is still a regular); whether he
          captained the side last season, his seasons there and whether it was his first IPL side; whether he
          is a capped Indian or overseas, his age, his IPL balls, whether he was bought at the last auction,
          and how much he costs. <Badge tone="willow">Keep</Badge> at {Math.round((KEEP_CALL + BORDER_BAND) * 100)}% or more,{" "}
          <Badge tone="ball">Release</Badge> below {Math.round((KEEP_CALL - BORDER_BAND) * 100)}%,{" "}
          <Badge tone="gold">Borderline</Badge> in between (a close call); the default plan keeps him from{" "}
          {Math.round(KEEP_CALL * 100)}%. The model was chosen on the deadlines up to 2024. On the 2025 and 2026
          deadlines it made the franchise's own call for 78% of the players (82% of the stars), against 70%
          (64%) for the old rule that set the price against the salary with a fixed margin; keeping everyone
          the rules allow scores 75% (75%), so the gain is in telling which stars go. Those two seasons have
          since been looked at up to five times while building CricDex, so treat these numbers as optimistic.
          A player we can't price at all (too few balls, no market inputs) is Borderline: scout him.
        </p>
        <p>
          <b className="text-fg">Should they?</b> The call copies what franchises do, and in a mini year they
          hardly weigh the cost: in the fitted model a dear retention looks about as likely as a cheap one. So
          this column asks the other question, from the market price alone: is he worth what keeping him
          costs? <Badge tone="willow">Yes</Badge> when players like him fetch at least that cost at auction
          (the median market price), <Badge tone="ball">No</Badge> when even the dearer quarter of players
          like him fetch less (the upper figure), <Badge tone="gold">Close</Badge> in between (about the price's
          typical error). It sees no scouting, so a surprise uncapped buy can read No when the franchise
          knows better.
        </p>
        <p>
          <b className="text-fg">Age and outlook</b> are at the auction date, from the player master's date of birth,
          with the shape of his Form forecast (holds, improves, declines).
        </p>
        <p>
          <b className="text-fg">Last season</b> is the raw {f?.season ?? "latest"} IPL numbers, not the model: strike rate
          {f ? ` (league ${fmtNum(f.bat_sr, 0)})` : ""} for batters, economy
          {f ? ` (league ${fmtNum(f.bowl_econ, 1)})` : ""} and wickets for bowlers, from 30 balls up.
        </p>
        <p>
          <b className="text-fg">The squad.</b> Purse left = the purse − what the players you keep cost it. In a
          mini year a kept player stays on his contract; a player his franchise retained at the 2025 mega auction
          is charged by the retention slabs instead (18, 14, 11, 18, 14 cr for the 1st–5th capped, 4 cr
          uncapped; the team's retentions together cost the first slabs for as many as it keeps, or their
          salaries if those add up to more; that is how every team's 2025 and 2026 purse was charged).{" "}
          <b className="text-gold">Assumed</b> for 2027: the 2025 slabs carry on until the BCCI publishes the 2027
          rules. So keeping one costs what releasing him alone would free. Open slots = the squad maximum − kept. Each <b>role gap</b> (keepers,
          openers, death bowlers, spinners, overseas) is your target minus the kept players with that tag. It is
          filled from the likely <b>auction pool</b>: today's free agents plus the players our calls release from
          the other nine squads, cheapest first (at our estimated price), among those at least as good as the best
          player you released in that role, by runs above a replacement per match (batting and bowling at the balls
          he gets; a replacement-level player, 0, if you released none), respecting
          open slots and overseas room; a player who fills two gaps counts for both. A death bowler bowls{" "}
          {Math.round(data.death_rule.share * 100)}%+ of his balls in overs 16–20 ({data.death_rule.min_balls}+ such
          balls, every league we have); an opener is tagged so in the player master; spinners by bowling type.
        </p>
        <p className="rounded-lg border border-willow/20 bg-willow/5 px-3 py-2 text-xs">
          <b className="text-willow">Honest caveat:</b> the market price is fitted to real auctions but is rough
          and sees no fitness or brand, so the useful part is the comparison (who is paid well above
          or below what players like him fetch), not the exact crore. Every
          assumption is editable: flip any player, change the purse or a role target, and the squad numbers update.
        </p>
      </div>
    </Collapsible>
  );
}

function Rules({ data }: { data: KeepData }) {
  const c = data.competition;
  const assumed = new Set(c.assumed);
  const facts: { key: string; value: string }[] = [
    { key: "retention_deadline", value: dateLabel(c.retention_deadline) },
    { key: "auction_date", value: `${dateLabel(c.auction_date)}, ${c.auction_venue}` },
    { key: "purse", value: `${cr(c.purse)} ${c.unit} per team` },
    { key: "squad_max", value: `${c.squad_min}–${c.squad_max} players` },
    { key: "overseas_max", value: `${c.overseas_max} overseas` },
    { key: "max_retained", value: c.max_retained ? String(c.max_retained) : "none: keep any number" },
    { key: "rtm_cards", value: c.rtm_cards ? String(c.rtm_cards) : "none in a mini auction" },
    {
      key: "retained_cost",
      value:
        c.retained_cost === "salary"
          ? "his current salary, out of the purse"
          : `his salary; a 2025 retention by the slabs (${(c.retention_slabs ?? []).map((x) => cr(x)).join(" / ")} cr capped, ${cr(c.uncapped_retention_slab ?? 0)} uncapped)`,
    },
    { key: "overseas_fee_cap", value: c.overseas_fee_cap ? `${cr(c.overseas_fee_cap)} ${c.unit} paid to an overseas buy` : "none" },
    { key: "replacements_retainable", value: c.replacements_retainable ? "yes" : "no" },
    { key: "min_purse_spend_share", value: c.min_purse_spend_share ? `${Math.round(c.min_purse_spend_share * 100)}%` : "no rule" },
  ];
  const isAssumed = (k: string) => assumed.has(k) || (k === "squad_max" && assumed.has("squad_min"));
  return (
    <Collapsible title={`The rules for ${c.name}, and where they come from`} icon={<ScrollText className="h-4 w-4" />}>
      <div className="space-y-4 text-sm">
        <div className="grid grid-cols-1 gap-x-6 gap-y-1.5 sm:grid-cols-2">
          {facts.map((f) => (
            <div key={f.key} className="flex flex-wrap items-baseline gap-x-2">
              <span className="text-muted">{FIELD_LABEL[f.key]}:</span>
              <span className="font-medium text-fg">{f.value}</span>
              {isAssumed(f.key) && <Badge tone="gold">assumed</Badge>}
            </div>
          ))}
        </div>
        <p className="text-xs leading-relaxed text-muted">
          <Badge tone="gold">assumed</Badge> marks a number no official or press source confirms yet; it is our
          editable default (the purse field below, a role target). Rules live in{" "}
          <code className="text-fg">config/competitions.toml</code>; another league's cycle is one more entry there.
        </p>
        <ul className="space-y-2 text-xs leading-relaxed text-muted">
          {c.source.map((s, i) => (
            <li key={i}>
              <span className="font-semibold text-fg">{FIELD_LABEL[s.about] ?? s.about}</span>{" "}
              <Badge tone={s.status === "official" ? "willow" : "muted"}>{s.status}</Badge>{" "}
              <a href={s.url} target="_blank" rel="noreferrer" className="text-accent-glow underline-offset-2 hover:underline">
                {s.title}
              </a>
              {s.date && <span> ({dateLabel(s.date)})</span>}
              {s.note && <span>. {s.note}</span>}
            </li>
          ))}
        </ul>
      </div>
    </Collapsible>
  );
}

export function Keep() {
  const keep = useAsync(() => getKeep("ipl"), []);
  const poolData = useAsync(() => getAuctionPool("ipl"), []);
  const data = keep.data;

  return (
    <>
      <PageTitle
        title="Keep or release"
        icon={<Scale className="h-6 w-6" />}
        desc="Which players should a franchise keep before the retention deadline? For each one: what his game would fetch at auction against what he's paid, a Keep / Release / Borderline call (what franchises likely do) with the reason, whether he's worth his cost, and what the squad looks like if you follow it: purse left, role gaps and what filling them costs."
      />
      {keep.error || poolData.error ? (
        <ErrorBox message={(keep.error || poolData.error)!} />
      ) : !data || !poolData.data ? (
        <Spinner label="Loading the squads…" />
      ) : data.players.length === 0 ? (
        <Empty>No squads exported yet.</Empty>
      ) : (
        <KeepCalculator data={data} pool={poolData.data} />
      )}
    </>
  );
}

function KeepCalculator({ data, pool }: { data: KeepData; pool: Parameters<typeof buildPool>[0] }) {
  const comp = data.competition;
  const teams = data.teams;
  const [team] = useUrlState<string>("team", teams[0] ?? "", { valid: teams, replace: false });
  const [sort, setSort] = useUrlState<SortKey>("sort", "kept", { valid: SORTS });
  const { params, update } = useUrlParams();
  const keepIds = useMemo(() => splitIds(params.get("keep") ?? ""), [params]);
  const relIds = useMemo(() => splitIds(params.get("rel") ?? ""), [params]);
  const purseParam = Number(params.get("purse"));
  const purse = Number.isFinite(purseParam) && purseParam > 0 && purseParam <= 1000 ? purseParam : comp.rules.purse;
  const needs = useMemo(() => {
    const out: Partial<Record<Tag, number>> = {};
    for (const part of (params.get("need") ?? "").split(",")) {
      const [k, v] = part.split(":");
      if ((TAG_ORDER as string[]).includes(k) && /^\d{1,2}$/.test(v ?? "")) out[k as Tag] = Number(v);
    }
    return out;
  }, [params]);
  const [copied, setCopied] = useState(false);

  const market = useMemo(
    () => marketFor(team, data.players, buildPool(pool), data.pool_tags, data.form, comp.rules),
    [team, data.players, pool, data.pool_tags, data.form, comp.rules],
  );
  const squad = useMemo(() => data.players.filter((p) => p.team === team), [data.players, team]);
  const decisions = useMemo(() => {
    const d: Record<string, Decision> = {};
    for (const k of keepIds) d[k] = "keep";
    for (const k of relIds) d[k] = "release";
    return d;
  }, [keepIds, relIds]);
  const rules = useMemo(() => ({ ...comp.rules, purse }), [comp.rules, purse]);
  const res = useMemo(
    () => evaluate(squad, market, rules, decisions, needs, data.form),
    [squad, market, rules, decisions, needs, data.form],
  );

  const writeIds = useCallback(
    (k: Set<string>, r: Set<string>) => update({ keep: [...k].join(",") || null, rel: [...r].join(",") || null }),
    [update],
  );
  const flip = (p: AssessedPlayer, to: Decision) => {
    const k = new Set(keepIds);
    const r = new Set(relIds);
    k.delete(p.key);
    r.delete(p.key);
    const def = p.rec !== "release" ? "keep" : "release";
    if (to !== def) (to === "keep" ? k : r).add(p.key);
    writeIds(k, r);
  };
  const setNeed = (t: Tag, v: number) => {
    const next = { ...needs, [t]: v };
    const def: Record<string, number> = { ...DEFAULT_NEEDS, overseas: Math.min(comp.rules.overseas_max, squad.filter((p) => p.overseas).length) };
    const parts = TAG_ORDER.filter((x) => next[x] !== undefined && next[x] !== def[x]).map((x) => `${x}:${next[x]}`);
    update({ need: parts.join(",") || null });
  };
  // a team switch starts clean: the overrides are per player of that squad
  const pickTeam = (t: string) =>
    update({ team: t === teams[0] ? null : t, keep: null, rel: null, need: null }, { replace: false });
  const reset = () => update({ keep: null, rel: null, need: null, purse: null });
  // Bid plan reads the same keys, so your calls carry over
  const bidPlanLink = (() => {
    const q = new URLSearchParams();
    for (const k of ["team", "keep", "rel", "purse", "need"]) {
      const v = params.get(k);
      if (v) q.set(k, v);
    }
    const s = q.toString();
    return `/bidplan${s ? `?${s}` : ""}`;
  })();

  const rows = useMemo(() => {
    const val = (p: AssessedPlayer): number | null =>
      sort === "kept" ? p.p_keep : sort === "should" ? (p.price === null || p.cost <= 0 ? null : p.price / p.cost) : sort === "surplus" ? p.surplus : sort === "price" ? p.price : sort === "onfield" ? p.onfield : sort === "outlook" ? p.forecast_avg3 : sort === "salary" ? p.salary : sort === "value" ? p.value : sort === "age" ? p.age : null;
    return [...res.players].sort((a, b) => {
      if (sort === "name") return a.name.localeCompare(b.name);
      const x = val(a);
      const y = val(b);
      if (x === null || x === undefined) return y === null || y === undefined ? 0 : 1;
      if (y === null || y === undefined) return -1;
      return y - x;
    });
  }, [res.players, sort]);

  const download = () => {
    const blob = new Blob([toCsv(toCsvRows(res))], { type: "text/csv;charset=utf-8" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `keep-or-release-${team}-${comp.key}.csv`;
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
  const daysLeft = Math.ceil((new Date(`${comp.retention_deadline}T23:59:59`).getTime() - Date.now()) / 86400000);
  const overseasDefault = Math.min(comp.rules.overseas_max, squad.filter((p) => p.overseas).length);
  const check = data.purse_check.teams[team];
  const changes = data.changes.filter((c) => c.to === team || c.from === team || c.team === team);
  const unmatched = data.unmatched.filter((u) => u.team === team);
  const SortTh = ({ k, children, className }: { k: SortKey; children: React.ReactNode; className?: string }) => (
    <th className={cn("th", className)}>
      <button onClick={() => setSort(k)} className={cn("inline-flex items-center gap-1 hover:text-fg", sort === k && "text-accent-glow")}>
        {children}
        {sort === k && <span aria-hidden>{k === "name" ? "↑" : "↓"}</span>}
      </button>
    </th>
  );

  return (
    <div className="space-y-5">
      <Card className="px-5 py-4 text-sm leading-relaxed text-muted">
        <span className="font-semibold text-fg">{comp.name}: </span>
        retention lists are due <b className="text-fg">{dateLabel(comp.retention_deadline)}</b>
        {daysLeft >= 0 ? ` (${daysLeft} day${daysLeft === 1 ? "" : "s"} away)` : " (passed)"}; the auction is{" "}
        {assumed.has("auction_date") ? "likely " : ""}on <b className="text-fg">{dateLabel(comp.auction_date)}</b> in{" "}
        {comp.auction_venue}. A mini year: keep as many as you like (up to {comp.squad_max}, {comp.overseas_max} overseas),
        each at his current salary (a 2025 retention at his retention slab
        {assumed.has("retained_cost") && <>, <span className="text-gold">assumed</span> to carry into 2027</>}) out of a{" "}
        <b className="text-fg">{cr(comp.rules.purse)} cr</b> purse
        {assumed.has("purse") && <> (<span className="text-gold">assumed</span>: no 2027 figure published)</>}, and no
        right-to-match card to buy anyone back.
      </Card>

      <Rules data={data} />
      <HowItWorks data={data} />

      <Card className="p-5">
        <div className="mb-2 flex items-center gap-2 text-sm font-semibold text-fg">Franchise</div>
        <div className="flex flex-wrap gap-1.5">
          {teams.map((t) => (
            <button key={t} onClick={() => pickTeam(t)}
              className={cn("rounded-lg border px-3 py-1.5 text-sm font-medium transition-all",
                t === team ? "border-accent/40 bg-accent/10 text-accent-glow shadow-glow" : "border-border bg-surface text-muted hover:text-fg")}>
              {t}
            </button>
          ))}
        </div>
        <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
          <NumberField label="Purse" value={purse} min={1} max={1000} step={1} suffix="cr"
            onChange={(v) => update({ purse: v === comp.rules.purse ? null : v })} />
          {TAG_ORDER.map((t) => (
            <NumberField key={t} label={`${TAG_LABEL[t]} wanted`} min={0} max={t === "overseas" ? comp.rules.overseas_max : 12}
              value={needs[t] ?? (t === "overseas" ? overseasDefault : DEFAULT_NEEDS[t as keyof typeof DEFAULT_NEEDS])}
              onChange={(v) => setNeed(t, v)} />
          ))}
        </div>
        <div className="mt-4 flex flex-wrap gap-2">
          <button className="btn" onClick={download}><Download className="h-4 w-4" /> Export CSV</button>
          <button className="btn" onClick={copyLink}>{copied ? <Check className="h-4 w-4" /> : <Link2 className="h-4 w-4" />} {copied ? "Copied" : "Copy link"}</button>
          <button className="btn" onClick={reset} disabled={!keepIds.size && !relIds.size && !params.get("need") && !params.get("purse")}>
            <RotateCcw className="h-4 w-4" /> Back to our calls
          </button>
          <Link className="btn" to={bidPlanLink}>
            <ClipboardList className="h-4 w-4" /> Plan the auction bids
          </Link>
        </div>
      </Card>

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <StatTile label="Purse left" value={`${cr(res.purse_left)} cr`} hint={`${cr(res.purse)} − ${cr(res.purse_charged)} for the kept players`} />
        <StatTile label="Kept / released" value={`${res.kept} / ${res.released}`} hint={`${res.overseas_kept} overseas kept · frees ${cr(res.salary_released)} cr`} />
        <StatTile label="Slots open" value={`${res.slots_left}`} hint={`${res.overseas_slots_left} overseas · squad ${comp.rules.squad_min}–${comp.rules.squad_max}`} />
        <StatTile label="After filling gaps" value={`${cr(res.purse_after_replacements)} cr`} hint={(() => { const n = res.gaps.reduce((s, g) => s + g.picks.length, 0); return `${cr(res.replacement_cost)} cr on ${n} replacement${n === 1 ? "" : "s"}`; })()} />
      </div>
      {res.warnings.length > 0 && (
        <Card className="space-y-1 border-gold/30 bg-gold/5 px-4 py-3 text-sm">
          {res.warnings.map((w) => (
            <div key={w} className="flex items-start gap-2 text-fg"><AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-gold" />{w}</div>
          ))}
        </Card>
      )}

      <Card className="overflow-hidden">
        <CardHeader
          title={`${team} squad: ${res.players.length} players`}
          subtitle="Likely call = what franchises do with players like him. Should they? = is he worth what keeping him costs (Yes if he'd fetch at least that at auction, No if even the dearer quarter of players like him fetch less). Click a column to sort; Keep / Release flips our call (the purse and gaps update, and the link keeps it)."
        />
        <div className="overflow-auto">
          <table className="w-full border-collapse">
            <thead>
              <tr>
                <SortTh k="name">Player</SortTh>
                <SortTh k="age" className="text-right">Age</SortTh>
                <SortTh k="salary" className="text-right">Salary</SortTh>
                <SortTh k="value" className="text-right">
                  Value
                </SortTh>
                <SortTh k="price" className="text-right">Market price</SortTh>
                <SortTh k="onfield" className="text-right">On-field worth</SortTh>
                <SortTh k="surplus" className="text-right">Surplus</SortTh>
                <SortTh k="outlook" className="text-right">3-season outlook</SortTh>
                <SortTh k="kept" className="text-right">Kept by franchises</SortTh>
                <th className="th">Likely call</th>
                <SortTh k="should">Should they?</SortTh>
                <th className="th">Decision</th>
                <th className="th">Why</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((p) => (
                <tr key={p.key} className={cn("hover:bg-surface/50", !p.kept && "opacity-70")}>
                  <td className="td">
                    <div className="flex items-center gap-1.5">
                      {p.id ? (
                        <Link to={profilePath(p.id, p.profile ?? "ipl")} className="font-medium text-fg hover:text-accent-glow">{p.name}</Link>
                      ) : (
                        <span className="font-medium text-fg">{p.name}</span>
                      )}
                      {p.overseas && <Plane className="h-3 w-3 shrink-0 text-willow" aria-label="overseas" />}
                      {p.captain && <span title={`Captained ${p.captain} last season (the market pays captains a premium)`}><Badge tone="gold">Captain</Badge></span>}
                    </div>
                    <div className="mt-0.5 text-[11px] text-muted">
                      {ROLE_LABEL[p.role] ?? p.role}
                      {p.acquired ? ` · ${p.acquired}` : ""}
                      {p.trade ? ` from ${p.trade.from}` : ""}
                      {p.withdrawn ? " · missed 2026" : ""}
                    </div>
                  </td>
                  <td className="td stat-num text-right" title={p.outlook}>
                    {p.age === null ? "—" : Math.floor(p.age)}
                  </td>
                  <td className="td stat-num text-right">
                    {crExact(p.salary)}
                    {Math.abs(p.cost - Number(p.salary)) >= 0.005 && (
                      <div className="text-[11px] font-normal text-muted" title="A 2025 retention: keeping him costs what releasing him alone would free under the retention slabs">
                        costs {cr(p.cost)}
                      </div>
                    )}
                    {p.note && (
                      <InfoTip title="About this salary" className="ml-1 align-middle">
                        {p.note}
                      </InfoTip>
                    )}
                  </td>
                  <td className="td stat-num whitespace-nowrap text-right">
                    {p.value === null ? <span className="text-muted">{p.no_data ? NO_DATA_LABEL : "—"}</span> : <>{fmtNum(p.value, 1)} <span className="text-muted">± {fmtNum(p.value_sd ?? 0, 1)}</span></>}
                  </td>
                  <td className="td stat-num whitespace-nowrap text-right">
                    {p.price === null ? "—" : cr(p.price)}
                    {p.p_bought !== null && (
                      <div className="text-[11px] font-normal text-muted" title="Chance a franchise buys a player like him if he's released (fitted to past auctions)">
                        {fmtNum(100 * p.p_bought, 0)}% bought
                      </div>
                    )}
                  </td>
                  <td className="td stat-num text-right text-muted">{p.onfield === null ? "—" : cr(p.onfield)}</td>
                  <td className={cn("td stat-num text-right font-semibold", p.surplus === null ? "text-muted" : p.surplus >= 0 ? "text-willow" : "text-ball")}>
                    {p.surplus === null ? "—" : (p.surplus > 0 ? "+" : "") + cr(p.surplus)}
                  </td>
                  <td className="td stat-num whitespace-nowrap text-right" title={p.forecast?.text ?? "No forecast (no IPL season in the last two, or too few balls)"}>
                    {p.forecast ? (
                      <>
                        <span className="font-semibold text-fg">{p.forecast.median.map(signed).join(" / ")}</span>
                        <div className="text-[11px] font-normal text-muted">
                          {FORECAST_FLAG[p.forecast.flag] ?? p.forecast.flag} · {Math.round(100 * p.forecast.p_regular_last)}% regular {p.forecast.seasons[p.forecast.seasons.length - 1]}
                        </div>
                      </>
                    ) : (
                      <span className="text-muted">—</span>
                    )}
                  </td>
                  <td className="td stat-num text-right" title="The chance a franchise keeps a player like him at the retention deadline (a model of every real deadline 2018-2026)">
                    {p.p_keep === null ? "—" : `${Math.round(100 * p.p_keep)}%`}
                  </td>
                  <td className="td"><Badge tone={REC_TONE[p.rec]}>{REC_LABEL[p.rec]}</Badge></td>
                  <td className="td" title={p.price === null ? "No market price" : `Market price ${cr(p.price)} cr (upper quartile ${cr(p.price_central ?? p.price)}) against ${cr(p.cost)} cr to keep`}>
                    {p.should ? <Badge tone={SHOULD_TONE[p.should]}>{SHOULD_LABEL[p.should]}</Badge> : <span className="text-muted">—</span>}
                  </td>
                  <td className="td">
                    <div className="seg flex-nowrap" role="radiogroup" aria-label={`Decision for ${p.name}`}>
                      {(["keep", "release"] as const).map((d) => (
                        <button key={d} role="radio" aria-checked={(d === "keep") === p.kept}
                          className={cn("seg-btn px-2 py-0.5 text-xs", (d === "keep") === p.kept && "seg-btn-active")}
                          onClick={() => flip(p, d)}>
                          {d === "keep" ? "Keep" : "Release"}
                        </button>
                      ))}
                    </div>
                    {p.overridden && <div className="mt-0.5 text-[10px] text-gold">your call</div>}
                  </td>
                  <td className="td min-w-[18rem] max-w-[26rem] whitespace-normal text-xs leading-relaxed text-muted">
                    <div className="text-fg">{p.reason}</div>
                    <div>{p.outlook}{p.form_note ? ` ${p.form_note}.` : ""}</div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      <Card className="overflow-hidden">
        <CardHeader
          title="Role gaps, and what filling them costs"
          subtitle="Cheapest in the likely pool (free agents + other teams' release calls) at least as good as the best player you released in that role"
          right={
            <InfoTip title="How gaps are filled">
              Each need is filled in this order: keepers, openers, death bowlers, spinners, overseas. A pick counts for
              every role he fills, takes a squad slot, and an overseas slot if he's overseas. The pool is today's free
              agents plus the players our calls release from the other squads (marked "from" their team); the
              real auction will differ with what teams actually release.
            </InfoTip>
          }
        />
        <div className="overflow-auto">
          <table className="w-full border-collapse">
            <thead>
              <tr>
                <th className="th">Need</th>
                <th className="th text-right">Wanted</th>
                <th className="th text-right">Kept</th>
                <th className="th text-right">Gap</th>
                <th className="th">Cheapest that fit</th>
                <th className="th text-right">Cost</th>
              </tr>
            </thead>
            <tbody>
              {res.gaps.map((g) => (
                <tr key={g.tag} className="hover:bg-surface/50">
                  <td className="td font-medium text-fg">{g.label}</td>
                  <td className="td stat-num text-right">{g.target}</td>
                  <td className="td stat-num text-right">{g.kept}</td>
                  <td className={cn("td stat-num text-right", g.gap > 0 && "font-semibold text-gold")}>{g.gap}</td>
                  <td className="td min-w-[14rem] whitespace-normal text-xs text-muted">
                    {g.gap === 0 ? "covered" : g.picks.length === 0 ? "none found" : g.picks.map((c, i) => (
                      <span key={c.id}>
                        {i > 0 && ", "}
                        {c.id.startsWith("name:") ? <span className="text-fg">{c.name}</span> : <Link to={profilePath(c.id, "ipl")} className="text-fg hover:text-accent-glow">{c.from_team ? c.name : pool.find((r) => r.cricsheet_id === c.id)?.display_name || c.name}</Link>}{" "}
                        {cr(c.price)}
                        {c.from_team && <span className="text-faint"> (from {c.from_team})</span>}
                      </span>
                    ))}
                    {g.gap > 0 && (
                      <div className="mt-0.5 text-[11px]">
                        ≥ {fmtNum(g.ref_value, 1)} runs a match {g.ref_from_release ? "(best released)" : "(replacement level)"}
                      </div>
                    )}
                  </td>
                  <td className="td stat-num text-right">{g.cost ? `${cr(g.cost)} cr` : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      <Card className="space-y-2 px-5 py-4 text-xs leading-relaxed text-muted [overflow-wrap:anywhere]">
        <div className="text-sm font-semibold text-fg">About the data</div>
        <p>
          Squads, salaries and trades: {data.salary_source ?? data.squads_source}. Moves since the season:{" "}
          {data.changes_source ?? "none"}
          {changes.length > 0 && (
            <> ({changes.map((c) => (c.kind === "trade" ? `${c.name} ${c.from} → ${c.to} at ${cr(c.salary_cr ?? 0)} cr` : `${c.name} retired`)).join("; ")})</>
          )}
          . Salaries are hand-editable in <code className="text-fg">data/curated/ipl_squads_2026.json</code>.
        </p>
        {check && (
          <p>
            Data check: {team}'s purse entering the 2026 auction was published as {cr(check.published)} cr; our salaries give{" "}
            {cr(check.ours)} cr
            {(check.slab ?? 0) > 0 && (
              <>
                {" "}less {cr(check.slab ?? 0)} cr the purse still counts for 2025 retentions (charged at the fixed retention slab, not
                the salary) = {cr(check.ours - (check.slab ?? 0))} cr
              </>
            )}
            {Math.abs(check.ours - (check.slab ?? 0) - check.published) < 0.01
              ? " (they agree)."
              : ` (off by ${cr(Math.abs(check.ours - (check.slab ?? 0) - check.published))} cr: a salary on the source page differs from what the team paid).`}
          </p>
        )}
        {unmatched.length > 0 && (
          <p>
            Not in our ball-by-ball data (no match on Cricsheet yet), so priced from the market (uncapped Indian, age,
            no record) instead of rated: {unmatched.map((u) => u.name).join(", ")}.
          </p>
        )}
        <p>Recommendations are a model's view for discussion, not advice. Ratings data to the end of the 2026 IPL.</p>
      </Card>
    </div>
  );
}
