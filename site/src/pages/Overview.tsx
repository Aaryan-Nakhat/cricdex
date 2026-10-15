import { Link } from "react-router-dom";
import { ArrowRight, Database, CalendarClock, Trophy, Users, CircleDot, Layers } from "lucide-react";
import { useStore } from "@/lib/store";
import { NAV, NAV_GROUPS } from "@/lib/nav";
import { Card, StatTile, Badge } from "@/components/ui";
import { cn, collectionLabel, fmt, prettyDate } from "@/lib/utils";

export function Overview() {
  const { meta, collection, collections, setCollection } = useStore();

  return (
    <div>
      {/* hero */}
      <div className="card relative mb-8 overflow-hidden px-6 py-10 sm:px-10 sm:py-12">
        <div className="pointer-events-none absolute -right-24 -top-24 h-72 w-72 rounded-full bg-accent/15 blur-3xl" />
        <div className="pointer-events-none absolute -bottom-28 left-1/3 h-64 w-64 rounded-full bg-gold/10 blur-3xl" />
        <div className="relative max-w-2xl">
          <Badge tone="accent" className="mb-4">
            <CircleDot className="h-3 w-3" /> open cricket intelligence
          </Badge>
          <h1 className="text-3xl font-extrabold leading-tight tracking-tight text-fg sm:text-[42px]">
            The numbers behind the game, <span className="grad-text">honestly modelled.</span>
          </h1>
          <p className="mt-4 text-base leading-relaxed text-muted">
            CricDex turns Cricsheet ball-by-ball data into win-probability impact, ten more context metrics,
            Bayesian skill ratings, cross-league scouting and a real-rules IPL auction — computed offline and
            served as a static site. Every model is explained.
          </p>
          <div className="mt-7 flex flex-wrap gap-3">
            <Link to="/leaderboards" className="btn btn-accent">
              Explore leaderboards <ArrowRight className="h-4 w-4" />
            </Link>
            <Link to="/scout" className="btn">
              Scout a player
            </Link>
            <Link to="/about" className="btn">
              How it works
            </Link>
          </div>
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
