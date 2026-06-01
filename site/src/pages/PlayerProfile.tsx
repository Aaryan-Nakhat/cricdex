import { useEffect, useState } from "react";
import { useSearchParams, useNavigate } from "react-router-dom";
import { UserSearch, Activity, Target, Shield, Swords, Users2, Instagram, Twitter, Cake, ExternalLink } from "lucide-react";
import { useStore } from "@/lib/store";
import { usePlayers } from "@/lib/usePlayers";
import { useAsync } from "@/lib/useAsync";
import { getProfile, getCohorts, type Profile } from "@/lib/data";
import { Combobox } from "@/components/Combobox";
import { PageTitle, Card, CardHeader, Spinner, ErrorBox, Empty, Badge, StatTile } from "@/components/ui";
import { cn, fmt } from "@/lib/utils";

function num(v: unknown): number | null {
  if (v === null || v === undefined || v === "") return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}

/** A latent skill axis: mean dot on a ±band, sd as the band width. */
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
      <div className="flex items-baseline justify-between">
        <span className="text-xs font-medium text-muted">{label}</span>
        <span className={cn("stat-num text-sm font-semibold", good ? "text-accent-glow" : "text-ball")}>
          {mean >= 0 ? "+" : ""}
          {mean.toFixed(3)}
          {sd !== null && <span className="ml-1 text-[11px] text-muted">±{sd.toFixed(3)}</span>}
        </span>
      </div>
      <div className="relative mt-1.5 h-2 w-full rounded-full bg-border/50">
        <div className="absolute left-1/2 top-0 h-full w-px bg-muted/40" />
        {/* uncertainty band */}
        <div
          className="absolute top-0 h-full rounded-full bg-accent/20"
          style={{ left: `${Math.max(0, pct - band / 2)}%`, width: `${band}%` }}
        />
        {/* mean dot */}
        <div
          className={cn(
            "absolute top-1/2 h-3 w-3 -translate-x-1/2 -translate-y-1/2 rounded-full ring-2 ring-bg",
            good ? "bg-accent" : "bg-ball",
          )}
          style={{ left: `${pct}%` }}
        />
      </div>
      <div className="mt-1 text-[11px] text-muted">{hint}</div>
    </div>
  );
}

