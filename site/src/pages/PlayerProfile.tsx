import { useEffect, useRef } from "react";
import { useSearchParams, useNavigate } from "react-router-dom";
import { UserSearch, Activity, Target, Shield, Swords, Users2, Instagram, Twitter, Cake, ExternalLink } from "lucide-react";
import { useStore } from "@/lib/store";
import { usePlayers } from "@/lib/usePlayers";
import { useAsync } from "@/lib/useAsync";
import { getProfile, getCohorts, getValueNow, displayName, type Profile, type PlayerRow, type ValueNow } from "@/lib/data";
import { Combobox } from "@/components/Combobox";
import { PageTitle, Card, CardHeader, Spinner, ErrorBox, Empty, Badge, StatTile, Segmented, InfoTip, StaleBadge } from "@/components/ui";
import { MetricInfo } from "@/components/MetricInfo";
import { FormForecast } from "@/components/FormForecast";
import { METRIC_BY_SLUG, fmtMetric } from "@/lib/metrics";
import { BAT_STATS, BOWL_STATS, fmtStat, standardStats } from "@/lib/standard";
import { useUrlState } from "@/lib/useUrlState";
import { normCountry } from "@/lib/scout";
import { cn, collectionLabel, fmt, fmtSigned } from "@/lib/utils";

function num(v: unknown): number | null {
  if (v === null || v === undefined || v === "") return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}

/** A latent skill axis on a scale centred on the average player (0). The centre line is that average
 * player, drawn clearly and labelled; the dot is this player; the shaded band is the model's uncertainty. */
function SkillAxis({
  label,
  mean,
  sd,
  hint,
}: {
  label: string;
  mean: number | null;
  sd: number | null;
  hint: string;
}) {
  if (mean === null) return null;
  // map roughly [-0.6, 0.6] skill range to 0..100%
  const span = 0.6;
  const pct = Math.max(2, Math.min(98, ((mean + span) / (2 * span)) * 100));
  const band = sd ? Math.min(40, (sd / (2 * span)) * 100) : 0;
  const good = mean >= 0;
  return (
    <div>
      <div className="flex items-baseline justify-between gap-3">
        <span className="text-xs font-medium text-fg">{label}</span>
        <span className={cn("stat-num text-sm font-semibold", good ? "text-accent-glow" : "text-ball")}>
          {mean >= 0 ? "+" : ""}
          {mean.toFixed(3)}
          {sd !== null && <span className="ml-1 text-[11px] text-muted">±{sd.toFixed(3)}</span>}
        </span>
      </div>
      <div className="relative mt-2 h-3 w-full rounded-full bg-border/50">
        {/* the average-player baseline: a solid, full-height line */}
        <div className="absolute -top-1 left-1/2 h-5 w-0.5 -translate-x-1/2 rounded bg-fg/70" aria-hidden />
        {/* uncertainty band */}
        <div
          className="absolute top-0 h-full rounded-full bg-accent/25"
          style={{ left: `${Math.max(0, pct - band / 2)}%`, width: `${band}%` }}
        />
        {/* this player */}
        <div
          className={cn(
            "absolute top-1/2 h-3.5 w-3.5 -translate-x-1/2 -translate-y-1/2 rounded-full ring-2 ring-bg",
            good ? "bg-accent" : "bg-ball",
          )}
          style={{ left: `${pct}%` }}
        />
      </div>
      <div className="relative mt-1 flex justify-between text-[10px] uppercase tracking-wider text-faint">
        <span>worse</span>
        <span className="absolute left-1/2 -translate-x-1/2 font-semibold text-muted">average</span>
        <span>better</span>
      </div>
      <div className="mt-1 text-[11px] leading-relaxed text-muted">{hint}</div>
    </div>
  );
}

const INTENT_BUCKETS = ["0-5", "6-10", "11-20", "21-30", "31-50", "51+"];

