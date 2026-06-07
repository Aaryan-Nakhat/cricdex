import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Handshake } from "lucide-react";
import { useStore } from "@/lib/store";
import { useAsync } from "@/lib/useAsync";
import { getPartnerships, type Partnership } from "@/lib/data";
import { usePlayers } from "@/lib/usePlayers";
import { Combobox } from "@/components/Combobox";
import { DataTable, type Col } from "@/components/DataTable";
import { PageTitle, Card, CardHeader, Spinner, ErrorBox, Empty } from "@/components/ui";

type Row = Record<string, unknown>;

// a picked player's partners
const PARTNER_COLS: Col<Row>[] = [
  { key: "partner", label: "Partner", primary: false },
  { key: "runs", label: "Runs", align: "right", digits: 0, primary: true },
  { key: "innings", label: "Inns", align: "right", digits: 0 },
  { key: "best", label: "Best", align: "right", digits: 0 },
  { key: "avg", label: "Avg", align: "right", digits: 1 },
  { key: "sr", label: "SR", align: "right", digits: 1 },
  { key: "fifties", label: "50+", align: "right", digits: 0 },
  { key: "hundreds", label: "100+", align: "right", digits: 0 },
];

// the all-time best stands
const BEST_COLS: Col<Row>[] = [
  { key: "pair", label: "Partnership", primary: false },
  { key: "runs", label: "Runs", align: "right", digits: 0, primary: true },
  { key: "innings", label: "Inns", align: "right", digits: 0 },
  { key: "best", label: "Best", align: "right", digits: 0 },
  { key: "avg", label: "Avg", align: "right", digits: 1 },
  { key: "sr", label: "SR", align: "right", digits: 1 },
  { key: "hundreds", label: "100+", align: "right", digits: 0 },
];

export function Partnerships() {
  const { collection } = useStore();
  const navigate = useNavigate();
  const { options } = usePlayers(collection);
  const { data, loading, error } = useAsync(() => getPartnerships(collection), [collection]);
  const [cid, setCid] = useState<string | null>(null);
  const [minRuns, setMinRuns] = useState(50);

  const pairs = data?.pairs ?? [];

  const partnerRows = useMemo<Row[]>(() => {
    if (!cid) return [];
    return pairs
      .filter((p) => (p.a_cid === cid || p.b_cid === cid) && p.runs >= minRuns)
      .map((p: Partnership) => ({
        partner: p.a_cid === cid ? p.b : p.a,
        partner_cid: p.a_cid === cid ? p.b_cid : p.a_cid,
        runs: p.runs,
        innings: p.innings,
        best: p.best,
        avg: p.avg,
        sr: p.sr,
        fifties: p.fifties,
        hundreds: p.hundreds,
      }))
      .sort((x, y) => Number(y.runs) - Number(x.runs));
  }, [pairs, cid, minRuns]);

  const bestRows = useMemo<Row[]>(
    () =>
      pairs
        .filter((p) => p.runs >= minRuns)
        .slice(0, 60)
        .map((p) => ({
          pair: `${p.a} & ${p.b}`,
          runs: p.runs,
          innings: p.innings,
          best: p.best,
          avg: p.avg,
          sr: p.sr,
          hundreds: p.hundreds,
        })),
    [pairs, minRuns],
  );

  return (
    <>
      <PageTitle
        title="Partnerships"
        icon={<Handshake className="h-6 w-6" />}
        desc="Batter-pair stands — who builds runs together. Pick a player for their most productive partners, or browse the all-time best partnerships. Runs include extras added while both were at the crease."
      />

      <div className="mb-4 flex flex-wrap items-center gap-3">
        <Combobox
          options={options}
          value={cid}
          onChange={setCid}
          placeholder="Search a player for their partners…"
          className="max-w-md flex-1"
        />
        <label className="flex items-center gap-2 text-sm text-muted">
          <span>Min runs</span>
          <input
            type="number"
            min={0}
            step={10}
            value={minRuns}
            onChange={(e) => setMinRuns(Math.max(0, Number(e.target.value) || 0))}
            className="input w-20 py-1.5"
          />
        </label>
      </div>

      {loading ? (
        <Spinner />
      ) : error ? (
        <ErrorBox message={error} />
      ) : (
        <div className="space-y-5 animate-fade-up">
          {cid && (
            <div>
              <div className="mb-2 text-sm font-semibold text-fg">
                Most productive partners
              </div>
              {partnerRows.length ? (
                <DataTable
                  rows={partnerRows}
                  cols={PARTNER_COLS}
                  initialSort={{ key: "runs", dir: "desc" }}
                  onRowClick={(r) =>
                    r.partner_cid && navigate(`/player?cid=${String(r.partner_cid)}`)
                  }
                />
              ) : (
                <Empty>No partnerships at ≥ {minRuns} runs for this player.</Empty>
              )}
            </div>
          )}

          <Card>
            <CardHeader
              title="Best partnerships"
              subtitle={`All-time top stands by aggregate runs${cid ? "" : " — pick a player above for a per-player view"}`}
            />
            <div className="p-2">
              {bestRows.length ? (
                <DataTable rows={bestRows} cols={BEST_COLS} initialSort={{ key: "runs", dir: "desc" }} />
              ) : (
                <Empty>No partnerships meet the filter.</Empty>
              )}
            </div>
          </Card>
        </div>
      )}
    </>
  );
}
