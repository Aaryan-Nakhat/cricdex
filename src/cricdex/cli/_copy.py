"""Single source of truth for CLI explainer prose.

Every string here mirrors what the corresponding Streamlit page tells
the user, so the terminal surface stays at parity with the browser
surface. Edit here when the Streamlit copy changes.
"""

from __future__ import annotations

# --- Profile page --------------------------------------------------------

PROFILE_INTRO = (
    "Everything CricDex knows about one player — cross-source IDs, "
    "career totals, novel metrics, Bayesian scout-rating skills, and top "
    "style twins. All derived from Cricsheet ball-by-ball + the People "
    "Register."
)

WIKIDATA_FOOTER = (
    "Wikidata-sourced (image + DOB + cross-source IDs). Country / "
    "birthplace are raw Q-ids in v1 — label resolution in vNext. "
    "Refresh with `cricdex data ingest wikidata --force`."
)

WIKIDATA_NOT_FOUND = "Wikidata: no entity found for this player."

WIKIDATA_NOT_PULLED = (
    "Wikidata enrichment not yet pulled for this player — run "
    "`cricdex data ingest wikidata` to populate."
)

BAYES_SCALE = (
    "Skill is on the natural-log scale of the NumPyro / JAX "
    "hierarchical Negative-Binomial fit. 0 = an average player in this league "
    "(not a replacement player). +0.30 ≈ marquee; -0.30 ≈ well below average."
)

# Per-metric one-liner — mirrors Streamlit's METRIC_HINTS dict.
METRIC_HINTS: dict[str, str] = {
    "pressure_runs": (
        "Strike rate on balls where the required run rate is ≥ 1.5× the "
        "venue median (chase only). Higher = better under pressure."
    ),
    "dot_ball_recovery": (
        "How efficiently this batter recovers after a slow patch. "
        "Higher = doesn't let one dot ball spiral."
    ),
    "counter_attack": (
        "Strike rate inflation right after a wicket falls. Higher = "
        "aggressive after partnership-breaking dismissals."
    ),
    "boundary_dependency": (
        "Share of runs from 4s + 6s. High = boundary-reliant; low = strike-rotator. "
        "A style, not a level — neither is better."
    ),
    "pressure_conversion": (
        "Wicket rate on the next ball after a 4+ consecutive dot streak "
        "in the same over (bowler metric). Higher = turns pressure into "
        "dismissals."
    ),
    "intent_curve": (
        "Early SR (balls 1-10) — who comes out firing — with the full "
        "innings strike-rate curve (0-5 … 51+) as the sparkline column."
    ),
    "ngi": (
        "Net Game Impact — how much a player adds to his team's chance of winning. "
        "Win chance added / match is the per-game average (+5% = five percentage points); "
        "wins added is the career total, which grows with matches played."
    ),
    "wicket_quality": (
        "Σ(opponent Bayes skill) ÷ wickets taken. Wickets of marquee "
        "batters score higher than wickets of tail-enders."
    ),
    "crease_longevity": (
        "Crease longevity vs the cohort — average balls faced per "
        "dismissal ÷ the cohort average. >1 = bats longer than the "
        "typical batter (anchor); <1 = shorter, higher-tempo cameos."
    ),
    "slow_start_cost": (
        "Career strike rate minus strike rate over the first 20 balls "
        "of an innings. Positive = slow starter whose early caution "
        "costs tempo; ~0 = aggressive from ball one."
    ),
    "keeping": "Wicketkeeping dismissals: catches + stumpings + run-outs.",
    "fielding": "Outfield dismissals: catches + run-outs.",
}

# --- Leaderboards page ---------------------------------------------------

LEADERBOARD_INTRO = (
    "Context-adjusted player rankings. Computed from Cricsheet "
    "ball-by-ball; no scraping, no proprietary feeds. Re-emit with "
    "`cricdex data ingest metrics -c <collection>`."
)

# --- Records -------------------------------------------------------------

RECORDS_INTRO = (
    "9 record SQL queries + On-This-Day digest. Today's default "
    "lists every notable event for the calendar date across the "
    "selected collection."
)

# --- Compare -------------------------------------------------------------

COMPARE_INTRO = (
    "Side-by-side metric table across multiple players. Empty cells "
    "show as '—' with the threshold note. Radar in the dashboard "
    "(`cricdex dashboard`) for a visual."
)

COMPARE_THRESHOLD_NOTE = (
    "Empty cells mean the player didn't clear that metric's "
    "min-balls / min-innings threshold for the collection."
)

HEAD_TO_HEAD_NOTE = (
    "P(A better) = probability A's true value exceeds B's, from the "
    "difference of their Bayesian posteriors. Near-50% = statistically "
    "indistinguishable. Value is in runs per 100 balls above the league's "
    "average ball: batting = opponent-adjusted extra scoring + the runs "
    "saved by not getting out, a wicket priced at what it costs where he "
    "bats (dear in the powerplay, cheap at the death); bowling = runs saved "
    "+ extra wickets at the same price."
)

# --- Venues --------------------------------------------------------------

VENUES_INTRO = (
    "Per-venue conditions: innings totals + phase run rates + "
    "chase-vs-set win rate + dismissal mix. Pulled live from "
    "Cricsheet for the selected collection."
)

# --- Auction -------------------------------------------------------------

AUCTION_SIMULATE_INTRO = (
    "Real-rules IPL auction Monte-Carlo — each franchise retains its core, "
    "then the ten teams bid for the rest by a demand model fitted on real auctions "
    "(their squads, overseas places and purses at each lot) over ~300 trials. "
    "Same engine as the web (cricdex.web_parity), seeded + reproducible."
)

KEEP_INTRO = (
    "Keep or release — for each player in the squad: his market price (a model fitted to every "
    "IPL auction since 2018, each mega-auction retention counted as a floor: value on a cautious "
    "estimate, caps, age, IPL experience, captaincy; the % is the chance he's bought if released) "
    "against what keeping him costs (his salary; for a 2025 retention the retention slabs, assumed "
    "to carry into 2027), with his on-field worth (the skill-only curve) alongside. The call is what "
    "franchises actually do: the chance a franchise keeps a player like him, from a model fitted to "
    "every real retention deadline 2018-2026 (market price vs cost, the 3-season Form forecast, "
    "captain / seasons there / home-grown, capped Indian, overseas, age, IPL balls). Keep at 65%+, "
    "release under 35%, borderline in between (kept by default from 50%). Then the purse left "
    "after what the kept players cost, the role gaps and the cheapest free agents who fill them."
)

# --- Scout ---------------------------------------------------------------

TWINS_INTRO = (
    "Cross-competition look-alikes — pick an active IPL player, see similar "
    "players across IPL, SMAT and every overseas league by within-tier "
    "skill standing, with est. price, saving-vs-pick and a gem flag."
)
