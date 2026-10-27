import { Link } from "react-router-dom";
import { ArrowRight, Database, CalendarClock, Trophy, Users, CircleDot, Layers, Gavel, Scale, ClipboardList } from "lucide-react";
import { useStore } from "@/lib/store";
import { useAsync } from "@/lib/useAsync";
import { getLeaderboard } from "@/lib/data";
import { usePlayers } from "@/lib/usePlayers";
import { METRIC_BY_SLUG, fmtMetric, primaryCol } from "@/lib/metrics";
import { MetricInfo } from "@/components/MetricInfo";
import { NAV, NAV_GROUPS } from "@/lib/nav";
import { Card, StatTile, Badge } from "@/components/ui";
import { AUTHOR, AUTHOR_URL, cn, collectionLabel, fmt, prettyDate } from "@/lib/utils";

// The IPL 2027 retention deadline the hero leads with (as reported; config/competitions.toml
// `retention_deadline`, also in keep.json, which the home page doesn't load).
const DEADLINE = "2026-11-15";
const DEADLINE_LABEL = new Date(`${DEADLINE}T00:00:00`).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });

export function Overview() {
  const daysLeft = Math.ceil((new Date(`${DEADLINE}T23:59:59`).getTime() - Date.now()) / 86400000);
  const { meta, collection, collections, setCollection } = useStore();
  const ngi = useAsync(() => getLeaderboard(collection, "ngi").catch(() => []), [collection]);
  const { nameOf } = usePlayers(collection);
  const ngiDef = METRIC_BY_SLUG.ngi;
  const ngiCol = primaryCol(ngiDef);
  // the biggest match-winners among active regulars: win chance added per match, 25+ matches
  const winners = (ngi.data ?? [])
    .filter((r) => Number(r.matches ?? 0) >= 25 && (r as Record<string, unknown>).active !== false && Number.isFinite(Number(r.ngi_per_match)))
    .sort((a, b) => Number(b.ngi_per_match) - Number(a.ngi_per_match))
    .slice(0, 5);

  return (
    <div>
      {/* hero */}
      <div className="card relative mb-8 overflow-hidden px-6 py-10 sm:px-10 sm:py-12">
        <div className="pointer-events-none absolute -right-24 -top-24 h-72 w-72 rounded-full bg-accent/15 blur-3xl" />
        <div className="pointer-events-none absolute -bottom-28 left-1/3 h-64 w-64 rounded-full bg-gold/10 blur-3xl" />
        <div className="relative max-w-2xl">
          <Badge tone="accent" className="mb-4">
            <CalendarClock className="h-3 w-3" /> IPL 2027 retention deadline: {DEADLINE_LABEL}
            {daysLeft >= 0 ? ` (${daysLeft} day${daysLeft === 1 ? "" : "s"} away)` : ""}
          </Badge>
          <h1 className="text-3xl font-extrabold leading-tight tracking-tight text-fg sm:text-[42px]">
            Who will each IPL team keep? <span className="grad-text">Our calls, before the deadline.</span>
          </h1>
          <p className="mt-4 text-base leading-relaxed text-muted">
            Every contracted player at all ten franchises gets two answers. What his team will likely do, learned
            from every real retention deadline since 2018. And whether he is worth what keeping him costs, at the
            prices players like him fetch at auction. Then the squad that follows: purse left, open places and the
            role gaps to fill.
          </p>
          <div className="mt-7 flex flex-wrap gap-3">
            <Link to="/keep" className="btn btn-accent">
              <Scale className="h-4 w-4" /> See the retention calls <ArrowRight className="h-4 w-4" />
            </Link>
            <Link to="/bidplan" className="btn">
              <ClipboardList className="h-4 w-4" /> Plan the auction bids
            </Link>
            <Link to="/auction?run=1" className="btn">
              <Gavel className="h-4 w-4" /> Run the auction room
            </Link>
            <Link to="/scout" className="btn">
              Scout a player
            </Link>
            <Link to="/about" className="btn">
              How it works
            </Link>
          </div>
          <p className="mt-5 text-xs text-muted">
            by{" "}
            <a href={AUTHOR_URL} target="_blank" rel="noreferrer" className="font-semibold text-fg hover:text-accent-glow">
              {AUTHOR}
            </a>{" "}
            · open cricket intelligence from Cricsheet ball-by-ball data
          </p>
        </div>
      </div>

      {/* dataset stats */}
      <div className="mb-3 flex items-center gap-2 text-sm text-muted">
        <Database className="h-4 w-4 text-accent" />
        <span>
          Current league: <span className="font-semibold text-fg">{collectionLabel(collection)}</span>
        </span>
      </div>
      <div className="mb-8 grid grid-cols-2 gap-3 sm:grid-cols-4">
        <StatTile label="Matches" value={fmt(meta?.n_matches ?? 0)} icon={<Trophy className="h-3.5 w-3.5" />} />
        <StatTile label="Balls bowled" value={fmt(meta?.n_balls ?? 0)} icon={<CircleDot className="h-3.5 w-3.5" />} />
        <StatTile label="Players rated" value={fmt(meta?.n_players ?? 0)} icon={<Users className="h-3.5 w-3.5" />} />
        <StatTile
          label="Data up to"
          value={prettyDate(meta?.data_as_of)}
          hint="latest match"
          icon={<CalendarClock className="h-3.5 w-3.5" />}
        />
      </div>

      {/* match-winners, in human units */}
      {winners.length > 0 && (
        <Card className="mb-8 px-5 py-4">
          <div className="mb-1 flex items-center gap-2">
            <h2 className="text-sm font-semibold text-fg">Biggest match-winners right now</h2>
            <MetricInfo m={ngiDef} />
          </div>
          <p className="mb-3 text-xs text-muted">
            Win chance added per match — active players with 25+ matches. +5% means he adds five percentage points to
            his side's chance of winning in a typical game.
          </p>
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-5">
            {winners.map((r, i) => (
              <Link
                key={String(r.name)}
                to={r.cricsheet_id ? `/player?cid=${String(r.cricsheet_id)}` : `/player?name=${encodeURIComponent(String(r.name))}`}
                className="rounded-lg border border-border bg-surface/50 px-3 py-2 hover:border-accent/40"
              >
                <div className="text-[11px] text-muted">#{i + 1}</div>
                <div className="truncate text-sm font-semibold text-fg">{nameOf(String(r.name), r.cricsheet_id)}</div>
                <div className="stat-num text-base font-bold text-accent-glow">{fmtMetric(r.ngi_per_match, ngiCol)}</div>
                <div className="text-[11px] text-muted">
                  {fmtMetric(r.ngi_total, { digits: 1 })} wins added · {String(r.matches)} matches
                </div>
              </Link>
            ))}
          </div>
        </Card>
      )}

      {/* every league at a glance */}
      {collections.length > 1 && (
        <div className="mb-10">
          <h2 className="mb-3 flex items-center gap-2 text-lg font-bold text-fg">
            <Layers className="h-4 w-4 text-accent" /> Leagues
          </h2>
          <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-2 lg:grid-cols-4">
            {collections.map((c) => (
              <button
                key={c.collection}
                onClick={() => setCollection(c.collection)}
                aria-pressed={c.collection === collection}
                className={cn(
                  "card card-hover px-4 py-3 text-left",
                  c.collection === collection && "border-accent/50 shadow-glow",
                )}
              >
                <div className="truncate text-sm font-semibold text-fg">{collectionLabel(c.collection)}</div>
                <div className="mt-1 flex flex-wrap gap-x-3 text-xs text-muted">
                  <span className="stat-num">{fmt(c.n_matches)} matches</span>
                  <span>to {prettyDate(c.data_as_of)}</span>
                </div>
              </button>
            ))}
          </div>
        </div>
      )}

      {/* feature grid, by section */}
      {NAV_GROUPS.filter((g) => g !== "Start").map((group) => (
        <div key={group} className="mb-8">
          <h2 className="eyebrow mb-3">{group}</h2>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {NAV.filter((n) => n.group === group).map((item) => (
              <Link key={item.to} to={item.to} className="rounded-2xl">
                <Card className="card-hover group h-full px-5 py-4">
                  <div className="flex items-center gap-2.5">
                    <span className="flex h-9 w-9 items-center justify-center rounded-xl border border-border bg-surface text-accent transition-colors group-hover:border-accent/40">
                      <item.icon className="h-4 w-4" />
                    </span>
                    <h3 className="font-semibold text-fg">{item.label}</h3>
                    <ArrowRight className="ml-auto h-4 w-4 text-muted opacity-0 transition-opacity group-hover:opacity-100" />
                  </div>
                  <p className="mt-2.5 text-sm leading-relaxed text-muted">{item.blurb}</p>
                </Card>
              </Link>
            ))}
          </div>
        </div>
      ))}

      {/* freshness footnote */}
      <div className="mt-6 flex items-center gap-2 text-xs text-muted">
        <CalendarClock className="h-3.5 w-3.5 shrink-0" />
        Data is computed offline and refreshed on demand. Figures are accurate up to{" "}
        {prettyDate(meta?.data_as_of)} — the most recent match in this league.
      </div>
    </div>
  );
}
