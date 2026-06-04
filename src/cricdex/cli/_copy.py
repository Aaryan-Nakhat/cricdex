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
    "hierarchical Negative-Binomial fit. 0 = league average. +0.30 ≈ "
    "marquee; -0.30 ≈ replacement-level."
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
        "Share of runs from 4s + 6s. Higher = boundary-reliant; lower = strong strike-rotator."
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
        "Net Game Impact — WPA-style win-probability delta credited "
        "per ball. Per-match average. Calibrated XGBoost WP model."
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
    "indistinguishable. Batting value = opponent-adjusted scoring rate "
    "+ dismissal resistance; bowling value = economy + strike rate. A "
    "fast slogger who gets out often no longer outranks an anchor."
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
    "then the ten teams bid for the rest by personality over ~300 trials. "
    "Same engine as the web (cricdex.web_parity), seeded + reproducible."
)

# --- Scout ---------------------------------------------------------------

TWINS_INTRO = (
    "Cross-competition look-alikes — pick an active IPL player, see similar "
    "players across IPL / SMAT / BBL / SA20 / CPL / Blast by within-tier "
    "skill standing, with est. price, saving-vs-pick and a gem flag."
)
