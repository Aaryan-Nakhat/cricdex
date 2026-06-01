import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Network, Users, Handshake, Repeat } from "lucide-react";
import { useStore } from "@/lib/store";
import { usePlayers } from "@/lib/usePlayers";
import { useAsync } from "@/lib/useAsync";
import { getCohorts, type Cohorts } from "@/lib/data";
import { Combobox } from "@/components/Combobox";
import { PageTitle, Card, CardHeader, Spinner, Empty, Badge, InfoTip, Collapsible } from "@/components/ui";

function ScoutMath() {
  return (
    <Collapsible title="How the scout graph works (plain English)" icon={<Network className="h-4 w-4" />}>
      <div className="space-y-3 text-sm leading-relaxed text-muted">
        <p>
          Every player is a <b>dot</b>. We draw two kinds of lines between them, straight from the
          ball-by-ball data:
        </p>
        <ul className="space-y-1.5">
          <li>• <b className="text-fg">faced</b> — this batter faced that bowler (a lot)</li>
          <li>• <b className="text-fg">teammate</b> — they played in the same XI</li>
        </ul>
        <p>Then we just count overlaps — no skill model involved here, only who-met-whom:</p>
        <ul className="space-y-1.5">
          <li>
            • <b className="text-fg">Faced the same bowlers</b> — batters who battled the same attacks.
            Shared-bowler count = how alike their on-field challenge was (a batting-style twin).
          </li>
          <li>
            • <b className="text-fg">Teammate overlap</b> — who shared the most XIs with this player.
          </li>
          <li>
            • <b className="text-fg">Find a replacement</b> — graph-similar players, then filtered by
            role/recency. Because "shared opponents" alone can pair a seamer with a leg-spinner, the{" "}
            <b>same bowling type only</b> toggle keeps replacements seam↔seam or spin↔spin (using the
            Gemini-classified type).
          </li>
        </ul>
        <p className="rounded-lg border border-willow/20 bg-willow/5 px-3 py-2 text-xs">
          <b className="text-willow">Note:</b> "faced the same bowlers" measures shared <i>experience</i>,
          not similar skill — so two very different batters can be high if they came up against the same
          attacks.
        </p>
      </div>
    </Collapsible>
  );
}

function TypeBadge({ row }: { row: Record<string, unknown> }) {
  const cat = row.bowling_category as string | undefined;
  const role = row.primary_role as string | undefined;
  return (
    <span className="flex items-center gap-1">
      {role && <Badge>{String(role).replace("_", "-")}</Badge>}
      {cat === "seam" && <Badge tone="ball">seam</Badge>}
      {cat === "spin" && <Badge tone="willow">spin</Badge>}
    </span>
  );
}

function CohortColumn({
  title,
  icon,
  subtitle,
  rows,
  metricKey,
  metricLabel,
  onPick,
}: {
  title: React.ReactNode;
  icon: React.ReactNode;
  subtitle: string;
  rows: Record<string, unknown>[];
  metricKey: string;
  metricLabel: string;
  onPick: (cid: string) => void;
}) {
  return (
    <Card>
      <CardHeader title={<span className="flex items-center gap-2">{icon}{title}</span>} subtitle={subtitle} />
      <div className="p-2">
        {rows.length === 0 ? (
          <div className="px-3 py-6 text-center text-sm text-muted">No matching cohort.</div>
        ) : (
          rows.slice(0, 12).map((r, i) => {
            const cid = r.cricsheet_id ? String(r.cricsheet_id) : null;
            return (
              <button
                key={i}
                disabled={!cid}
                onClick={() => cid && onPick(cid)}
                className="flex w-full items-center justify-between gap-2 rounded-md px-3 py-2 text-left text-sm hover:bg-surface disabled:opacity-60"
              >
                <span className="flex min-w-0 items-center gap-2">
                  <span className="stat-num w-5 shrink-0 text-xs text-muted">{i + 1}</span>
                  <span className="truncate text-fg">{String(r.name)}</span>
                  <TypeBadge row={r} />
                </span>
                <span className="stat-num shrink-0 text-xs text-muted">
                  {String(r[metricKey] ?? "")} {metricLabel}
                </span>
              </button>
            );
          })
        )}
      </div>
    </Card>
  );
}