function MetricCard({ slug, m }: { slug: string; m: Record<string, unknown> }) {
  const titles: Record<string, [string, string, string]> = {
    pressure_runs: ["Pressure Runs", "pressure_sr_per_100_balls", "SR under chase pressure"],
    dot_ball_recovery: ["Dot-Ball Recovery", "runs_per_6_after_dot", "runs / 6 balls after a dot"],
    counter_attack: ["Counter-Attack", "counter_attack_sr", "SR after a partner falls"],
    boundary_dependency: ["Boundary Dependency", "bdr_pct", "% of runs from boundaries"],
    pressure_conversion: ["Pressure Conversion", "wicket_rate_pct", "pressure balls → wickets"],
  };
  const t = titles[slug];
  if (!t) return null;
  const [name, valKey, sub] = t;
  const v = num(m[valKey]);
  return (
    <Card className="px-4 py-3">
      <div className="text-[11px] font-medium uppercase tracking-wider text-muted">{name}</div>
      <div className="mt-1 stat-num text-lg font-bold text-fg">{fmt(v, 1)}</div>
      <div className="mt-0.5 text-[11px] text-muted">{sub}</div>
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

function ageFrom(dob: string): number | null {
  const d = new Date(dob);
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

function Identity({
  profile,
  bat,
  bowl,
}: {
  profile: Profile;
  bat?: Record<string, number>;
  bowl?: Record<string, number>;
}) {
  const w = (profile.wikidata ?? {}) as Record<string, string | null>;
  const tax = profile.taxonomy ?? null;
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
          alt={profile.name}
          loading="lazy"
          className="h-16 w-16 shrink-0 rounded-xl border border-border object-cover"
          onError={(e) => {
            (e.currentTarget as HTMLImageElement).style.display = "none";
          }}
        />
      ) : (
        <div className="flex h-16 w-16 shrink-0 items-center justify-center rounded-xl border border-border bg-surface text-2xl font-bold text-accent">
          {profile.name.split(" ").pop()?.[0] ?? "?"}
        </div>
      )}
      <div className="min-w-0 flex-1">
        <h2 className="text-xl font-bold text-fg">{w.label ?? profile.name}</h2>
        {dob && (
          <div className="mt-0.5 flex items-center gap-1.5 text-xs text-muted">
            <Cake className="h-3.5 w-3.5" />
            Born {new Date(dob).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" })}
            {age !== null && <span>· {age} yrs</span>}
          </div>
        )}
        {/* Gemini taxonomy: role / bowling type / batting slot / country */}
        {tax && (
          <div className="mt-2 flex flex-wrap items-center gap-2">
            {tax.primary_role && <Badge tone="accent">{tax.primary_role.replace("_", "-")}</Badge>}
            {tax.bowling_style && tax.bowling_category !== "none" && (
              <Badge tone={tax.bowling_category === "spin" ? "willow" : "ball"}>
                {tax.bowling_style.replace(/-/g, " ")}
              </Badge>
            )}
            {tax.batting_position && <Badge>{POS_LABEL[tax.batting_position] ?? tax.batting_position}</Badge>}
            {tax.country && <Badge>{tax.country}</Badge>}
          </div>
        )}
        <div className="mt-2 flex flex-wrap items-center gap-2">
          {bat && <Badge tone="accent">batting value {fmt(bat.value, 3)}</Badge>}
          {bowl && bowl.balls > 60 && <Badge tone="willow">bowling value {fmt(bowl.value, 3)}</Badge>}
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
  const { collection } = useStore();
  const { options, byName, loading: pl } = usePlayers(collection);
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();

  // resolve incoming ?name= / ?cid= to a cricsheet_id
  const qName = params.get("name");
  const qCid = params.get("cid");
  const [cid, setCid] = useState<string | null>(null);

  useEffect(() => {
    if (qCid) setCid(qCid);
    else if (qName && byName.has(qName)) setCid(byName.get(qName)!.cricsheet_id);
  }, [qName, qCid, byName]);

  const { data: profile, loading, error } = useAsync<Profile | null>(
    () => (cid ? getProfile(collection, cid) : Promise.resolve(null)),
    [collection, cid],
  );
  const { data: cohorts } = useAsync(
    () => (cid ? getCohorts(collection, cid) : Promise.resolve(null)),
    [collection, cid],
  );

  function pick(id: string | null) {
    setCid(id);
    if (id) setParams({ cid: id });
    else setParams({});
  }

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

      {!cid ? (
        <Empty>Pick a player to see their dossier.</Empty>
      ) : loading ? (
        <Spinner label="Building dossier…" />
      ) : error ? (
        <ErrorBox message={error} />
      ) : !profile ? (
        <Empty>No profile found.</Empty>
      ) : (
        <div className="space-y-5 animate-fade-up">
          {/* identity */}
          <Identity profile={profile} bat={bat} bowl={bowl} />

          {/* career tiles */}
          {career && (
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
              <StatTile label="Runs" value={fmt(career.career_runs, 0)} />
              <StatTile label="Balls faced" value={fmt(career.career_balls_faced, 0)} />
              <StatTile label="Innings" value={fmt(career.career_innings, 0)} />
              <StatTile label="Fours / Sixes" value={`${career.career_fours ?? 0}/${career.career_sixes ?? 0}`} />
              <StatTile label="Wickets" value={fmt(career.career_wickets, 0)} />
              <StatTile label="Balls bowled" value={fmt(career.career_legal_balls_bowled, 0)} />
            </div>
          )}

          {/* bayes skill axes */}
          <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
            {bat && (
              <Card>
                <CardHeader title="Batting skill" subtitle="Two latent axes — scoring & survival — with model uncertainty" right={<Activity className="h-4 w-4 text-accent" />} />
                <div className="space-y-4 p-5">
                  <SkillAxis label="Scoring (runs added)" mean={num(bat.skill)} sd={num(bat.skill_sd)} hint="how fast they score above a replacement batter" />
                  <SkillAxis label="Survival (wicket-avoidance)" mean={num(bat.survival_skill)} sd={num(bat.survival_skill_sd)} hint="how well they avoid getting out per ball" />
                  <div className="text-xs text-muted">From {fmt(bat.balls, 0)} balls faced.</div>
                </div>
              </Card>
            )}
            {bowl && (bowl.balls ?? 0) > 60 && (
              <Card>
                <CardHeader title="Bowling skill" subtitle="Two latent axes — economy & strike — with model uncertainty" right={<Shield className="h-4 w-4 text-willow" />} />
                <div className="space-y-4 p-5">
                  <SkillAxis label="Economy (run suppression)" mean={num(bowl.skill)} sd={num(bowl.skill_sd)} hint="how few runs they concede per ball" />
                  <SkillAxis label="Strike (wicket-taking)" mean={num(bowl.strike_skill)} sd={num(bowl.strike_skill_sd)} hint="how often they take a wicket per ball" />
                  <div className="text-xs text-muted">From {fmt(bowl.balls, 0)} balls bowled.</div>
                </div>
              </Card>
            )}
          </div>

          {/* novel metrics */}
          {metrics && Object.values(metrics).some(Boolean) && (
            <div>
              <h3 className="mb-3 text-sm font-semibold text-fg">Novel metrics</h3>
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
                {Object.entries(metrics).map(([slug, m]) => (m ? <MetricCard key={slug} slug={slug} m={m} /> : null))}
              </div>
            </div>
          )}

          {/* dismissal fingerprint */}
          <DismissalFingerprint fp={profile.dismissal_fingerprint} />

          {/* style twins + cohorts */}
          <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
            <Card>
              <CardHeader title="Style twins" subtitle="Nearest players in feature space" right={<Users2 className="h-4 w-4 text-accent" />} />
              <div className="p-3">
                <TwinList twins={profile.style_twins_batter} byName={byName} onPick={(c) => navigate(`/player?cid=${c}`)} role="batter" />
                <TwinList twins={profile.style_twins_bowler} byName={byName} onPick={(c) => navigate(`/player?cid=${c}`)} role="bowler" />
              </div>
            </Card>
            <Card>
              <CardHeader title="Graph cohort" subtitle="Players who faced the same bowlers / shared a side" />
              <div className="p-3">
                <CohortList rows={cohorts?.co_faced ?? []} label="Faced the same bowlers" keyField="shared_bowlers" byName={byName} onPick={(c) => navigate(`/player?cid=${c}`)} />
              </div>
            </Card>
          </div>
        </div>
      )}
    </>
  );
}

function TwinList({
  twins,
  role,
  byName,
  onPick,
}: {
  twins: Record<string, unknown>[] | null;
  role: string;
  byName: Map<string, { cricsheet_id: string }>;
  onPick: (cid: string) => void;
}) {
  if (!twins || twins.length === 0) return null;
  return (
    <div className="mb-2">
      <div className="px-2 pb-1 text-[11px] uppercase tracking-wider text-muted">{role}</div>
      {twins.slice(0, 6).map((t, i) => {
        const name = String(t.name);
        const cid = byName.get(name)?.cricsheet_id;
        const dist = Number(t.distance);
        const sim = Number.isFinite(dist) ? Math.max(0, 1 - dist) : null;
        return (
          <button
            key={i}
            disabled={!cid}
            onClick={() => cid && onPick(cid)}
            className="flex w-full items-center justify-between rounded-md px-2 py-1.5 text-sm hover:bg-surface disabled:opacity-60"
          >
            <span className="text-fg">{name}</span>
            {sim !== null && <span className="stat-num text-xs text-muted">{(sim * 100).toFixed(1)}% alike</span>}
          </button>
        );
      })}
    </div>
  );
}

function CohortList({
  rows,
  label,
  keyField,
  byName,
  onPick,
}: {
  rows: Record<string, unknown>[];
  label: string;
  keyField: string;
  byName: Map<string, { cricsheet_id: string }>;
  onPick: (cid: string) => void;
}) {
  if (!rows.length) return <div className="px-2 py-3 text-sm text-muted">No graph cohort available.</div>;
  return (
    <div>
      <div className="px-2 pb-1 text-[11px] uppercase tracking-wider text-muted">{label}</div>
      {rows.slice(0, 10).map((r, i) => {
        const name = String(r.name);
        const cid = byName.get(name)?.cricsheet_id;
        return (
          <button
            key={i}
            disabled={!cid}
            onClick={() => cid && onPick(cid)}
            className="flex w-full items-center justify-between rounded-md px-2 py-1.5 text-sm hover:bg-surface disabled:opacity-60"
          >
            <span className="text-fg">{name}</span>
            <span className="stat-num text-xs text-muted">{String(r[keyField] ?? "")} shared</span>
          </button>
        );
      })}
    </div>
  );
}
