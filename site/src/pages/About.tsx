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
        A win-probability model (gradient-boosted trees with common-sense constraints — a wicket can never
        help the batting side — and a smooth calibration) reads the match state before every ball: score,
        wickets and balls left, target and required rate, run rate against the ground's average and
        against the league's recent scoring level. Every ball is scored by a model that{" "}
        <strong>never saw that match</strong>. The change in win chance is credited to whoever caused it:
        runs off the bat to the striker (and against the bowler), wides and no-balls to the bowler alone,
        a wicket against the batter who is out (the non-striker in a run out at his end) and to the bowler,
        with 20% of a catch or stumping to the fielder and a run out to the fielders who made it. Summed per
        match, a 30* that wins a tight chase counts for more than a hundred in a lost cause. It is shown
        two ways: <strong>win chance added per match</strong> (+5% means he adds five percentage points to
        his side's chance of winning in a typical game; 0% is break-even), counted over his matches in
        the playing XI, and <strong>wins added</strong>, the career total — every 1.0 is one whole win's
        worth, and like career runs it grows with every match played. The all-time board needs at least
        25 matches.
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
        so each number is judged in the context of who it came against — and <strong>when and where</strong>:
        it learns each season's scoring level, the powerplay / middle / death split, setting vs chasing
        and the ground, so a 2026 strike rate is judged against 2026 and a death bowler against the death
        overs. A bowler's economy counts his wides and no-balls, and a player with few balls is pulled
        toward the average for his role (a tail-ender toward tail-enders), not toward the average player.
        The model is{" "}
        <strong>dismissal-aware</strong>: it fits four axes per player — for batters, a{" "}
        <em>scoring</em> rate and a <em>survival</em> (don’t-get-out) rate; for bowlers, an{" "}
        <em>economy</em> and a <em>strike</em> (take-wickets) rate. The two combine into one{" "}
        <strong>value in runs per 100 balls</strong>, a wicket priced at what it costs where the player
        bats or bowls (about 14 runs early in the powerplay, 2–3 at the death), so a finisher is judged
        mainly on how fast he scores. Prices use a cautious estimate (value minus half its
        uncertainty), and the price ceiling rises with IPL experience (13.5 cr with none, 27 cr from
        about two seasons), so a short, hot record is priced below a proven one. Crucially it reports not just a point
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
        actually went (rank correlation: 1 = same order, 0 = no link). The plain baselines get the same
        league adjustment as the model, and every fit is run with three seeds.{" "}
        <strong>Established IPL players</strong> (2021–26): the overall value, in runs, beats plain
        career averages for batters (0.19 vs 0.15) and bowlers (0.15 vs 0.11). Weighting recent
        seasons more didn't help. A single T20 season is mostly noise, for any method, but on a sharper
        test, predicting every ball of the next season, the current model beats the old one in every
        season.{" "}
        <strong>IPL newcomers</strong> (2014–26, rated only from other leagues): here the ratings are no
        better than the players' own league-adjusted numbers from those leagues (batters 0.08 vs 0.10,
        bowlers 0.22 vs 0.26, with all 13 other leagues). The only lean is for batters with the original
        five leagues (0.11 vs 0.06), and re-drawing the ~100 newcomers 2,000 times it held in just 78% of
        redraws; after correcting for running six tests at once none of the results is significant.
        Earlier versions of this page claimed an edge for newcomer batters; one came from an unfair
        baseline, the other from the old way of adding up the value, and neither survives. Both
        backtests are scripts in the repo, so you can re-run them.
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
