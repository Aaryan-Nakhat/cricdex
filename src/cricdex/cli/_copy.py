"""Single source of truth for CLI explainer prose.

Every string here mirrors what the corresponding Streamlit page tells
the user, so the terminal surface stays at parity with the browser
surface. Edit here when the Streamlit copy changes.
"""

from __future__ import annotations

# --- Profile page --------------------------------------------------------

PROFILE_INTRO = (
    "Everything CricDex knows about one player — cross-source IDs, "
    "career totals, novel metrics, Bayesian scout-rating skills, top "
    "style twins, and the graph cohort. All derived live from Cricsheet "
    "ball-by-ball + the People Register."
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

GRAPH_COHORT_INTRO = (
    "Players in the same competitive neighbourhood — derived from the "
    "scout graph's FACED and TEAMMATE_OF edges. Complements the cosine "
    "style-twins above with a relational signal."
)

# Per-metric one-liner — mirrors Streamlit's METRIC_HINTS dict.
METRIC_HINTS: dict[str, str] = {
    "pressure_runs": (
        "Strike rate on balls where the required run rate is ≥ 1.5× the "
        "venue median (chase only). Higher = better under pressure."
    ),
    "recoverability": (
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
    "sticky_dot_pressure": (
        "Wicket rate on the next ball after a 4+ consecutive dot streak "
        "in the same over (bowler metric). Higher = turns pressure into "
        "dismissals."
    ),
    "intent_curve": (
        "How a batter's strike rate evolves across innings phases "
        "(0-5 / 6-10 / 11-20 / 21-30 / 31-50 / 51+ balls). Rising = "
        "grower; flat-high = aggressor; flat-mid = grinder."
    ),
    "ngi": (
        "Net Game Impact — WPA-style win-probability delta credited "
        "per ball. Per-match average. Calibrated XGBoost WP model."
    ),
    "wicket_quality": (
        "Σ(opponent Bayes skill) ÷ wickets taken. Wickets of marquee "
        "batters score higher than wickets of tail-enders."
    ),
    "phase_dilation": (
        "Strike-rate inflation vs the batter's own baseline when the "
        "phase demands it (batting-first counterpart of Pressure Runs)."
    ),
    "setting_tax": (
        "Cost (in runs / ball) of setting a chaseable total — captures "
        "balls spent below par when the team is batting first."
    ),
}

# --- Leaderboards page ---------------------------------------------------

LEADERBOARD_INTRO = (
    "Context-adjusted player rankings. Computed from Cricsheet "
    "ball-by-ball; no scraping, no proprietary feeds. Re-emit with "
    "`cricdex data ingest metrics -c <collection>`."
)

# --- Rules Q&A -----------------------------------------------------------

RULES_INTRO = (
    "Natural-language Q&A over 21 verified rulebook PDFs (MCC Laws, "
    "ICC PCs, IPL, Hundred, BBL/WBBL, SA20, Cricket Australia "
    "domestic, ICC Codes, Anti-Corruption). 11k+ clauses indexed."
)

# --- Records -------------------------------------------------------------

RECORDS_INTRO = (
    "9 record SQL queries + On-This-Day digest. Today's default "
    "lists every notable event for the calendar date across the "
    "selected collection."
)

# --- Match Reports -------------------------------------------------------

MATCH_REPORT_INTRO = (
    "LLM-written match report grounded in Cricsheet facts. No "
    "hallucinations — every named stat traces back to the ball-by-ball."
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
    "P(A better) = probability A's true opponent-adjusted skill exceeds "
    "B's, from the difference of their Bayesian posteriors. Near-50% = "
    "statistically indistinguishable. Skill = scoring / run-suppression "
    "rate, not dismissal-adjusted value (vNext)."
)

# --- Venues --------------------------------------------------------------

VENUES_INTRO = (
    "Per-venue conditions: innings totals + phase run rates + "
    "chase-vs-set win rate + dismissal mix. Pulled live from "
    "Cricsheet for the selected collection."
)

# --- Auction -------------------------------------------------------------

AUCTION_SOLVE_INTRO = (
    "MILP squad optimiser via `scipy.optimize.milp` over a player "
    "pool. Maximises total projected value subject to budget + "
    "squad-size + role + overseas constraints."
)

AUCTION_RECOMMEND_INTRO = (
    "War-room substitute advisor — graph similarity × Bayes value × "
    "remaining purse × role match. Composite-scored shortlist."
)

AUCTION_SIMULATE_INTRO = (
    "Monte-Carlo auction price-band simulator. N franchises bid on "
    "a pool; emits per-player sale-price distributions."
)

# --- Translate -----------------------------------------------------------

TRANSLATE_INTRO = (
    "English commentary → Hindi / Tamil / Bengali / Urdu / Sinhala / "
    "Marathi / Telugu / Kannada. Text-only in v1; voice-cloned audio "
    "deferred to year 2."
)

# --- Scout ---------------------------------------------------------------

TWINS_INTRO = (
    "Graph cohort via Neo4j FACED + TEAMMATE_OF edges. `co_faced` = "
    "bowlers who've bowled to the same set of batters as the target; "
    "`teammates` = players who've shared a dressing room overlap."
)

FIND_REPLACEMENT_INTRO = (
    "Auto-flip role-aware twin search. Detects whether the target is "
    "primarily a bowler or batter via balls_bowled-vs-balls_faced "
    "ratio, then surfaces same-archetype candidates only."
)
