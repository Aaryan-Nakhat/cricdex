"""Manifest of cricket rulebook PDF sources.

URLs in this manifest are scraped from publishers' official Rules &
Regulations / Playing Conditions index pages. Versions update annually;
re-verify before each major re-ingest.

Entries with empty URLs are publisher gaps — no public PDF available at
time of writing (year 1). Track them so we can fill in later.
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel


class RuleSource(BaseModel):
    id: str
    title: str
    organization: str
    tier: str
    url: str
    edition: str
    effective_from: date | None = None
    effective_to: date | None = None
    verified: bool = False
    notes: str = ""


SOURCES: list[RuleSource] = [
    # --- MCC Laws ---
    RuleSource(
        id="mcc_laws_2017_4th_2026",
        title="MCC Laws of Cricket (2017 Code, 4th Edition 2026)",
        organization="MCC",
        tier="laws",
        url="https://www.lords.org/getmedia/1d908298-5c44-468d-b6a7-e1414a1296e0/Laws-of-Cricket-2017-Code-4th-Edition-(2026)_3.pdf",
        edition="2017 Code, 4th Edition 2026",
        effective_from=date(2026, 4, 1),
        verified=True,
        notes="Spirit of Cricket preamble is included as the opening section of this PDF.",
    ),
    # --- ICC Men's Playing Conditions ---
    RuleSource(
        id="icc_pc_men_test_2025",
        title="ICC Men's Test Match Playing Conditions",
        organization="ICC",
        tier="international_men",
        url="https://images.icc-cricket.com/image/upload/prd/lm8owaz03i86m1eneb7m.pdf",
        edition="Effective June 2025",
        effective_from=date(2025, 6, 1),
        verified=True,
    ),
    RuleSource(
        id="icc_pc_men_odi_2025",
        title="ICC Men's Standard ODI Playing Conditions",
        organization="ICC",
        tier="international_men",
        url="https://images.icc-cricket.com/image/upload/prd/d25dbgishkx0kijb4jeu.pdf",
        edition="Effective July 2025",
        effective_from=date(2025, 7, 1),
        verified=True,
    ),
    RuleSource(
        id="icc_pc_men_t20i_2025",
        title="ICC Men's T20I Playing Conditions",
        organization="ICC",
        tier="international_men",
        url="https://images.icc-cricket.com/image/upload/prd/qfnsie8fz6vhyl1pmcli.pdf",
        edition="Effective July 2025",
        effective_from=date(2025, 7, 1),
        verified=True,
    ),
    # --- ICC Women's Playing Conditions ---
    RuleSource(
        id="icc_pc_women_test_2025",
        title="ICC Women's Test Match Playing Conditions",
        organization="ICC",
        tier="international_women",
        url="https://images.icc-cricket.com/image/upload/prd/og30iq9lm5vflinq7pic.pdf",
        edition="Effective December 2025",
        effective_from=date(2025, 12, 1),
        verified=True,
    ),
    RuleSource(
        id="icc_pc_women_odi_2025",
        title="ICC Women's ODI Playing Conditions",
        organization="ICC",
        tier="international_women",
        url="https://images.icc-cricket.com/image/upload/prd/uw0cku3rre2921vposgb.pdf",
        edition="Effective December 2025",
        effective_from=date(2025, 12, 1),
        verified=True,
    ),
    RuleSource(
        id="icc_pc_women_t20i_2025",
        title="ICC Women's T20I Playing Conditions",
        organization="ICC",
        tier="international_women",
        url="https://images.icc-cricket.com/image/upload/prd/vc9oqfirkjvjvvk5nccy.pdf",
        edition="Effective December 2025",
        effective_from=date(2025, 12, 1),
        verified=True,
    ),
    # --- ICC Age-Group ---
    RuleSource(
        id="icc_u19_men_world_cup_2024",
        title="ICC U19 Men's Cricket World Cup 2024 Playing Conditions",
        organization="ICC",
        tier="age_group_men",
        url="https://images.icc-cricket.com/image/upload/prd/fcza6gcre5ylexpq73kx.pdf",
        edition="2024",
        verified=True,
    ),
    RuleSource(
        id="icc_u19_women_t20wc_2025",
        title="ICC U19 Women's T20 World Cup 2025 Playing Conditions",
        organization="ICC",
        tier="age_group_women",
        url="https://images.icc-cricket.com/image/upload/prd/ICC_U19_WOMEN_S_T20WC25_PLAYING_CONDITIONS.pdf",
        edition="2025",
        verified=True,
    ),
    # --- ICC Tournament-specific ---
    RuleSource(
        id="icc_wtc_2025_2027",
        title="ICC World Test Championship 2025-2027 Playing Conditions",
        organization="ICC",
        tier="international_men",
        url="https://images.icc-cricket.com/image/upload/prd/xgmt8r5r41onkqbb5nxv.pdf",
        edition="2025-2027",
        effective_from=date(2025, 6, 1),
        verified=True,
    ),
    RuleSource(
        id="icc_men_t20wc_2026",
        title="ICC Men's T20 World Cup 2026 Playing Conditions",
        organization="ICC",
        tier="international_men",
        url="https://images.icc-cricket.com/image/upload/prd/yyt7m8uh9c1uehrbvuwb.pdf",
        edition="2026",
        verified=True,
    ),
    # --- Leagues (men's) ---
    RuleSource(
        id="ipl_pc_2026",
        title="IPL Playing Conditions",
        organization="BCCI / IPL",
        tier="league_men",
        url="https://documents.iplt20.com/bcci/documents/1775736835406_TATA_IPL_2026_Match_Playing_Conditions.pdf",
        edition="Effective 1 March 2026",
        effective_from=date(2026, 3, 1),
        verified=True,
    ),
    RuleSource(
        id="ipl_impact_player_2025_27",
        title="IPL Impact Player Regulation (2025-2027 cycle)",
        organization="BCCI / IPL",
        tier="supplementary",
        url="https://www.iplt20.com/news/4109/ipl-governing-council-announces-tata-ipl-player-regulations-2025-27",
        edition="2025-2027 cycle",
        effective_from=date(2025, 3, 1),
        verified=True,
        notes=(
            "Curated supplementary clauses. The Impact Player rule lives in the "
            "TATA IPL Player Regulations 2025-27 (a separate BCCI document not "
            "publicly hosted as PDF), not in the Match Playing Conditions PDF. "
            "Clauses sit in data/rules/curated/ — synthesized from the official "
            "iplt20.com announcement (news 4109) plus ESPNcricinfo / Wisden / "
            "Olympics.com explainers. Re-curate when BCCI publishes a public PDF."
        ),
    ),
    RuleSource(
        id="hundred_pc_2025",
        title="The Hundred Playing Conditions",
        organization="ECB",
        tier="league_mixed",
        url="https://resources.ecb.co.uk/ecb/document/2025/05/14/8bd24152-c515-42a0-83b2-b22e03da8045/The-Hundred-2025.pdf",
        edition="2025",
        effective_from=date(2025, 8, 1),
        verified=True,
        notes="Single PDF covers both men's and women's competitions.",
    ),
    RuleSource(
        id="bbl_pc_2024_25",
        title="BBL Playing Conditions",
        organization="Cricket Australia",
        tier="league_men",
        url="https://resources.cricket-australia.pulselive.com/cricket-australia/document/2024/11/21/31e47da0-e8a1-49cf-aec4-18462885881c/2024-25-BBL-Playing-Conditions-FINAL.pdf",
        edition="2024-25",
        verified=True,
        notes="Latest BBL men's PC publicly released. Refresh once 2025-26 published.",
    ),
    RuleSource(
        id="sa20_pc_2023",
        title="SA20 Playing Conditions",
        organization="CSA / SA20",
        tier="league_men",
        url="https://sa20.co.za/wp-content/uploads/2023/01/VF_SA20-Playing-Conditions-2023.pdf",
        edition="2023",
        verified=False,
        notes="URL confirmed correct, but Next.js + Cloudfront gate the path and serve an HTML shell to non-browser clients. Promote to Playwright-based fetcher when needed.",
    ),
    RuleSource(
        id="ilt20_pc",
        title="ILT20 Playing Conditions",
        organization="ECB UAE / ILT20",
        tier="league_men",
        url="",
        edition="TBD",
        verified=False,
        notes="No public PDF on ilt20.ae. ILT20 adopts ICC T20I PC with annexures; treat ICC T20I PC as fallback.",
    ),
    RuleSource(
        id="mlc_pc",
        title="Major League Cricket Playing Conditions",
        organization="USA Cricket / MLC",
        tier="league_men",
        url="",
        edition="TBD",
        verified=False,
        notes="No public PDF on majorleaguecricket.com. MLC follows ICC T20I PC with playoff annex.",
    ),
    RuleSource(
        id="cpl_pc",
        title="Caribbean Premier League Playing Conditions",
        organization="CWI",
        tier="league_men",
        url="",
        edition="2025",
        verified=False,
        notes="CPL adopted ICC's updated 2025 T20I PC. Use ICC T20I PC as primary; track CPL-specific addenda.",
    ),
    RuleSource(
        id="lpl_pc",
        title="Lanka Premier League Playing Conditions",
        organization="SLC / LPL",
        tier="league_men",
        url="",
        edition="TBD",
        verified=False,
        notes="No public PDF on lpl-srilanka.com. Adopt ICC T20I PC as fallback.",
    ),
    # --- Leagues (women's) ---
    RuleSource(
        id="wpl_pc_2026",
        title="WPL Playing Conditions",
        organization="BCCI / WPL",
        tier="league_women",
        url="https://www.wplt20.com/static-assets/pdfs/TATA_WPL_2026_Playing_Conditions.pdf",
        edition="Effective 1 January 2026",
        effective_from=date(2026, 1, 1),
        verified=False,
        notes="URL confirmed in WPL site search, but wplt20.com's Next.js SPA rewrites static-assets paths and serves an HTML shell to non-browser clients. Promote to Playwright-based fetcher when needed.",
    ),
    RuleSource(
        id="wbbl_pc_2025_26",
        title="WBBL Playing Conditions",
        organization="Cricket Australia",
        tier="league_women",
        url="https://resources.cricket-australia.pulselive.com/cricket-australia/document/2025/11/06/e193e9bf-0d4e-4f89-aa26-a79ef829cd99/2025-26-WBBL11-Playing-Conditions-24-October-2025.pdf",
        edition="2025-26 (WBBL|11)",
        verified=True,
    ),
    # --- Domestic ---
    RuleSource(
        id="cricket_aus_shield_2025_26",
        title="Sheffield Shield / Second XI Playing Conditions",
        organization="Cricket Australia",
        tier="domestic_men",
        url="https://resources.cricket-australia.pulselive.com/cricket-australia/document/2025/11/07/61b80b8c-bb0a-4ea9-9440-aebdbaf87bf6/2025-26-Sheffield-Shield-Second-XI-1-October-2025.pdf",
        edition="2025-26",
        verified=True,
    ),
    RuleSource(
        id="cricket_aus_oneday_cup_2025_26",
        title="Marsh One-Day Cup Playing Conditions",
        organization="Cricket Australia",
        tier="domestic_men",
        url="https://resources.cricket-australia.pulselive.com/cricket-australia/document/2025/11/07/a219316b-ffbe-4119-89fa-ae540abe9dae/2025-26-One-Day-Cup-Playing-Conditions-1-September-2025.pdf",
        edition="2025-26",
        verified=True,
    ),
    RuleSource(
        id="bcci_domestic_pc",
        title="BCCI Domestic Tournament Playing Conditions (Ranji / SMAT / Vijay Hazare)",
        organization="BCCI",
        tier="domestic_mixed",
        url="",
        edition="2025-26",
        verified=False,
        notes="No aggregated PC PDF on documents.bcci.tv. BCCI publishes per-tournament annexures; collect manually each season.",
    ),
    # --- Ethics + Conduct ---
    RuleSource(
        id="icc_code_of_conduct_players_2023",
        title="ICC Code of Conduct for Players & Player Support Personnel",
        organization="ICC",
        tier="ethics",
        url="https://images.icc-cricket.com/image/upload/prd/rhatyfvzipulmdvbfzdz.pdf",
        edition="Effective 16 June 2023",
        effective_from=date(2023, 6, 16),
        verified=True,
    ),
    RuleSource(
        id="icc_code_of_conduct_match_officials_2016",
        title="ICC Code of Conduct for Match Officials & Match Official Support Personnel",
        organization="ICC",
        tier="ethics",
        url="https://images.icc-cricket.com/image/upload/prd/uwwfg8g5ilyxzisk9pbw.pdf",
        edition="Effective 1 November 2016",
        effective_from=date(2016, 11, 1),
        verified=True,
    ),
    RuleSource(
        id="ipl_code_of_conduct_2025",
        title="IPL Code of Conduct for Players and Team Officials",
        organization="BCCI / IPL",
        tier="ethics",
        url="https://documents.iplt20.com/bcci/documents/1742708207275_Code_of_Conduct_for_Players_&_Team_Officials.pdf",
        edition="2025",
        verified=True,
    ),
    RuleSource(
        id="bcci_code_of_conduct_2025",
        title="BCCI Code of Conduct for Players and Team Officials",
        organization="BCCI",
        tier="ethics",
        url="https://www.hycricket.org/data-2025-26/BCCI/BCCI-coc-Players_Final-031025.pdf",
        edition="2025",
        verified=False,
        notes="Hyderabad Cricket Association mirror (BCCI's own copy not directly linked). Host's TLS certificate is for a different hostname, so httpx rejects it; promote to a fetcher that allows cert overrides if needed.",
    ),
    # --- Integrity ---
    RuleSource(
        id="icc_anti_corruption_2024",
        title="ICC Anti-Corruption Code for Participants",
        organization="ICC",
        tier="integrity",
        url="https://resources.ecb.co.uk/ecb/document/2024/03/28/958938e1-d7f0-4294-aeba-a987b1d55198/21.-ICC-Anti-Corruption-Code-for-Participants-1st-June-2024-vF.pdf",
        edition="Effective 1 June 2024",
        effective_from=date(2024, 6, 1),
        verified=True,
        notes="ECB-hosted mirror of ICC's global Anti-Corruption Code.",
    ),
]
