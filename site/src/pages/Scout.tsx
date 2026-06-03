import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Network, Users, Sprout, Plane } from "lucide-react";
import { usePlayers } from "@/lib/usePlayers";
import { useAsync } from "@/lib/useAsync";
import { getScoutIndex, type ScoutPlayer, type ScoutIndex } from "@/lib/data";
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

// similar = same role (+ same bowling type for bowlers), nearest skill standing
function similarTo(sel: ScoutPlayer, pool: ScoutPlayer[]): { p: ScoutPlayer; sim: number }[] {
  return pool
    .filter((p) => p.cricsheet_id !== sel.cricsheet_id && p.role === sel.role)
    .filter((p) => sel.role !== "bowler" || p.bowling_category === sel.bowling_category)
    .map((p) => ({ p, sim: Math.max(0, 1 - Math.abs(p.z - sel.z) / 2.5) }))
    .sort((a, b) => b.sim - a.sim)
    .slice(0, 8);
}

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
          <li>• <b className="text-fg">Overseas (BBL)</b> — Big Bash players of the same mould.</li>
        </ul>
        <p>
          "Skill standing" is the player's Bayesian value expressed as a z-score <i>within its own
          competition</i> (mean 0, sd 1), so a star in SMAT and a star in the IPL line up even though
          the raw numbers aren't comparable across tiers. Similarity = how close those standings are.
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
  linkable,
  navigate,
}: {
  title: string;
  icon: React.ReactNode;
  subtitle: string;
  rows: { p: ScoutPlayer; sim: number }[];
  linkable: boolean;
  navigate: (path: string) => void;
}) {
  return (
    <Card>
      <CardHeader title={<span className="flex items-center gap-2">{icon}{title}</span>} subtitle={subtitle} />
      <div className="p-2">
        {rows.length === 0 ? (
          <div className="px-3 py-6 text-center text-sm text-muted">No close match of this archetype.</div>
        ) : (
          rows.map(({ p, sim }, i) => (
            <button
              key={p.cricsheet_id}
              disabled={!linkable}
              onClick={() => linkable && navigate(`/player?cid=${p.cricsheet_id}`)}
              className="flex w-full items-center justify-between gap-2 rounded-md px-3 py-2 text-left text-sm hover:bg-surface disabled:cursor-default"
            >
              <span className="flex min-w-0 items-center gap-2">
                <span className="stat-num w-5 shrink-0 text-xs text-muted">{i + 1}</span>
                <span className="truncate text-fg">{p.name}</span>
                {p.country && <span className="shrink-0 text-[11px] text-muted">{p.country}</span>}
              </span>
              <span className="flex shrink-0 items-center gap-2">
                <span className="stat-num text-xs text-muted">{p.last_match_date?.slice(0, 4)}</span>
                <span className="w-12 text-right">
                  <Badge tone={sim > 0.8 ? "accent" : sim > 0.6 ? "willow" : "muted"}>{Math.round(sim * 100)}%</Badge>
                </span>
              </span>
            </button>
          ))
        )}
      </div>
    </Card>
  );
}

export function Scout() {
  const navigate = useNavigate();
  const { options } = usePlayers("ipl"); // nice full-name search
  const idx = useAsync<ScoutIndex>(() => getScoutIndex("ipl"), []);
  const [cid, setCid] = useState<string | null>(null);

  const iplById = useMemo(() => {
    const m = new Map<string, ScoutPlayer>();
    for (const p of idx.data?.ipl ?? []) m.set(p.cricsheet_id, p);
    return m;
  }, [idx.data]);

  // only IPL players that exist in the scout index are pickable
  const pickOptions = useMemo(() => options.filter((o) => iplById.has(o.value)), [options, iplById]);
  const sel = cid ? iplById.get(cid) : null;

  return (
    <>
      <PageTitle
        title="Scout"
        icon={<Network className="h-6 w-6" />}
        desc="Pick an active IPL player and find others of the same mould at three levels — IPL peers, uncapped Indian prospects (SMAT), and overseas options (BBL) — ranked by how close their skill standing is."
      />

      <ScoutMath />

      <div className="mb-4 flex flex-wrap items-center gap-3">
        <Combobox options={pickOptions} value={cid} onChange={setCid} placeholder="Search an active IPL player…" className="max-w-md flex-1" />
        {sel && (
          <div className="flex items-center gap-2 text-sm text-muted">
            <Badge tone="accent">{sel.role.replace("_", "-")}</Badge>
            {sel.role === "bowler" && sel.bowling_category && (
              <Badge tone={sel.bowling_category === "spin" ? "willow" : "ball"}>{sel.bowling_category}</Badge>
            )}
            {sel.batting_position && <Badge>{POS[sel.batting_position] ?? sel.batting_position}</Badge>}
            <span className="text-xs">standing {fmt(sel.z, 2)}</span>
          </div>
        )}
      </div>

      {idx.loading ? (
        <Spinner label="Loading scout index…" />
      ) : !sel ? (
        <Empty>Pick an IPL player to scout look-alikes across IPL, SMAT and the BBL.</Empty>
      ) : (
        <div className="grid grid-cols-1 gap-5 animate-fade-up lg:grid-cols-3">
          <TierPanel
            title="IPL peers"
            icon={<Users className="h-4 w-4 text-accent" />}
            subtitle="Most-similar active IPL players"
            rows={similarTo(sel, idx.data!.ipl)}
            linkable
            navigate={navigate}
          />
          <TierPanel
            title="Uncapped · SMAT"
            icon={<Sprout className="h-4 w-4 text-willow" />}
            subtitle="Domestic Indian prospects of the same mould"
            rows={similarTo(sel, idx.data!.smat)}
            linkable={false}
            navigate={navigate}
          />
          <TierPanel
            title="Overseas · BBL"
            icon={<Plane className="h-4 w-4 text-accent" />}
            subtitle="Big Bash players of the same mould"
            rows={similarTo(sel, idx.data!.bbl)}
            linkable={false}
            navigate={navigate}
          />
        </div>
      )}
    </>
  );
}
