import { BookOpen, Brain, Sigma, Network, Gavel, Database, Target, Activity, Scale, TrendingUp, ClipboardList } from "lucide-react";
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
        mainly on how fast he scores. Prices are <strong>fitted to real IPL auction prices</strong>{" "}
        (2018–2026 sales and mega retentions, from Wikipedia): from a cautious estimate of the value
        (value minus half its uncertainty), international caps, age, IPL experience and captaincy,
        priced at the median for his kind of player (overseas in a mega or a mini auction, capped or
        uncapped Indian). At the top the price follows what the market really paid for its dearest lots (a
        monotone calibration fitted out of fold), so no ceiling is needed. Out of time half the lots land
        within ±50% of their price and the 20 dearest predictions of each auction fetch about 0.87× them
        on average. The
        skill-only curve is kept alongside as each player's <em>on-field worth</em>. Crucially it reports not just a point
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
        <em>estimated crore price</em> (the Auction room's market price, his value discounted per tier) and
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
        CPL, T20 Blast, PSL and more) and the <strong>SMAT</strong> (uncapped Indians) — priced in crore at the market price fitted to real auctions (at most 36% of the lots overseas, as on a real shortlist). Each
        franchise first <strong>retains</strong> its core (Mega = the real 2025 lists, ~5; Mini = keep
        most of the squad — both editable), then the ten teams bid for the rest by their own
        personality (marquee-chaser, value-hunter, overseas-heavy…), hundreds of times, filling 20–25-man
        squads under the purse + overseas cap. A team with more money left per open slot than the rest
        bids harder (so a side that retained little actually spends its purse), and the winner pays just
        above the second-highest bid, never more than its purse allows (the purse less the base price of every
        place it still has to fill). The bidding is
        calibrated to real auctions (2022–24, tested on 2025–26): a fitted level per auction type, money spread
        beyond the stars, a player's last price remembered, a demand shock per lot, and more money chasing fewer
        places lifting every bid. You see
        who likely lands each remaining star. Runs
        entirely in your browser — and identically on the CLI, TUI and Streamlit from the same inputs
        (one shared implementation with a seeded RNG, locked by a parity test).
      </>
    ),
  },
  {
    icon: <Scale className="h-5 w-5" />,
    title: "Keep or release (retentions)",
    body: (
      <>
        Before the retention deadline (IPL 2027: 15 November 2026, as reported) a franchise decides whom to keep.
        For every player in its squad we set what keeping him <strong>costs</strong> (his salary; for a player
        retained at the 2025 mega auction, the 2025 retention slabs, assumed to carry into 2027) against his{" "}
        <strong>market price</strong> (what players like him have fetched at real IPL auctions, each retention
        counted as a floor on a star's worth, with the chance he's bought if released; his on-field worth is
        shown alongside; last season's captains carry a badge and the premium the market pays them). The call
        is <strong>what franchises actually do</strong>: the chance a franchise keeps a player like him, from a
        model fitted to every real retention deadline 2018–2026 (his market price against his cost, his
        three-season Form forecast, his ties to the side: captain, seasons there, home-grown; capped Indian or
        overseas, age, IPL balls). Chosen on the deadlines up to 2024 and tested once on 2025–26, it made the
        franchise's own call for 78% of players (82% of stars). Keep at 65%+, release under 35%, borderline in
        between. Then the squad that follows: purse left after what the kept players cost, open slots, and the role gaps
        (keepers, openers, death bowlers, spinners, overseas) filled from the likely auction pool, free agents
        plus the players our calls release elsewhere. Squads and salaries come from Wikipedia's personnel pages
        (CC BY-SA); the rules are data in <code>config/competitions.toml</code>, each one sourced or marked as an
        assumption (no 2027 purse has been published, so 125 cr is assumed). Every call can be flipped on the
        page, and the same calculator runs on the CLI (<code>cricdex keep</code>), locked by a parity test.
      </>
    ),
  },
  {
    icon: <TrendingUp className="h-5 w-5" />,
    title: "Form forecast (the next three seasons)",
    body: (
      <>
        Every active IPL player's profile projects his value (runs per 100 balls above average, the rating's
        own unit) over the next three seasons, <strong>starting from his current level</strong>: a model of his
        true level drifting from season to season with age, updated by each season he plays (a 450-ball season
        counts far more than a cameo, recent seasons more than old ones). Then a median, an 80% range and the{" "}
        <strong>chance he is still a regular</strong> (120+ balls that season). Batters start from that level
        (blended with a quarter of the career rating); for bowlers the career rating turned out to be the better
        guide to where they are now, so they start from it. The age curve is corrected for{" "}
        <strong>survivorship</strong> (the players who decline are the ones who get dropped, so a curve built only
        on those who kept playing is too kind to age): each season that was seen counts for the ones like it that
        weren't. For bowlers the data can't fully correct it (the ones still picked at 36 are the ones selectors
        trust), so their curve is held flat past 32. Backtested with data through 2021, 2022 and 2023 against
        2022–2026: for batters the lowest error of every baseline at every horizon; for bowlers a tie with the
        rating; the chance of being a regular beats every baseline; about three in four seasons landed inside
        the 80% one-season range. Methodology §11 checks 15 stars against their last three seasons and explains
        each disagreement (Kohli, at 38 after three big seasons, comes out at +5: players like him have
        averaged +6 the season after). Keep or release shows it as a "3-season outlook" column.
        The medians are <em>if he plays</em>; read them with the chance he does. Also on the CLI:{" "}
        <code>cricdex forecast "Kohli"</code>, <code>cricdex forecast --team RCB</code>.
      </>
    ),
  },
  {
    icon: <ClipboardList className="h-5 w-5" />,
    title: "Bid plan (the auction sheet)",
    body: (
      <>
        For the auction itself: whom your franchise should bid for, and how high. Your squad and purse come from Keep or
        release (your own calls carry over); every team opens at least 8 places (the median a team bought at recent mini
        auctions). The other nine teams then bid in the Auction room's simulator 200 times, which gives each player's{" "}
        <strong>price to beat</strong>. A squad's <strong>strength</strong> is its best XI's values added up (at most 4
        overseas, a keeper, five bowling and six batting options) plus a little for depth and minus a penalty for each
        role need missed. In every run you bid for a player up to his gain in strength ÷ λ, an exchange rate in runs per
        crore chosen to give the best average squad. Each target gets a <strong>max bid</strong> (where his value per crore
        drops below the next-best use of the purse), the odds of landing him under it, and a{" "}
        <strong>fallback chain</strong> per role. The rivals' bidding is calibrated to real auctions (fitted on 2022–24,
        tested on 2025–26: real prices now fall inside the simulated range about as often as they should), and a team
        never buys back its own releases: a release worth more to the squad than his salary is flagged "reconsider
        keeping". Replayed on the 2025 and 2026 auctions with only what was known beforehand, the plan's squads were
        level with the real ones in 2025 and worse in 2026: a starting sheet, not a forecast. Same optimiser on the CLI
        (<code>cricdex bidplan</code>), locked by a parity test.
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