export function Scout() {
  const { collection } = useStore();
  const { options, byId } = usePlayers(collection);
  const navigate = useNavigate();
  const [cid, setCid] = useState<string | null>(null);
  const [sameType, setSameType] = useState(true);

  const { data, loading } = useAsync<Cohorts | null>(
    () => (cid ? getCohorts(collection, cid) : Promise.resolve(null)),
    [collection, cid],
  );

  const player = cid ? byId.get(cid) : null;
  const playerCat = player?.bowling_category ?? null;

  // "Same bowling type" makes find-replacement actually useful: a seamer
  // should be replaced by seamers, not Amit Mishra.
  const replacements = useMemo(() => {
    const rows = data?.find_replacement ?? [];
    if (!sameType || !playerCat) return rows;
    return rows.filter((r) => !r.bowling_category || r.bowling_category === playerCat);
  }, [data, sameType, playerCat]);

  return (
    <>
      <PageTitle
        title="Scout graph"
        icon={<Network className="h-6 w-6" />}
        desc="A Neo4j graph links players through who they faced and who they played alongside. Find stylistic twins (same bowlers troubled them) and ready-made replacements for an unavailable player."
      />

      <ScoutMath />

      <div className="mb-4 flex flex-wrap items-center gap-3">
        <Combobox options={options} value={cid} onChange={setCid} placeholder="Search a player…" className="max-w-md flex-1" />
        {player && (playerCat || player.primary_role) && (
          <div className="flex items-center gap-2 text-sm text-muted">
            <span>this player:</span>
            <TypeBadge row={{ primary_role: player.primary_role, bowling_category: player.bowling_category }} />
          </div>
        )}
      </div>

      {cid && (
        <label className="mb-4 flex w-fit cursor-pointer items-center gap-2 rounded-lg border border-border bg-surface/50 px-3 py-2 text-sm text-muted">
          <input
            type="checkbox"
            checked={sameType}
            onChange={(e) => setSameType(e.target.checked)}
            className="accent-[#34d399]"
          />
          Replacements: same bowling type only
          <InfoTip title="Why">
            Find-replacement walks the graph by shared opponents, which can surface a spinner as a
            seamer's "twin". This filter keeps replacements to the same bowling category (seam/spin)
            as the selected player. Off = raw graph similarity.
          </InfoTip>
        </label>
      )}

      {!cid ? (
        <Empty>Pick a player to traverse their cohort.</Empty>
      ) : loading ? (
        <Spinner label="Querying the graph…" />
      ) : !data ? (
        <Empty>No graph cohort for this player.</Empty>
      ) : (
        <div className="grid grid-cols-1 gap-5 animate-fade-up lg:grid-cols-3">
          <CohortColumn
            title={<>Faced the same bowlers</>}
            icon={<Users className="h-4 w-4 text-accent" />}
            subtitle="Batting affinity — troubled by the same attacks"
            rows={data.co_faced}
            metricKey="shared_bowlers"
            metricLabel="shared"
            onPick={(c) => navigate(`/player?cid=${c}`)}
          />
          <CohortColumn
            title={<>Teammate overlap</>}
            icon={<Handshake className="h-4 w-4 text-willow" />}
            subtitle="Played the most alongside this player"
            rows={data.teammates}
            metricKey="shared_teammates"
            metricLabel="games"
            onPick={(c) => navigate(`/player?cid=${c}`)}
          />
          <CohortColumn
            title={
              <span className="flex items-center gap-1.5">
                Find a replacement
                {sameType && playerCat && <Badge tone="accent">{playerCat} only</Badge>}
              </span>
            }
            icon={<Repeat className="h-4 w-4 text-accent" />}
            subtitle="Closest available substitutes by role + graph similarity"
            rows={replacements}
            metricKey="shared"
            metricLabel="shared"
            onPick={(c) => navigate(`/player?cid=${c}`)}
          />
        </div>
      )}
    </>
  );
}
