import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Network, Users, Handshake, Repeat } from "lucide-react";
import { useStore } from "@/lib/store";
import { usePlayers } from "@/lib/usePlayers";
import { useAsync } from "@/lib/useAsync";
import { getCohorts, type Cohorts } from "@/lib/data";
import { Combobox } from "@/components/Combobox";
import { PageTitle, Card, CardHeader, Spinner, Empty, Badge } from "@/components/ui";

function CohortColumn({
  title,
  icon,
  subtitle,
  rows,
  metricKey,
  metricLabel,
  onPick,
}: {
  title: string;
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
          <div className="px-3 py-6 text-center text-sm text-muted">No cohort data.</div>
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
                <span className="flex items-center gap-2">
                  <span className="stat-num w-5 text-xs text-muted">{i + 1}</span>
                  <span className="text-fg">{String(r.name)}</span>
                  {r.role ? <Badge>{String(r.role)}</Badge> : null}
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
  const { options } = usePlayers(collection);
  const navigate = useNavigate();
  const [cid, setCid] = useState<string | null>(null);

  const { data, loading } = useAsync<Cohorts | null>(
    () => (cid ? getCohorts(collection, cid) : Promise.resolve(null)),
    [collection, cid],
  );

  return (
    <>
      <PageTitle
        title="Scout graph"
        icon={<Network className="h-6 w-6" />}
        desc="A Neo4j graph links players through who they faced and who they played alongside. Use it to find stylistic twins (same bowlers troubled them) and ready-made replacements for an unavailable player."
      />

      <div className="mb-6 max-w-md">
        <Combobox options={options} value={cid} onChange={setCid} placeholder="Search a player…" />
      </div>

      {!cid ? (
        <Empty>Pick a player to traverse their cohort.</Empty>
      ) : loading ? (
        <Spinner label="Querying the graph…" />
      ) : !data ? (
        <Empty>No graph cohort for this player.</Empty>
      ) : (
        <div className="grid grid-cols-1 gap-5 animate-fade-up lg:grid-cols-3">
          <CohortColumn
            title="Faced the same bowlers"
            icon={<Users className="h-4 w-4 text-accent" />}
            subtitle="Batting affinity — troubled by the same attacks"
            rows={data.co_faced}
            metricKey="shared_bowlers"
            metricLabel="shared"
            onPick={(c) => navigate(`/player?cid=${c}`)}
          />
          <CohortColumn
            title="Teammate overlap"
            icon={<Handshake className="h-4 w-4 text-willow" />}
            subtitle="Played the most alongside this player"
            rows={data.teammates}
            metricKey="shared_teammates"
            metricLabel="games"
            onPick={(c) => navigate(`/player?cid=${c}`)}
          />
          <CohortColumn
            title="Find a replacement"
            icon={<Repeat className="h-4 w-4 text-accent" />}
            subtitle="Closest available substitutes by role + graph similarity"
            rows={data.find_replacement}
            metricKey="shared"
            metricLabel="shared"
            onPick={(c) => navigate(`/player?cid=${c}`)}
          />
        </div>
      )}
    </>
  );
}