// slug -> [title, value key, subtitle, digits] — one card per catalog metric
// the player appears in (all 12 boards). Mirrored by 8_Player_Profile.py.
const METRIC_CARDS: Record<string, [string, string, string, number]> = {
  ngi: ["Net Game Impact", "ngi_per_match", "win chance added per match", 1],
  pressure_runs: ["Pressure Runs", "pressure_sr_per_100_balls", "SR under chase pressure", 1],
  intent_curve: ["Intent Curve", "early_sr", "SR over the first 10 balls", 1],
  dot_ball_recovery: ["Dot-Ball Recovery", "runs_per_6_after_dot", "runs / 6 balls after a dot", 1],
  counter_attack: ["Counter-Attack", "counter_attack_sr", "SR after a partner falls", 1],
  boundary_dependency: ["Boundary Dependency", "bdr_pct", "% of runs from boundaries", 1],
  dot_avoidance: ["Dot-Ball Avoidance", "dots_avoided_per100", "dots avoided per 100 balls vs average", 1],
  pace_spin: ["Pace vs Spin", "spin_edge", "runs / 100 balls better v spin than pace", 1],
  finisher: ["Finisher Index", "above_per100", "runs / 100 balls above avg, chase overs 17-20", 1],
  hand_split: ["Left vs Right", "left_edge", "runs / 100 saved, left-handers v right", 1],
  wicket_quality: ["Wicket Quality", "wicket_quality", "avg skill of batters dismissed", 3],
  crease_longevity: ["Crease Longevity", "longevity_index", "balls per dismissal vs cohort", 2],
  slow_start_cost: ["Slow-Start Cost", "slow_start_cost", "career SR − first-20-ball SR", 1],
  keeping: ["Wicketkeeping", "dismissals", "catches + stumpings + run-outs", 0],
  fielding: ["Fielding", "dismissals", "catches + run-outs", 0],
};

/** Intent curve: SR per balls-faced bucket as mini bars, scaled to the player's own peak. */
function IntentBars({ curve }: { curve: unknown }) {
  if (!Array.isArray(curve)) return null;
  const values = curve.map(num);
  const present = values.filter((v): v is number => v !== null);
  if (present.length === 0) return null;
  const max = Math.max(...present, 1);
  const title = values.map((v, i) => `${INTENT_BUCKETS[i]}: ${v === null ? "—" : Math.round(v)}`).join("   ");
  return (
    <div className="mt-1.5 flex h-6 items-end gap-[3px]" title={title}>
      {values.map((v, i) => (
        <span
          key={i}
          className={cn("w-[7px] rounded-sm", v === null ? "bg-border/40" : "bg-accent/70")}
          style={{ height: v === null ? "12%" : `${Math.max(14, (v / max) * 100)}%` }}
        />
      ))}
    </div>
  );
}

function MetricCard({ slug, m }: { slug: string; m: Record<string, unknown> }) {
  const t = METRIC_CARDS[slug];
  const def = METRIC_BY_SLUG[slug];
  if (!t || !def) return null;
  const [name, valKey, sub, digits] = t;
  const col = def.columns.find((c) => c.key === valKey);
  const total = slug === "ngi" ? num(m.ngi_total) : null;
  return (
    <Card className="px-4 py-3">
      <div className="flex items-start justify-between gap-2">
        <div className="text-[11px] font-medium uppercase tracking-wider text-muted">{name}</div>
        <MetricInfo m={def} />
      </div>
      <div className="mt-1 stat-num text-lg font-bold text-fg">{fmtMetric(m[valKey], { digits, fmt: col?.fmt })}</div>
      <div className="mt-0.5 text-[11px] text-muted">{sub}</div>
      {total !== null && (
        <div className="mt-1.5 border-t border-border pt-1.5 text-[11px] text-muted">
          <span className="stat-num font-semibold text-fg">{fmt(total, 1)}</span> wins added (career total — grows with
          matches played)
        </div>
      )}
      {slug === "intent_curve" && <IntentBars curve={m.curve} />}
    </Card>
  );
}

const POS_LABEL: Record<string, string> = {
  opener: "Opener",
  no3: "No. 3",
  middle: "Middle order",
  finisher: "Finisher",
  lower: "Lower order",
  tailender: "Tailender",
};

/** "1988-11-05" as a local date (new Date("1988-11-05") is UTC midnight, a day early west of Greenwich). */
function localDate(iso: string): Date {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso);
  return m ? new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3])) : new Date(iso);
}

function ageFrom(dob: string): number | null {
  const d = localDate(dob);
  if (Number.isNaN(d.getTime())) return null;
  const now = new Date();
  let a = now.getFullYear() - d.getFullYear();
  const m = now.getMonth() - d.getMonth();
  if (m < 0 || (m === 0 && now.getDate() < d.getDate())) a--;
  return a;
}

