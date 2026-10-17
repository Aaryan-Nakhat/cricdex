import { BookOpen, Brain, Sigma, Network, Gavel, Database, Target, Activity } from "lucide-react";
import { PageTitle, Card } from "@/components/ui";

interface Section {
  icon: React.ReactNode;
  title: string;
  body: React.ReactNode;
}

const SECTIONS: Section[] = [
  {
    icon: <Database className="h-5 w-5" />,
    title: "Where the numbers come from",
    body: (
      <>
        Everything here is built from <strong>Cricsheet</strong> ball-by-ball data — every delivery of
        every match in a collection. There is no scraping and no live feed, and every number is computed,
        not generated — the one AI step only tags each player's role, bowling type and country (marked
        “AI-classified” in the filters). A Python pipeline computes the ratings and metrics offline; this
        site just displays the result. The “data up to” date in the header is the most recent match
        actually in the dataset, refreshed on demand. Grounds that were renamed or spelled differently
        over the years (Feroz Shah Kotla → Arun Jaitley Stadium, Sardar Patel → Narendra Modi Stadium)
        are merged into one venue under its current name; the old names still work in search.
      </>
    ),
  },
  {
    icon: <Activity className="h-5 w-5" />,
    title: "Net Game Impact (NGI)",
    body: (
      <>
        The flagship number: how much a player moves their team's <strong>chance of winning</strong>.
        A win-probability model (gradient-boosted trees, calibrated) reads the match state before every
        ball — score, wickets and balls left, target and required rate, run rate against the ground's
        average — and the change in win chance after the ball is that ball's value: plus to the batter,
        minus to the bowler. Summed per match, a 30* that wins a tight chase counts for more than a
        hundred in a lost cause. The model is trained on one set of matches and checked on others it
        never saw, and the all-time board needs at least 25 matches. Fielders aren't credited yet.
      </>
    ),
  },
  {
    icon: <Brain className="h-5 w-5" />,
    title: "Bayesian skill ratings",
    body: (
      <>
        Raw averages punish a batter who faced great bowlers and flatter one who feasted on weak attacks.
        The Bayesian model fixes this by learning a <strong>latent skill</strong> for every player at once,
        so each number is judged in the context of who it came against. The model is{" "}
        <strong>dismissal-aware</strong>: it fits four axes per player — for batters, a{" "}
        <em>scoring</em> rate and a <em>survival</em> (don’t-get-out) rate; for bowlers, an{" "}
        <em>economy</em> and a <em>strike</em> (take-wickets) rate. Crucially it reports not just a point
        estimate but the <strong>uncertainty</strong> around it — which is what powers the head-to-head
        probabilities.
      </>
    ),
  },
  {
    icon: <Sigma className="h-5 w-5" />,
    title: "Nine more metrics + fielding",
    body: (
      <>
        Each metric isolates one skill that a scorecard hides — strike rate <em>specifically</em> when the
        required rate is climbing (Pressure Runs), how a batter responds to a dot (Dot-Ball Recovery),
        whether a bowler converts built-up pressure into a wicket (Pressure Conversion), wickets weighted
        by the calibre of the batter dismissed (Wicket Quality), and more. They’re all on the Leaderboards
        page, each with a plain-English explainer.
      </>
    ),
  },
  {
    icon: <Network className="h-5 w-5" />,
    title: "Scout — cross-tier look-alikes",
    body: (
      <>
        Pick an active IPL player and find others of the <em>same mould</em> across every Scout pool:{" "}
        <strong>IPL peers</strong>, uncapped Indian prospects from the <strong>SMAT</strong>, and
        overseas options from each overseas league in the league list (the Big Bash, SA20, CPL, T20
        Blast, PSL, ILT20, The Hundred, MLC and more). Matches share the same role (and seam/spin type
        for bowlers) and are ranked by how close their <em>skill standing</em> is — each player's
        Bayesian value as a z-score within its own competition, so a SMAT star and an IPL star line up
        even though raw numbers aren't comparable across tiers. Each match carries an{" "}
        <em>estimated crore price</em> (the Auction room's skill→price curve, discounted per tier) and
        the <em>saving</em> vs your pick — the budget-swap case — plus a <em>gem</em> flag for uncapped
        prospects punching above their sample. One click <em>drafts</em> a prospect into the Auction
        room. The exact same scout runs on the CLI, TUI and Streamlit too (one shared implementation,
        locked by a parity test). A faced/teammate cohort — built straight from the ball-by-ball —
        also surfaces on each player's profile: who they share the most opponents and sides with.
      </>
    ),
  },
  {
    icon: <Gavel className="h-5 w-5" />,
    title: "Auction simulation",
    body: (
      <>
        A Monte-Carlo of a real IPL auction. The pool spans the active T20 world it draws from — IPL
        players plus free agents from every overseas league in the league list (the Big Bash, SA20,
        CPL, T20 Blast, PSL and more) and the <strong>SMAT</strong> (uncapped Indians) — priced in crore from the skill model and decayed for staleness. Each
        franchise first <strong>retains</strong> its core (Mega = the real 2025 lists, ~5; Mini = keep
        most of the squad — both editable), then the ten teams bid for the rest by their own
        personality (marquee-chaser, value-hunter, overseas-heavy…), hundreds of times, filling 20–25-man
        squads under the purse + overseas cap. A team with more money left per open slot than the rest
        bids harder (so a side that retained little actually spends its purse), and the winner pays just
        above the second-highest bid, never more than <strong>27 cr</strong> — the real record. You see
        who likely lands each remaining star. Runs
        entirely in your browser — and identically on the CLI, TUI and Streamlit from the same inputs
        (one shared implementation with a seeded RNG, locked by a parity test).
      </>
    ),
  },
  {
    icon: <Target className="h-5 w-5" />,
    title: "Do the ratings predict anything? (backtest)",
    body: (
      <>
        We checked, out of sample: for each IPL season the model is fitted on matches{" "}
        <strong>before</strong> it only, then its ranking of players is compared with how the season
        actually went (rank correlation: 1 = same order, 0 = no link). The honest result has two parts.{" "}
        <strong>Established IPL players</strong> (2021–26): the ratings predict next season about as well
        as plain career averages — around 0.15 overall for batters, 0.07 for bowlers — and weighting
        recent seasons more didn't change that. A single T20 season is mostly noise, for any method.{" "}
        <strong>IPL newcomers</strong> (2014–26, rated only from the BBL, SA20, CPL, Blast and SMAT):
        here the opponent- and league-adjusted ratings ranked <em>batters</em> better than their raw
        numbers from those leagues on every measure (overall 0.18 vs 0.12, staying in 0.34 vs 0.22); for{" "}
        <em>bowlers</em> there was no clear edge (overall 0.20 vs 0.25). How sure is that? Re-drawing the
        ~100 newcomers 2,000 times, the model judged how long a newcomer batter lasts better in 97% of
        redraws — the one solid result; its batter overall edge held in 79%, a lean rather than proof.
        Both backtests are scripts in the repo, so you can re-run them.
      </>
    ),
  },
];

export function About() {
  return (
    <>
      <PageTitle
        title="How it works"
        icon={<BookOpen className="h-6 w-6" />}
        desc="The models behind CricDex, explained without the jargon. No black boxes — if a number is on this site, you can find out exactly how it was made."
      />
      <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
        {SECTIONS.map((s) => (
          <Card key={s.title} className="px-5 py-5">
            <div className="flex items-center gap-2.5 text-accent">
              {s.icon}
              <h3 className="text-base font-bold text-fg">{s.title}</h3>
            </div>
            <p className="mt-3 text-sm leading-relaxed text-muted">{s.body}</p>
          </Card>
        ))}
      </div>

      <Card className="mt-5 px-5 py-4 text-sm text-muted">
        CricDex is open source. The full pipeline — ingestion, the NumPyro Bayesian model, the metrics,
        and a typer CLI / Textual TUI / Streamlit dashboard with the same features — lives on{" "}
        <a className="text-accent-glow underline" href="https://github.com/Aaryan-Nakhat/cricdex" target="_blank" rel="noreferrer">
          GitHub
        </a>
        .
      </Card>
    </>
  );
}
