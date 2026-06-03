import { BookOpen, Brain, Sigma, Network, Gavel, Database } from "lucide-react";
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
        every match in a collection. There is no scraping, no live feed, and no LLM guessing. A Python
        pipeline computes the ratings and metrics offline; this site just displays the result. The “data
        up to” date in the header is the most recent match actually in the dataset, and a nightly GitHub
        Action re-cooks it.
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
    title: "Ten novel metrics",
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
        Pick an active IPL player and find others of the <em>same mould</em> at three levels:{" "}
        <strong>IPL peers</strong>, uncapped Indian prospects from the <strong>SMAT</strong>, and
        overseas options from the <strong>BBL</strong>. Matches share the same role (and seam/spin type
        for bowlers) and are ranked by how close their <em>skill standing</em> is — each player's
        Bayesian value as a z-score within its own competition, so a SMAT star and an IPL star line up
        even though raw numbers aren't comparable across tiers. (A Neo4j faced/teammate graph still
        powers the desktop CLI &amp; Streamlit twins.)
      </>
    ),
  },
  {
    icon: <Gavel className="h-5 w-5" />,
    title: "Auction simulation",
    body: (
      <>
        A Monte-Carlo of a real IPL auction. The pool spans the active T20 world it draws from — IPL
        players plus free agents from the <strong>BBL</strong> (overseas) and <strong>SMAT</strong>
        (uncapped Indians) — priced in crore from the skill model and decayed for staleness. Each
        franchise first <strong>retains</strong> its core (Mega = the real 2025 lists, ~5; Mini = keep
        most of the squad — both editable), then the ten teams bid for the rest by their own
        personality (marquee-chaser, value-hunter, overseas-heavy…), hundreds of times, filling 20–25-man
        squads under the purse + overseas cap. You see who likely lands each remaining star. Runs
        entirely in your browser. (The desktop CLI keeps an exact MILP optimiser.)
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
        CricDex is open source. The full pipeline — ingestion, the NumPyro Bayesian model, the metrics, the
        Neo4j graph, and a typer CLI / Textual TUI / Streamlit dashboard with the same features — lives on{" "}
        <a className="text-accent-glow underline" href="https://github.com/Aaryan-Nakhat/cricdex" target="_blank" rel="noreferrer">
          GitHub
        </a>
        .
      </Card>
    </>
  );
}