function SocialChip({ href, icon, label }: { href: string; icon: React.ReactNode; label: string }) {
  return (
    <a
      href={href}
      target="_blank"
      rel="noreferrer"
      className="inline-flex items-center gap-1.5 rounded-md border border-border bg-surface px-2 py-1 text-xs font-medium text-muted transition-colors hover:border-accent/40 hover:text-accent-glow"
    >
      {icon}
      {label}
    </a>
  );
}

/** A role's value badge: next season's value when known (the career rating and its balls beside it),
 * else the career rating; a bowler's economy and wicket parts after it. */
function RoleValue({
  tone,
  label,
  now,
  career,
  balls,
  parts,
}: {
  tone: "accent" | "willow";
  label: string;
  now?: [number, number];
  career: number;
  balls: number;
  parts?: [number, number] | null;
}) {
  return (
    <span className="inline-flex flex-wrap items-center gap-1.5">
      <Badge tone={tone}>
        {label} {fmt(now ? now[0] : career, 1)}
        {now ? " next season" : ""}
      </Badge>
      <span className="text-xs text-muted">
        {now ? `career ${fmt(career, 1)} · ` : ""}
        {balls.toLocaleString()} balls
        {parts ? ` · economy ${fmtSigned(parts[0], 1)}, wickets ${fmtSigned(parts[1], 1)}` : ""}
      </span>
    </span>
  );
}

