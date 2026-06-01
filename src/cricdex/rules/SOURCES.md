# Rule-source coverage

Snapshot of every entry in `manifest.py` and its current state.
Re-verify before each major re-ingest — publishers swap URLs annually.

Legend
- ✅ verified + downloaded + parsed
- 📝 curated supplementary clauses (no public PDF — synthesized from authoritative announcements)
- 🔒 URL known but blocked (SPA gate / TLS mismatch) → needs Playwright
- ⏳ no public PDF yet → check publisher periodically
- ↪️ no separate PDF; league explicitly adopts ICC PC

## MCC Laws

| ID | Status | Edition | Notes |
|---|---|---|---|
| `mcc_laws_2017_4th_2026` | ✅ | 2017 Code, 4th Edition 2026 | Spirit of Cricket preamble is the opening section of this PDF. |

## ICC men's

| ID | Status | Edition |
|---|---|---|
| `icc_pc_men_test_2025` | ✅ | Effective June 2025 |
| `icc_pc_men_odi_2025` | ✅ | Effective July 2025 |
| `icc_pc_men_t20i_2025` | ✅ | Effective July 2025 |
| `icc_wtc_2025_2027` | ✅ | 2025–2027 |
| `icc_men_t20wc_2026` | ✅ | 2026 World Cup specific |

## ICC women's

| ID | Status | Edition |
|---|---|---|
| `icc_pc_women_test_2025` | ✅ | Effective December 2025 |
| `icc_pc_women_odi_2025` | ✅ | Effective December 2025 |
| `icc_pc_women_t20i_2025` | ✅ | Effective December 2025 |

## ICC age-group

| ID | Status | Edition |
|---|---|---|
| `icc_u19_men_world_cup_2024` | ✅ | 2024 |
| `icc_u19_women_t20wc_2025` | ✅ | 2025 |

## Men's leagues

| ID | Status | Edition | Notes |
|---|---|---|---|
| `ipl_pc_2026` | ✅ | Effective 1 March 2026 | Match Playing Conditions only — does NOT include Impact Player rule. |
| `ipl_impact_player_2025_27` | 📝 | 2025-2027 cycle | Curated supplementary clauses (10) under `data/rules/curated/`. The underlying TATA IPL Player Regulations 2025-27 is a separate BCCI document not publicly hosted; clauses synthesized from iplt20.com announcement + ESPNcricinfo / Wisden / Olympics.com explainers. |
| `hundred_pc_2025` | ✅ | 2025 | Single PDF covers men's + women's competitions. |
| `bbl_pc_2024_25` | ✅ | 2024-25 | Refresh once 2025-26 men's PC is published. |
| `ilt20_pc` | ⏳ | TBD | No public PDF on ilt20.ae. ILT20 adopts ICC T20I PC with annexures. |
| `mlc_pc` | ↪️ | — | majorleaguecricket.com publishes no PC PDF; MLC adopts ICC T20I PC with playoff annex. |
| `cpl_pc` | ↪️ | 2025 | CPL formally adopted ICC's 2025 T20I PC. Use `icc_pc_men_t20i_2025`. |
| `lpl_pc` | ⏳ | TBD | No public PDF on lpl-srilanka.com. |

## Women's leagues

| ID | Status | Edition | Notes |
|---|---|---|---|
| `wbbl_pc_2025_26` | ✅ | 2025-26 (WBBL\|11) | |

## Domestic

| ID | Status | Edition | Notes |
|---|---|---|---|
| `cricket_aus_shield_2025_26` | ✅ | 2025-26 | Sheffield Shield + Second XI. |
| `cricket_aus_oneday_cup_2025_26` | ✅ | 2025-26 | Marsh One-Day Cup. |

## Ethics / conduct

| ID | Status | Edition | Notes |
|---|---|---|---|
| `icc_code_of_conduct_players_2023` | ✅ | Effective 16 June 2023 | |
| `icc_code_of_conduct_match_officials_2016` | ✅ | Effective 1 November 2016 | |
| `ipl_code_of_conduct_2025` | ✅ | 2025 | |

## Integrity

| ID | Status | Edition | Notes |
|---|---|---|---|
| `icc_anti_corruption_2024` | ✅ | Effective 1 June 2024 | ECB-hosted mirror of ICC's global Code. |

## Totals

- **29** entries
- **21** ✅ working today
- **3** 🔒 blocked behind SPA / TLS
- **3** ⏳ no public PDF yet
- **2** ↪️ explicitly adopt ICC PC (CPL, MLC)

Coverage by tier (✅ only): 1 laws · 5 ICC men's · 3 ICC women's · 2 age-group · 4 men's leagues · 1 women's league · 2 Cricket Australia domestic · 3 codes of conduct · 1 anti-corruption.
