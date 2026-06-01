import { Link } from "react-router-dom";
import { ArrowRight, Database, CalendarClock } from "lucide-react";
import { useStore } from "@/lib/store";
import { NAV } from "@/lib/nav";
import { Card, StatTile, Badge } from "@/components/ui";
import { collectionLabel, fmt, prettyDate } from "@/lib/utils";

export function Overview() {
  const { meta, collection } = useStore();

  return (
    <div className="animate-fade-up">
      {/* hero */}
      <div className="relative mb-8 overflow-hidden rounded-2xl border border-border bg-gradient-to-br from-card to-surface px-6 py-10 sm:px-10">
        <div className="pointer-events-none absolute -right-20 -top-20 h-64 w-64 rounded-full bg-accent/10 blur-3xl" />
        <div className="relative max-w-2xl">
          <Badge tone="accent" className="mb-4">
            open cricket intelligence
          </Badge>
          <h1 className="text-3xl font-extrabold tracking-tight text-fg sm:text-4xl">
            The numbers behind the game,{" "}
            <span className="text-accent">honestly modelled.</span>
          </h1>
          <p className="mt-4 text-base leading-relaxed text-muted">
            CricDex turns raw Cricsheet ball-by-ball data into Bayesian skill ratings, ten
            novel impact metrics, a scout graph, and an auction optimiser — all computed
            offline and served as a static site. No black boxes: every model is explained.
          </p>
          <div className="mt-6 flex flex-wrap gap-3">
            <Link to="/leaderboards" className="btn btn-accent">
              Explore leaderboards <ArrowRight className="h-4 w-4" />
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
          Current collection: <span className="font-semibold text-fg">{collectionLabel(collection)}</span>
        </span>
      </div>
      <div className="mb-10 grid grid-cols-2 gap-3 sm:grid-cols-4">
        <StatTile label="Matches" value={fmt(meta?.n_matches ?? 0, 0)} />
        <StatTile label="Balls bowled" value={fmt(meta?.n_balls ?? 0, 0)} />
        <StatTile label="Players rated" value={fmt(meta?.n_players ?? 0, 0)} />
        <StatTile label="Data up to" value={prettyDate(meta?.data_as_of)} hint="max match date" />
      </div>

      {/* feature grid */}
      <h2 className="mb-4 text-lg font-bold text-fg">Everything in here</h2>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {NAV.filter((n) => n.to !== "/").map((item) => (
          <Link key={item.to} to={item.to}>
            <Card className="group h-full px-5 py-4 transition-all hover:border-accent/40 hover:shadow-glow">
              <div className="flex items-center gap-2.5">
                <span className="flex h-9 w-9 items-center justify-center rounded-lg border border-border bg-surface text-accent transition-colors group-hover:border-accent/40">
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

      {/* freshness footnote */}
      <div className="mt-10 flex items-center gap-2 text-xs text-muted">
        <CalendarClock className="h-3.5 w-3.5" />
        Data is pre-computed offline and refreshed on demand via a GitHub Action. The figures you
        see are accurate up to {prettyDate(meta?.data_as_of)} — the date of the most recent match in
        this collection.
      </div>
    </div>
  );
}