function Identity({
  profile,
  bat,
  bowl,
  now,
}: {
  profile: Profile;
  bat?: Record<string, number>;
  bowl?: Record<string, number>;
  /** his value for the coming season per role (IPL profiles only) */
  now?: ValueNow[string] | null;
}) {
  const w = (profile.wikidata ?? {}) as Record<string, string | null>;
  // identity (the player-data pass) wins over the older taxonomy block; both are optional
  const idn = profile.identity ?? null;
  const tax0 = (profile.taxonomy ?? {}) as Record<string, string | undefined>;
  const tax = profile.taxonomy || idn
    ? {
        primary_role: idn?.primary_role ?? tax0.primary_role,
        bowling_style: idn?.bowling_style ?? tax0.bowling_style,
        bowling_category: idn?.bowling_category ?? tax0.bowling_category,
        batting_position: tax0.batting_position,
        country: idn?.country ?? tax0.country,
        batting_hand: idn?.batting_hand ?? tax0.batting_hand,
      }
    : null;
  const shownName = (idn?.display_name && idn.display_name.trim()) || w.label || profile.name;
  const photo = w.image_url ?? null;
  const dob = w.dob ?? null;
  const age = dob ? ageFrom(dob) : null;
  const ig = w.instagram;
  const tw = w.twitter;
  const qid = w.wikidata_qid;
  const cricinfoId = (profile.ids?.key_cricinfo as number | string | null) ?? null;

  return (
    <Card className="flex flex-wrap items-center gap-4 px-5 py-4">
      {photo ? (
        <img
          src={photo}
          alt={shownName}
          loading="lazy"
          className="h-16 w-16 shrink-0 rounded-xl border border-border object-cover"
          onError={(e) => {
            (e.currentTarget as HTMLImageElement).style.display = "none";
          }}
        />
      ) : (
        <div className="flex h-16 w-16 shrink-0 items-center justify-center rounded-xl border border-border bg-surface text-2xl font-bold text-accent">
          {shownName.split(" ").pop()?.[0] ?? "?"}
        </div>
      )}
      <div className="min-w-0 flex-1">
        <h2 className="text-xl font-bold text-fg">{shownName}</h2>
        {(shownName !== profile.name || (idn?.full_name && idn.full_name !== shownName)) && (
          <div className="mt-0.5 text-xs text-muted">
            {idn?.full_name && idn.full_name !== shownName ? `${idn.full_name} · ` : ""}scorecard name {profile.name}
          </div>
        )}
        {dob && (
          <div className="mt-0.5 flex items-center gap-1.5 text-xs text-muted">
            <Cake className="h-3.5 w-3.5" />
            Born {localDate(dob).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" })}
            {age !== null && <span>· {age} yrs</span>}
          </div>
        )}
        {/* LLM taxonomy: role / bowling type / batting slot / country */}
        {tax && (
          <div className="mt-2 flex flex-wrap items-center gap-2">
            {tax.primary_role && <Badge tone="accent">{tax.primary_role.replace("_", "-")}</Badge>}
            {tax.bowling_style && tax.bowling_category !== "none" && (
              <Badge tone={tax.bowling_category === "spin" ? "willow" : "ball"}>
                {tax.bowling_style.replace(/-/g, " ")}
              </Badge>
            )}
            {tax.batting_position && <Badge>{POS_LABEL[tax.batting_position] ?? tax.batting_position}</Badge>}
            {tax.batting_hand && <Badge>{tax.batting_hand}-hand bat</Badge>}
            {tax.country && <Badge>{tax.country}</Badge>}
            {idn?.team && <Badge tone="gold">{idn.team}</Badge>}
            {idn?.capped === true && <Badge tone="accent">capped</Badge>}
            {idn?.capped === false && <Badge>uncapped</Badge>}
            {idn?.captaincy?.ipl?.[0] && (
              <span title="IPL captaincy (Wikipedia)"><Badge tone="gold">
                IPL captain {idn.captaincy.ipl[0].team} {idn.captaincy.ipl[0].from}
                {idn.captaincy.ipl[0].to !== idn.captaincy.ipl[0].from ? `–${idn.captaincy.ipl[0].to}` : ""}
              </Badge></span>
            )}
            {idn?.captaincy?.international?.[0] && (
              <span title="International captaincy (Wikipedia)"><Badge tone="gold">
                {idn.captaincy.international[0].country} {idn.captaincy.international[0].format.toUpperCase()} captain{" "}
                {idn.captaincy.international[0].from}
                {idn.captaincy.international[0].to !== idn.captaincy.international[0].from ? `–${idn.captaincy.international[0].to}` : ""}
              </Badge></span>
            )}
          </div>
        )}
        <div className="mt-2 flex flex-wrap items-center gap-2">
          {profile.activity &&
            (profile.activity.active ? (
              <Badge tone="accent">active</Badge>
            ) : (
              <Badge tone="ball">retired{profile.activity.last_match_date ? ` · last ${profile.activity.last_match_date.slice(0, 4)}` : ""}</Badge>
            ))}
          {bat && (
            <RoleValue tone="accent" label="batting value" now={now?.bat} career={bat.value} balls={bat.balls} />
          )}
          {bowl && bowl.balls > 60 && (
            <RoleValue tone="willow" label="bowling value" now={now?.bowl} career={bowl.value} balls={bowl.balls}
              parts={bowl.value_rate != null && bowl.value_wkts != null ? [bowl.value_rate, bowl.value_wkts] : null} />
          )}
          {(bat || (bowl && bowl.balls > 60)) && (
            <InfoTip title="Batting / bowling value" label="What batting and bowling value mean">
              One number per role from the skill model, in runs per 100 balls above the league's average ball:
              0 = average, +10 = ten runs better every 100 balls; the best IPL regulars sit around +20 to +25.
              Batting value is extra scoring plus the runs saved by not getting out, a wicket priced at what it
              costs where he bats (dear early, cheap at the death); bowling value is runs saved plus extra
              wickets at the same price.
              {now && (
                <>
                  {" "}The headline is his value for the coming season: the career rating moved by how players of his
                  age and kind change from season to season, his recent seasons weighed in, and pulled part of the way
                  toward the average (about a quarter for batters, a fifth for bowlers, fitted on what players then did
                  the next season). The career rating is beside it, with the balls it rests on.
                </>
              )}
              {bowl?.value_rate != null && (
                <>
                  {" "}A bowler's value splits into economy (runs saved) and wickets (extra wickets at that price).
                  Economy carries over from one season to the next; a wicket rate barely does (season-to-season
                  IPL correlation about 0.1, against about 0.3 for economy), so a Purple Cap year says little about the
                  next one.
                </>
              )}
            </InfoTip>
          )}
          <Badge>id {profile.cricsheet_id}</Badge>
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        {ig && <SocialChip href={`https://instagram.com/${ig}`} icon={<Instagram className="h-3.5 w-3.5" />} label="Instagram" />}
        {tw && <SocialChip href={`https://twitter.com/${tw}`} icon={<Twitter className="h-3.5 w-3.5" />} label="Twitter" />}
        {cricinfoId && (
          <SocialChip
            href={`https://www.espncricinfo.com/cricketers/x-${cricinfoId}`}
            icon={<ExternalLink className="h-3.5 w-3.5" />}
            label="ESPNcricinfo"
          />
        )}
        {qid && <SocialChip href={`https://www.wikidata.org/wiki/${qid}`} icon={<ExternalLink className="h-3.5 w-3.5" />} label="Wikidata" />}
      </div>
    </Card>
  );
}

function DismissalFingerprint({ fp }: { fp: Record<string, unknown> | null }) {
  if (!fp) return null;
  const batter = fp.batter as { total: number; rows: { kind: string; count: number; pct: number }[]; read: string } | null;
  const bowler = fp.bowler as { total: number; rows: { kind: string; count: number; pct: number }[]; read: string } | null;
  const block = (title: string, d: typeof batter, icon: React.ReactNode) => {
    if (!d || !d.rows?.length) return null;
    return (
      <div className="flex-1">
        <div className="mb-2 flex items-center gap-2 text-sm font-semibold text-fg">
          {icon} {title} <span className="text-xs font-normal text-muted">· {d.total} total</span>
        </div>
        <div className="space-y-1.5">
          {d.rows.slice(0, 6).map((r) => (
            <div key={r.kind} className="flex items-center gap-2">
              <span className="w-20 shrink-0 text-xs capitalize text-muted">{r.kind}</span>
              <div className="h-2 flex-1 overflow-hidden rounded-full bg-border/50">
                <div
                  className="h-full rounded-full bg-gradient-to-r from-ball/70 to-ball"
                  style={{ width: `${r.pct}%` }}
                />
              </div>
              <span className="stat-num w-14 shrink-0 text-right text-xs text-fg">
                {r.pct.toFixed(1)}%
              </span>
            </div>
          ))}
        </div>
        <p className="mt-2.5 text-xs italic text-muted">“{d.read}”</p>
      </div>
    );
  };
  return (
    <Card>
      <CardHeader title="Dismissal fingerprint" subtitle="How they get out (batting) / take wickets (bowling)" />
      <div className="flex flex-col gap-6 p-5 sm:flex-row">
        {block("As batter", batter, <Target className="h-4 w-4 text-ball" />)}
        {block("As bowler", bowler, <Swords className="h-4 w-4 text-accent" />)}
      </div>
    </Card>
  );
}

export function PlayerProfile() {
  const { collection, meta } = useStore();
  const { options, byName, byId, loading: pl } = usePlayers(collection);
  const [params, setParams] = useSearchParams();
  // a link that names its league (`?c=bbl&cid=…`, e.g. from Scout) waits for the store to switch to it
  const urlC = params.get("c");
  const switching = !!urlC && urlC !== collection;
  const navigate = useNavigate();

  // resolve incoming ?name= / ?cid= to a cricsheet_id
  const qName = params.get("name");
  const qCid = params.get("cid");
  // the URL is the source of truth, so back/forward (or losing ?cid=) updates the view
  const nameCid = qName ? (byName.get(qName)?.cricsheet_id ?? null) : null;
  const cid = qCid || nameCid;

  // normalise a resolved ?name= link to the stable ?cid= form
  useEffect(() => {
    if (!qCid && nameCid) setParams({ cid: nameCid }, { replace: true });
  }, [qCid, nameCid, setParams]);

  // players are per league: on a switch, drop the selection rather than asking for a file that isn't there
  const prevCollection = useRef(collection);
  useEffect(() => {
    if (prevCollection.current === collection) return;
    prevCollection.current = collection;
    // …unless the switch came from a link that named this league for this player
    if (params.get("c") === collection) return;
    setParams({});
  }, [collection, setParams, params]);

  const nameNotFound = !qCid && !!qName && !pl && !byName.has(qName);

  const { data: profile, loading, error } = useAsync<Profile | null>(
    () => (cid && !switching ? getProfile(collection, cid) : Promise.resolve(null)),
    [collection, cid, switching],
  );
  // next season's values live with the auction target (the IPL)
  const { data: valueNow } = useAsync(
    () => (collection === "ipl" ? getValueNow(collection) : Promise.resolve(null)),
    [collection],
  );
  const { data: cohorts } = useAsync(
    () => (cid && !switching ? getCohorts(collection, cid) : Promise.resolve(null)),
    [collection, cid, switching],
  );

  function pick(id: string | null) {
    if (id) setParams({ cid: id });
    else setParams({});
  }

  const [statView, setStatView] = useUrlState<"totals" | "standard">("stats", "totals", { valid: ["totals", "standard"] });
  const [twinCountry, setTwinCountry] = useUrlState<TwinCountry>("twins", "same", { valid: ["same", "overseas", "all"] });
  const lg = collectionLabel(collection);
  const playerRow = cid ? (byId.get(cid) ?? null) : null;
  const playerCountry =
    profile?.identity?.country ?? (profile?.taxonomy?.country as string | undefined) ?? playerRow?.country ?? null;
  const bat = profile?.bayes?.bayes_batter as Record<string, number> | undefined;
  const bowl = profile?.bayes?.bayes_bowler as Record<string, number> | undefined;
  const career = profile?.career as Record<string, number> | undefined;
  const metrics = profile?.metrics as Record<string, Record<string, unknown> | null> | undefined;

  return (
    <>
      <PageTitle
        title="Player profile"
        icon={<UserSearch className="h-6 w-6" />}
        desc="A full dossier per player: four Bayesian skill axes with their uncertainty, career totals, the novel metrics, how they get out, and their closest stylistic twins."
      />

      <div className="mb-6 max-w-md">
        <Combobox
          options={options}
          value={cid}
          onChange={pick}
          placeholder={pl ? "Loading players…" : "Search a player…"}
        />
      </div>

      {!cid && qName && pl ? (
        <Spinner label="Finding player…" />
      ) : nameNotFound ? (
        <Empty>
          No player called “{qName}” in {collectionLabel(collection)} — search for them above, or switch league.
        </Empty>
      ) : !cid ? (
        <Empty>Pick a player to see their dossier.</Empty>
      ) : switching || (loading && !profile) ? (
        <Spinner label="Building dossier…" />
      ) : error ? (
        <ErrorBox message={error} />
      ) : !profile ? (
        <Empty>No profile found.</Empty>
      ) : (
        <div className="space-y-5 animate-fade-up">
          {/* identity */}
          {meta?.stale && (
            <div className="flex flex-wrap items-center gap-2 rounded-xl border border-gold/30 bg-gold/5 px-4 py-2.5 text-sm text-muted">
              <StaleBadge asOf={meta.data_as_of} />
              {collectionLabel(collection)} data has stopped updating — every number on this page ends at that date.
            </div>
          )}
          <Identity profile={profile} bat={bat} bowl={bowl} now={cid ? valueNow?.[cid] : null} />

          {/* career: totals or the standard scorecard stats, one click apart */}
          {career && <CareerBlock profile={profile} career={career} view={statView} setView={setStatView} />}

          {/* bayes skill axes */}
          <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
            {bat && (
              <Card>
                <CardHeader title="Batting skill" subtitle={`Measured against an average ${lg} batter (the centre line) — the dot is this player, the shaded band is how sure the model is`} right={<Activity className="h-4 w-4 text-accent" />} />
                <div className="space-y-4 p-5">
                  <SkillAxis label="Scoring speed" mean={num(bat.skill)} sd={num(bat.skill_sd)} hint={`How fast he scores compared with an average ${lg} batter facing the same bowlers. Right of the centre line = scores faster than average.`} />
                  <SkillAxis label="Staying in (hard to dismiss)" mean={num(bat.survival_skill)} sd={num(bat.survival_skill_sd)} hint={`How hard he is to get out, ball for ball, compared with an average ${lg} batter. Right of the centre line = harder to dismiss.`} />
                  <div className="text-xs text-muted">From {fmt(bat.balls, 0)} balls faced.</div>
                </div>
              </Card>
            )}
            {bowl && (bowl.balls ?? 0) > 60 && (
              <Card>
                <CardHeader title="Bowling skill" subtitle={`Measured against an average ${lg} bowler (the centre line) — the dot is this player, the shaded band is how sure the model is`} right={<Shield className="h-4 w-4 text-willow" />} />
                <div className="space-y-4 p-5">
                  <SkillAxis label="Economy (keeping runs down)" mean={num(bowl.skill)} sd={num(bowl.skill_sd)} hint={`How few runs he gives away per ball compared with an average ${lg} bowler bowling to the same batters. Right = tighter.`} />
                  <SkillAxis label="Wicket-taking" mean={num(bowl.strike_skill)} sd={num(bowl.strike_skill_sd)} hint={`How often he takes a wicket compared with an average ${lg} bowler. Right = takes wickets more often.`} />
                  <div className="text-xs text-muted">From {fmt(bowl.balls, 0)} balls bowled.</div>
                </div>
              </Card>
            )}
          </div>

          {/* form forecast: value over the next three seasons (IPL) */}
          <FormForecast collection={collection} cid={cid} />

          {/* novel metrics */}
          {metrics && Object.entries(metrics).some(([, m]) => m && Object.keys(m).length > 0) && (
            <div>
              <h3 className="mb-3 text-sm font-semibold text-fg">Novel metrics</h3>
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
                {Object.entries(metrics).map(([slug, m]) => (m ? <MetricCard key={slug} slug={slug} m={m} /> : null))}
              </div>
            </div>
          )}

          {/* dismissal fingerprint */}
          <DismissalFingerprint fp={profile.dismissal_fingerprint} />

          {/* style twins + cohorts */}
          <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
            <Card>
              <CardHeader
                title="Style twins"
                subtitle="Players whose numbers look most like this player's"
                right={<Users2 className="h-4 w-4 text-accent" />}
              />
              <div className="flex flex-wrap items-center gap-2 border-b border-border px-5 py-2.5">
                <span className="text-xs font-medium text-muted">Country</span>
                <Segmented<TwinCountry>
                  label="Style twins country"
                  value={playerCountry ? twinCountry : "all"}
                  onChange={setTwinCountry}
                  options={[
                    { value: "same", label: playerCountry ? `Same (${playerCountry})` : "Same" },
                    { value: "overseas", label: "Overseas" },
                    { value: "all", label: "All" },
                  ]}
                />
              </div>
              <div className="p-3">
                <TwinList twins={profile.style_twins_batter} byName={byName} byId={byId} onPick={(c) => navigate(`/player?cid=${c}`)} role="batter" country={playerCountry} mode={playerCountry ? twinCountry : "all"} />
                <TwinList twins={profile.style_twins_bowler} byName={byName} byId={byId} onPick={(c) => navigate(`/player?cid=${c}`)} role="bowler" country={playerCountry} mode={playerCountry ? twinCountry : "all"} />
              </div>
            </Card>
            <Card>
              <CardHeader title="Graph cohort" subtitle="Players who faced the same bowlers / shared a side" />
              <div className="p-3">
                <CohortList rows={cohorts?.co_faced ?? []} label="Faced the same bowlers" keyField="shared_bowlers" byName={byName} byId={byId} onPick={(c) => navigate(`/player?cid=${c}`)} />
              </div>
            </Card>
          </div>
        </div>
      )}
    </>
  );
}

type TwinCountry = "same" | "overseas" | "all";

function TwinList({
  twins,
  role,
  byName,
  byId,
  onPick,
  country,
  mode,
}: {
  twins: Record<string, unknown>[] | null;
  role: string;
  byName: Map<string, PlayerRow>;
  byId: Map<string, PlayerRow>;
  onPick: (cid: string) => void;
  /** The profiled player's country (null = unknown: no country filter). */
  country: string | null;
  mode: TwinCountry;
}) {
  if (!twins || twins.length === 0) return null;
  const home = normCountry(country);
  const dists = twins.map((x) => Number(x.distance)).filter(Number.isFinite);
  const closest = dists.length ? Math.min(...dists) : NaN;
  const kept = twins.filter((t) => {
    if (mode === "all" || !home) return true;
    const row = (typeof t.cricsheet_id === "string" ? byId.get(t.cricsheet_id) : undefined) ?? byName.get(String(t.name));
    const c = normCountry((t.country as string | null | undefined) ?? row?.country ?? null);
    if (!c) return false;
    return mode === "same" ? c === home : c !== home;
  });
  return (
    <div className="mb-2">
      <div className="px-2 pb-1 text-[11px] uppercase tracking-wider text-muted">{role}</div>
      {kept.length === 0 && (
        <div className="px-2 py-2 text-xs text-muted">
          None of his {twins.length} closest {role} twins {mode === "same" ? `are from ${home}` : "are from overseas"} — try{" "}
          {mode === "same" ? "Overseas or All" : "Same or All"}.
        </div>
      )}
      {kept.slice(0, 6).map((t, i) => {
        const name = String(t.name);
        const row = (typeof t.cricsheet_id === "string" ? byId.get(t.cricsheet_id) : undefined) ?? byName.get(name);
        const cid = (typeof t.cricsheet_id === "string" ? t.cricsheet_id : undefined) ?? row?.cricsheet_id;
        const dist = Number(t.distance);
        // 1 = as close as the closest twin, falling with distance
        const rel = Number.isFinite(dist) && dist > 0 ? Math.min(1, closest / dist) : Number.isFinite(dist) ? 1 : null;
        const c = (t.country as string | null | undefined) ?? row?.country ?? null;
        return (
          <button
            key={name}
            disabled={!cid}
            onClick={() => cid && onPick(cid)}
            className="flex w-full items-center justify-between rounded-md px-2 py-1.5 text-sm hover:bg-surface disabled:opacity-60"
          >
            <span className="flex min-w-0 items-center gap-2">
              <span className="stat-num w-5 text-right text-xs text-faint">{i + 1}</span>
              <span className="truncate text-fg">{displayName(row ?? { name })}</span>
              {c && <span className="text-[11px] text-muted">{c}</span>}
            </span>
            {rel !== null && (
              <span className="ml-3 h-1.5 w-16 shrink-0 overflow-hidden rounded-full bg-border/60" title={Number.isFinite(dist) ? `${Math.round(Math.max(0, 1 - dist) * 100)}% alike (bar: relative to the closest twin)` : "How close, relative to the closest twin"}>
                <span className="block h-full rounded-full bg-grad" style={{ width: `${Math.max(8, rel * 100)}%` }} />
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}

/** Career totals, or the standard scorecard stats (average, strike rate, economy…) — one click apart. */
function CareerBlock({
  profile,
  career,
  view,
  setView,
}: {
  profile: Profile;
  career: Record<string, number>;
  view: "totals" | "standard";
  setView: (v: "totals" | "standard") => void;
}) {
  const st = standardStats(profile);
  const bowls = (st.ballsBowled ?? 0) >= 60;
  const bats = (st.balls ?? 0) > 0;
  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <h3 className="text-sm font-semibold text-fg">Career</h3>
        <Segmented
          label="Career view"
          value={view}
          onChange={setView}
          options={[
            { value: "totals", label: "Totals" },
            { value: "standard", label: "Standard stats" },
          ]}
        />
      </div>
      {view === "totals" ? (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
          <StatTile label="Runs" value={fmt(career.career_runs, 0)} />
          <StatTile label="Balls faced" value={fmt(career.career_balls_faced, 0)} />
          <StatTile label="Innings" value={fmt(career.career_innings, 0)} />
          <StatTile label="Fours / Sixes" value={`${career.career_fours ?? 0}/${career.career_sixes ?? 0}`} />
          <StatTile label="Wickets" value={fmt(career.career_wickets, 0)} />
          <StatTile label="Balls bowled" value={fmt(career.career_legal_balls_bowled, 0)} />
        </div>
      ) : (
        <div className="space-y-3">
          {bats && (
            <div>
              <div className="eyebrow mb-1.5">Batting</div>
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-7">
                {BAT_STATS.map((r) => (
                  <StatTile key={r.key} label={r.label} value={fmtStat(st, r)} hint={r.hint} />
                ))}
              </div>
            </div>
          )}
          {bowls && (
            <div>
              <div className="eyebrow mb-1.5">Bowling</div>
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-7">
                {BOWL_STATS.map((r) => (
                  <StatTile key={r.key} label={r.label} value={fmtStat(st, r)} hint={r.hint} />
                ))}
              </div>
            </div>
          )}
          <p className="text-xs text-muted">“—” = not in this data export yet.</p>
        </div>
      )}
    </div>
  );
}

function CohortList({
  rows,
  label,
  keyField,
  byName,
  byId,
  onPick,
}: {
  rows: Record<string, unknown>[];
  label: string;
  keyField: string;
  byName: Map<string, PlayerRow>;
  byId: Map<string, PlayerRow>;
  onPick: (cid: string) => void;
}) {
  if (!rows.length) return <div className="px-2 py-3 text-sm text-muted">No graph cohort available.</div>;
  return (
    <div>
      <div className="px-2 pb-1 text-[11px] uppercase tracking-wider text-muted">{label}</div>
      {rows.slice(0, 10).map((r, i) => {
        const name = String(r.name);
        const row = (typeof r.cricsheet_id === "string" ? byId.get(r.cricsheet_id) : undefined) ?? byName.get(name);
        const cid = (typeof r.cricsheet_id === "string" ? r.cricsheet_id : undefined) ?? row?.cricsheet_id;
        return (
          <button
            key={i}
            disabled={!cid}
            onClick={() => cid && onPick(cid)}
            className="flex w-full items-center justify-between rounded-md px-2 py-1.5 text-sm hover:bg-surface disabled:opacity-60"
          >
            <span className="text-fg">{displayName(row ?? { name })}</span>
            <span className="stat-num text-xs text-muted">{String(r[keyField] ?? r.shared_bowlers ?? r.shared_batters ?? "")} shared</span>
          </button>
        );
      })}
    </div>
  );
}
