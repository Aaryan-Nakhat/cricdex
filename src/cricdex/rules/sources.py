"""Human-readable labels + publisher URLs for every rulebook `source_id`.

The retrieval index stores cryptic short ids like
`cricket_aus_oneday_cup_2025_26`; this module maps them to a name a
non-developer can read ("Marsh One-Day Cup 2025-26 Playing
Conditions") plus a publisher URL so the citation can be clicked.

Used by the Streamlit Rules Chat page + any future CLI / API rendering
layer. The set of source_ids matches the `parsed/*.jsonl` shipped by
`cricdex data ingest rules`.
"""

from __future__ import annotations

SOURCES: dict[str, dict[str, str]] = {
    "mcc_laws_2017_4th_2026": {
        "label": "MCC Laws of Cricket (2017 Code, 4th edition, 2026 update)",
        "url": "https://www.lords.org/mcc/the-laws-of-cricket",
    },
    "icc_pc_men_test_2025": {
        "label": "ICC Men's Test Match Playing Conditions 2025",
        "url": "https://www.icc-cricket.com/about/the-icc/rules-and-regulations",
    },
    "icc_wtc_2025_2027": {
        "label": "ICC World Test Championship 2025–27 Playing Conditions",
        "url": "https://www.icc-cricket.com/about/the-icc/rules-and-regulations",
    },
    "icc_pc_men_odi_2025": {
        "label": "ICC Men's ODI Playing Conditions 2025",
        "url": "https://www.icc-cricket.com/about/the-icc/rules-and-regulations",
    },
    "icc_pc_men_t20i_2025": {
        "label": "ICC Men's T20I Playing Conditions 2025",
        "url": "https://www.icc-cricket.com/about/the-icc/rules-and-regulations",
    },
    "icc_pc_women_test_2025": {
        "label": "ICC Women's Test Playing Conditions 2025",
        "url": "https://www.icc-cricket.com/about/the-icc/rules-and-regulations",
    },
    "icc_pc_women_odi_2025": {
        "label": "ICC Women's ODI Playing Conditions 2025",
        "url": "https://www.icc-cricket.com/about/the-icc/rules-and-regulations",
    },
    "icc_pc_women_t20i_2025": {
        "label": "ICC Women's T20I Playing Conditions 2025",
        "url": "https://www.icc-cricket.com/about/the-icc/rules-and-regulations",
    },
    "icc_u19_men_world_cup_2024": {
        "label": "ICC U19 Men's World Cup Playing Conditions 2024",
        "url": "https://www.icc-cricket.com/about/the-icc/rules-and-regulations",
    },
    "icc_u19_women_t20wc_2025": {
        "label": "ICC U19 Women's T20 World Cup Playing Conditions 2025",
        "url": "https://www.icc-cricket.com/about/the-icc/rules-and-regulations",
    },
    "icc_men_t20wc_2026": {
        "label": "ICC Men's T20 World Cup 2026 Playing Conditions",
        "url": "https://www.icc-cricket.com/about/the-icc/rules-and-regulations",
    },
    "ipl_pc_2026": {
        "label": "IPL 2026 Playing Conditions",
        "url": "https://www.iplt20.com/about/playing-conditions",
    },
    "ipl_impact_player_2025_27": {
        "label": "IPL Impact Player Rule (curated, 2025–27 window)",
        "url": "https://www.iplt20.com/news",
    },
    "ipl_code_of_conduct_2025": {
        "label": "IPL Code of Conduct 2025",
        "url": "https://www.iplt20.com/about/code-of-conduct",
    },
    "hundred_pc_2025": {
        "label": "The Hundred 2025 Playing Conditions",
        "url": "https://www.thehundred.com/competition-rules",
    },
    "bbl_pc_2024_25": {
        "label": "Big Bash League 2024-25 Playing Conditions",
        "url": "https://www.cricket.com.au/bbl",
    },
    "wbbl_pc_2025_26": {
        "label": "Women's Big Bash League 2025-26 Playing Conditions",
        "url": "https://www.cricket.com.au/wbbl",
    },
    "cricket_aus_shield_2025_26": {
        "label": "Sheffield Shield 2025-26 Playing Conditions",
        "url": "https://www.cricket.com.au/shield",
    },
    "cricket_aus_oneday_cup_2025_26": {
        "label": "Marsh One-Day Cup 2025-26 Playing Conditions",
        "url": "https://www.cricket.com.au/oneday-cup",
    },
    "icc_code_of_conduct_players_2023": {
        "label": "ICC Code of Conduct for Players & Player Support Personnel 2023",
        "url": "https://www.icc-cricket.com/about/the-icc/rules-and-regulations",
    },
    "icc_code_of_conduct_match_officials_2016": {
        "label": "ICC Code of Conduct for Match Officials 2016",
        "url": "https://www.icc-cricket.com/about/the-icc/rules-and-regulations",
    },
    "icc_anti_corruption_2024": {
        "label": "ICC Anti-Corruption Code 2024",
        "url": "https://www.icc-cricket.com/about/the-icc/rules-and-regulations",
    },
}


def label_for(source_id: str) -> str:
    """Human-readable title for a `source_id`. Falls back to the raw id
    if we haven't catalogued it yet."""
    meta = SOURCES.get(source_id)
    if not meta:
        return source_id
    return meta["label"]


def url_for(source_id: str) -> str | None:
    meta = SOURCES.get(source_id)
    return meta["url"] if meta else None


def render_citation(source_id: str, clause: str) -> str:
    """Render a single citation as a Markdown link (Streamlit-friendly).

    Example output:
        - **Marsh One-Day Cup 2025-26 Playing Conditions, clause 24.2.1**
          ([source](https://www.cricket.com.au/oneday-cup))
    """
    title = label_for(source_id)
    url = url_for(source_id)
    line = f"**{title}, clause {clause}**"
    if url:
        line += f"  [[source]({url})]"
    return line
