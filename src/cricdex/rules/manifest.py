"""Manifest of cricket rulebook PDF sources.

Each entry tracks a versioned PDF. `url` must be populated and `verified=True`
before bulk download. Empty URLs are skipped by the ingester.
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
    RuleSource(
        id="mcc_laws_2017_3rd_2022",
        title="MCC Laws of Cricket (2017 Code, 3rd Edition 2022)",
        organization="MCC",
        tier="laws",
        url="",
        edition="2017 Code, 3rd Edition 2022",
        effective_from=date(2022, 10, 1),
        notes="Source: lords.org/mcc/laws — fetch latest PDF link from MCC page.",
    ),
    RuleSource(
        id="icc_pc_test_2026",
        title="ICC Men's Test Match Playing Conditions",
        organization="ICC",
        tier="international",
        url="",
        edition="2026",
        notes="icc-cricket.com/about/cricket/rules-and-regulations",
    ),
    RuleSource(
        id="icc_pc_odi_2026",
        title="ICC Men's ODI Playing Conditions",
        organization="ICC",
        tier="international",
        url="",
        edition="2026",
    ),
    RuleSource(
        id="icc_pc_t20i_2026",
        title="ICC Men's T20I Playing Conditions",
        organization="ICC",
        tier="international",
        url="",
        edition="2026",
    ),
    RuleSource(
        id="icc_pc_women_test_2026",
        title="ICC Women's Test Match Playing Conditions",
        organization="ICC",
        tier="international_women",
        url="",
        edition="2026",
    ),
    RuleSource(
        id="icc_pc_women_odi_2026",
        title="ICC Women's ODI Playing Conditions",
        organization="ICC",
        tier="international_women",
        url="",
        edition="2026",
    ),
    RuleSource(
        id="icc_pc_women_t20i_2026",
        title="ICC Women's T20I Playing Conditions",
        organization="ICC",
        tier="international_women",
        url="",
        edition="2026",
    ),
    RuleSource(
        id="icc_pc_u19_2026",
        title="ICC Under-19 Playing Conditions",
        organization="ICC",
        tier="age_group",
        url="",
        edition="2026",
    ),
    RuleSource(
        id="ipl_pc_2026",
        title="IPL Playing Conditions",
        organization="BCCI / IPL",
        tier="league",
        url="",
        edition="2026",
        notes="iplt20.com About → Playing Conditions",
    ),
    RuleSource(
        id="wpl_pc_2026",
        title="WPL Playing Conditions",
        organization="BCCI / WPL",
        tier="league_women",
        url="",
        edition="2026",
    ),
    RuleSource(
        id="hundred_pc_2025",
        title="The Hundred Playing Conditions",
        organization="ECB",
        tier="league",
        url="",
        edition="2025",
    ),
    RuleSource(
        id="bbl_pc_2025_26",
        title="BBL Playing Conditions",
        organization="Cricket Australia",
        tier="league",
        url="",
        edition="2025/26",
    ),
    RuleSource(
        id="wbbl_pc_2025_26",
        title="WBBL Playing Conditions",
        organization="Cricket Australia",
        tier="league_women",
        url="",
        edition="2025/26",
    ),
    RuleSource(
        id="sa20_pc_2026",
        title="SA20 Playing Conditions",
        organization="CSA",
        tier="league",
        url="",
        edition="2026",
    ),
    RuleSource(
        id="ilt20_pc_2026",
        title="ILT20 Playing Conditions",
        organization="ECB UAE",
        tier="league",
        url="",
        edition="2026",
    ),
    RuleSource(
        id="mlc_pc_2025",
        title="Major League Cricket Playing Conditions",
        organization="USA Cricket / MLC",
        tier="league",
        url="",
        edition="2025",
    ),
    RuleSource(
        id="cpl_pc_2025",
        title="CPL Playing Conditions",
        organization="CWI",
        tier="league",
        url="",
        edition="2025",
    ),
    RuleSource(
        id="lpl_pc_2025",
        title="Lanka Premier League Playing Conditions",
        organization="SLC",
        tier="league",
        url="",
        edition="2025",
    ),
    RuleSource(
        id="bcci_domestic_pc_2026",
        title="BCCI Domestic Tournament Playing Conditions",
        organization="BCCI",
        tier="domestic",
        url="",
        edition="2026",
    ),
    RuleSource(
        id="mcc_spirit_preamble",
        title="MCC Spirit of Cricket Preamble",
        organization="MCC",
        tier="ethics",
        url="",
        edition="2017",
    ),
    RuleSource(
        id="icc_code_of_conduct",
        title="ICC Code of Conduct for Players & Officials",
        organization="ICC",
        tier="ethics",
        url="",
        edition="2026",
    ),
    RuleSource(
        id="icc_anti_corruption_code",
        title="ICC Anti-Corruption Code for Participants",
        organization="ICC",
        tier="integrity",
        url="",
        edition="2026",
    ),
]
