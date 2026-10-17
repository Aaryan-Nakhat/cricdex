"""The player master: country codes, display names, open-data parsers, capped, data-driven roles,
and the exporter's data-quality gates. Pure functions on fixtures; no network, no real DB."""

from __future__ import annotations

import importlib.util
import json
import zipfile
from pathlib import Path

import pytest

from cricdex import leagues
from cricdex.scout.identity import countries, master, names, sources

ROOT = Path(__file__).resolve().parents[1]


# ---- countries --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("spellings", "code"),
    [
        (["RSA", "ZAF", "SA", "South Africa", "rsa"], "ZAF"),
        (["SRI", "LKA", "SL", "Sri Lanka"], "LKA"),
        (["BAN", "BGD", "Bangladesh"], "BGD"),
        (["IRE", "IRL", "Ireland"], "IRL"),
        (["WI", "WIN", "West Indies", "Jamaica", "Trinidad and Tobago", "BRB"], "WIN"),
        (["NED", "NLD", "Netherlands"], "NLD"),
        (["ZIM", "ZWE"], "ZWE"),
        (["UAE", "ARE", "United Arab Emirates"], "ARE"),
        (["ENG", "England", "GBR", "United Kingdom"], "ENG"),
        (["USA", "United States of America"], "USA"),
        (["IND", "India"], "IND"),
    ],
)
def test_every_spelling_of_a_nation_is_one_code(spellings, code):
    assert {countries.normalise(s) for s in spellings} == {code}


def test_unknown_countries_are_none():
    for v in (None, "", "unknown", "none", "N/A", "Atlantis Republic"):
        assert countries.normalise(v) is None


def test_every_cricsheet_international_side_has_a_code():
    # the team names in Cricsheet's men's T20I archive (spot check of the awkward ones)
    for team in (
        "United States of America",
        "Hong Kong",
        "Papua New Guinea",
        "Isle of Man",
        "Turks and Caicos Island",
        "Swaziland",
        "Eswatini",
        "St Helena",
        "Ivory Coast",
    ):
        assert countries.team_country(team), team
    assert countries.team_country("ICC World XI") is None


def test_auction_eligibility_ignores_spelling():
    target = leagues.auction_target()
    assert target.auction_eligible("RSA") == target.auction_eligible("ZAF") is True
    assert target.auction_eligible("Sri Lanka") is True
    assert target.auction_eligible("PAK") is False


def test_taxonomy_codes_all_normalise_into_the_canonical_set():
    tax = json.loads((ROOT / "data" / "curated" / "player_taxonomy.json").read_text("utf-8"))
    codes = countries.all_codes()
    raw = {r.get("country") for r in tax.values() if isinstance(r, dict)}
    out = {countries.normalise(c) for c in raw} - {None}
    # duplicates collapse: no nation is left with two codes
    for a, b in (("RSA", "ZAF"), ("SRI", "LKA"), ("BAN", "BGD"), ("IRE", "IRL"), ("WI", "WIN")):
        assert a not in out or countries.normalise(a) == countries.normalise(b)
    assert {"RSA", "SRI", "BAN", "IRE"} & out == set()
    assert out <= codes | {c for c in out if len(c) == 3}


# ---- names ------------------------------------------------------------------------------------


def test_full_words_rejects_initials():
    assert names.is_full_words("Virat Kohli")
    assert names.is_full_words("Yashasvi Bhupendra Jaiswal")
    for n in ("V Kohli", "MS Dhoni", "YBK Jaiswal", "Kohli", "", None, "A.B. de Villiers"):
        assert not names.is_full_words(n), n


def test_candidate_prefers_wikidata_then_shortest_register_variant():
    variants = ["Yashasvi Bhupendra Jaiswal", "Y Jaiswal", "YB Jaiswal"]
    assert names.candidate("YBK Jaiswal", "Yashasvi Jaiswal", variants) == (
        "Yashasvi Jaiswal",
        "wikidata",
    )
    assert names.candidate("YBK Jaiswal", None, variants) == (
        "Yashasvi Bhupendra Jaiswal",
        "register",
    )
    assert names.candidate("SV Samson", None, ["Sanju Samson", "S Samson"]) == (
        "Sanju Samson",
        "register",
    )
    assert names.candidate("A Khan", None, ["A Khan"]) == ("A Khan", "scorecard")
    # a disambiguator never reaches the display name
    assert names.clean_label("Spencer Johnson (cricketer)") == "Spencer Johnson"


def test_llm_correction_must_keep_a_known_token():
    cache = {
        "a": {
            "candidate": "V Kohli",
            "display_name": "Virat Kohli",
            "verdict": "corrected",
            "confidence": "high",
        },
        "b": {
            "candidate": "A Khan",
            "display_name": "Babar Azam",
            "verdict": "corrected",
            "confidence": "high",
        },
        "c": {
            "candidate": "MS Dhoni",
            "display_name": "MS Dhoni",
            "verdict": "confirmed",
            "confidence": "high",
        },
        "d": {
            "candidate": "R Sharma",
            "display_name": "Rohit Sharma",
            "verdict": "corrected",
            "confidence": "low",
        },
    }
    r = names.resolve("a", "V Kohli", "V Kohli", "scorecard", ["Virat Kohli"], cache, None)
    assert r["display_name"] == "Virat Kohli" and r["name_check"] == "llm_corrected"
    r = names.resolve("b", "A Khan", "A Khan", "scorecard", [], cache, None)
    assert r["display_name"] == "A Khan" and r["name_check"] == "llm_rejected"
    r = names.resolve("c", "MS Dhoni", "MS Dhoni", "wikidata", [], cache, None)
    assert r["name_check"] == "llm_confirmed"
    r = names.resolve("d", "R Sharma", "R Sharma", "scorecard", [], cache, None)
    assert r["display_name"] == "R Sharma"  # a low-confidence answer is only a suggestion
    # a stale answer (asked about a different candidate) is ignored; an override always wins
    r = names.resolve("a", "V Kohli", "Virat Kohli", "wikidata", [], cache, None)
    assert r["name_check"] == "unverified"
    r = names.resolve("a", "V Kohli", "V Kohli", "scorecard", [], cache, "King Kohli")
    assert r == {"display_name": "King Kohli", "name_source": "override", "name_check": "reviewed"}


def test_llm_cannot_give_a_debutant_a_famous_namesakes_first_name():
    # a newer player the model doesn't know: an unknown first name at medium confidence is refused
    assert not names.plausible_correction("Vipin Nigam", ["V Nigam"], "V Nigam", "medium")
    assert names.plausible_correction("Vipin Nigam", ["V Nigam"], "V Nigam", "high")
    # a full-word candidate can't swap its given name for an unrelated one
    assert not names.plausible_correction(
        "Rahul Sharma", ["Satyanarayana Raju Sharma"], "Satyanarayana Sharma", "high"
    )
    # spelling variants, short forms and initials of known names are fine
    assert names.plausible_correction("Liton Das", ["Litton Das"], "Litton Das", "medium")
    assert names.plausible_correction("Phil Salt", ["Philip Salt"], "Philip Salt", "medium")
    assert names.plausible_correction(
        "T Natarajan", ["Thangarasu Natarajan"], "Thangarasu Natarajan"
    )


# ---- open-data parsers -------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "style"),
    [
        ("Right-arm medium-fast", "right-arm-fast-medium"),
        ("Right-arm fast-medium", "right-arm-fast-medium"),
        ("Right-arm fast", "right-arm-fast"),
        ("Right-arm medium", "right-arm-medium"),
        ("Left-arm fast-medium", "left-arm-fast"),
        ("Left-arm medium", "left-arm-medium"),
        ("Slow left-arm orthodox", "left-arm-orthodox"),
        ("Left-arm unorthodox spin", "left-arm-wrist-spin"),
        ("Right-arm leg break", "leg-spin"),
        ("Leg break googly", "leg-spin"),
        ("Right-arm off break", "off-spin"),
        ("Right-arm off break; right-arm leg break", "off-spin"),
        ("", None),
    ],
)
def test_bowling_style_text(text, style):
    assert sources.parse_bowling_style(text) == style


def test_infobox_markup_is_stripped_before_parsing():
    text = sources._strip_markup("Right-arm [[fast bowling|medium-fast]]<ref>x</ref>")
    assert text == "Right-arm medium-fast"


def test_style_category_and_arm_cover_every_style():
    assert set(sources.STYLE_CATEGORY) == set(sources.STYLE_ARM)
    assert sources.STYLE_CATEGORY["leg-spin"] == "spin"
    assert sources.STYLE_ARM["left-arm-orthodox"] == "left"


INFOBOX = """{{Short description|Indian cricketer}}
{{Infobox cricketer
| name = Hardik Pandya
| full_name = Hardik Himanshu Pandya
| birth_date = {{Birth date and age|1993|10|11|df=yes}}
| batting = Right-handed
| bowling = Right-arm [[fast bowling|medium-fast]]<ref>{{cite web|url=x}}</ref>
| role = [[All-rounder]]
| country = India
| club1 = {{nowrap|[[Mumbai Indians]]}}
}}
'''Hardik Pandya''' is a cricketer."""


def test_parse_infobox():
    f = sources.parse_infobox(INFOBOX)
    assert f["full_name"] == "Hardik Himanshu Pandya"
    assert f["dob"] == "1993-10-11"
    assert sources.parse_batting_hand(f["batting"]) == "right"
    assert sources.parse_bowling_style(f["bowling"]) == "right-arm-fast-medium"
    assert sources.parse_role(f["role"]) == "allrounder"
    assert sources.parse_infobox("no infobox here") is None


PERSONNEL = """intro
== Pre-auction ==
{| class="wikitable plainrowheaders"
|+ Retired players
! Date !! Name
|-
| 27 August 2025
! scope="row" | {{sortname|Ravichandran|Ashwin}}
| [[Chennai Super Kings]] || 38 || <ref>{{cite news|url= https://example.org/ashwin}}</ref>
|}
== Player retention ==
=== Retained players ===
{| class="wikitable"
|+ style="x" | [[Chennai Super Kings|<span>Chennai Super Kings</span>]]
|-
| 1
! scope="row" | {{sortname|Ruturaj|Gaikwad}}
| {{cr|IND}} || 18
|}
== Auction ==
=== Sold players ===
{| class="wikitable"
|+ Set 1
|-
| 3
! scope="row" | {{sortname|Cameron|Green}}
| {{cr|AUS}} || 29 || 200 || [[Kolkata Knight Riders]] || 2520 || {{N/A}}
|-
| 5
! scope="row" | {{sortname|David|Miller|dab=South African cricketer}}
| {{cr|SA}} || 141 || 200 || [[Delhi Capitals]] || 200 || [[Lucknow Super Giants]]
|}
== Withdrawn players ==
{| class="wikitable"
|-
! scope="row" | {{sortname|Ruturaj|Gaikwad}}
| [[Chennai Super Kings]] || 18 || Injury || 1 April 2026 || {{sortname|Urvil|Patel}} || 30 || 2 April 2026 || x
|}
== References ==
"""


def test_parse_ipl_personnel():
    d = sources.parse_ipl_personnel(PERSONNEL)
    assert [r["name"] for r in d["retired"]] == ["Ravichandran Ashwin"]
    assert d["retired"][0]["team"] == "CSK"
    csk = {p["name"]: p for p in d["squads"]["CSK"]}
    assert csk["Ruturaj Gaikwad"]["status"] == "retained" and csk["Ruturaj Gaikwad"]["withdrawn"]
    assert csk["Urvil Patel"]["status"] == "replacement"
    assert [p["name"] for p in d["squads"]["KKR"]] == ["Cameron Green"]
    # the 2026 team, not the 2025 one, and the article title carries the disambiguator
    assert d["squads"]["DC"][0]["wiki_title"] == "David Miller (South African cricketer)"
    assert d["squads"]["LSG"] == []


def test_international_zip_reads_xis_not_officials(tmp_path):
    match = {
        "info": {
            "dates": ["2016-01-26"],
            "gender": "male",
            "players": {"India": ["HH Pandya"], "Australia": ["SPD Smith"]},
            "registry": {
                "people": {
                    "HH Pandya": "dbe50b21",
                    "SPD Smith": "30a45b23",
                    "Umpire One": "u0000001",
                }
            },
            "officials": {"umpires": ["Umpire One"]},
        }
    }
    z = tmp_path / "odis_male_json.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("1.json", json.dumps(match))
        zf.writestr("README.txt", "not a match")
    rows = sources.read_international_zip(z, "odi")
    assert sorted(rows) == [
        ("30a45b23", "Australia", "2016-01-26", "odi"),
        ("dbe50b21", "India", "2016-01-26", "odi"),
    ]


# ---- data-driven role --------------------------------------------------------------------------


def _st(m, bf, bb, bowl_m, pos, stumpings=0):
    return {
        "matches": m,
        "balls_faced": bf,
        "balls_bowled": bb,
        "bowl_matches": bowl_m,
        "mean_bat_pos": pos,
        "stumpings": stumpings,
        "bat_innings": m,
    }


def test_data_role():
    # a seam-bowling all-rounder: bats in the top six, bowls three overs most games
    assert master.data_role(_st(100, 1500, 1800, 90, 5.2))[0] == "allrounder"
    # a specialist bowler: bowls every game, bats at 9
    assert master.data_role(_st(100, 200, 2300, 98, 9.1))[0] == "bowler"
    # an opener who bowls a few part-time overs is not an all-rounder
    assert master.data_role(_st(100, 2200, 120, 15, 1.8))[0] == "batter"
    # stumpings make a keeper
    assert master.data_role(_st(100, 1800, 0, 0, 3.0, stumpings=12))[0] == "wk_batter"
    # between part-time and regular: no verdict from the data
    assert master.data_role(_st(100, 2000, 600, 50, 3.0))[0] is None
    # too few matches to say anything
    assert master.data_role(_st(5, 100, 100, 5, 4.0))[0] is None


def test_resolve_role_order():
    assert master.resolve_role({"primary_role": "allrounder"}, "batter", "batter") == (
        "batter",
        "ball_data",
    )
    assert master.resolve_role({"primary_role": "allrounder"}, "batter", None) == (
        "batter",
        "wikipedia",
    )
    assert master.resolve_role({"primary_role": "bowler"}, None, None) == ("bowler", "llm")
    # a keeper with no stumpings in the data yet keeps the keeper tag
    assert master.resolve_role({"primary_role": "wk_batter"}, None, "batter") == (
        "wk_batter",
        "llm",
    )


def test_identity_block_defaults():
    b = master.identity_block(None, fallback_name="V Kohli")
    assert set(b) == set(master.IDENTITY_FIELDS)
    assert b["display_name"] == b["full_name"] == "V Kohli"
    assert b["aliases"] == ["V Kohli"]
    assert b["capped"] is False and b["retired"] is False and b["active"] is False


def test_overrides_file_is_valid():
    ov = json.loads((ROOT / "data" / "curated" / "player_overrides.json").read_text("utf-8"))
    allowed = {
        "display_name",
        "full_name",
        "aliases",
        "primary_role",
        "bowling_style",
        "batting_hand",
        "country",
        "team",
        "retired",
        "retired_scope",
        "dob",
    }
    for cid, rec in ov.items():
        if cid.startswith("_"):
            continue
        assert rec.get("_name") and rec.get("_evidence"), cid
        fields = {k for k in rec if not k.startswith("_")}
        assert fields <= allowed, (cid, fields - allowed)
        assert rec.get("primary_role") in (None, *master.ROLES)
        assert rec.get("bowling_style") in (None, *master.STYLES)
        if "country" in rec:
            assert countries.normalise(rec["country"]) == rec["country"]


# ---- exporter quality gates --------------------------------------------------------------------


def _export_site():
    spec = importlib.util.spec_from_file_location(
        "export_site", ROOT / "scripts" / "export_site.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_numbers_stored_as_strings_become_numbers():
    es = _export_site()
    rows = [
        {
            "batter": "1",
            "total_runs": "1028",
            "sr": "135.5",
            "match_id": "1082591",
            "match_date": "2020",
            "season": "2020",
            "key_cricinfo": "253802",
        }
    ]
    out = es._numify(rows)[0]
    assert out["total_runs"] == 1028 and out["sr"] == 135.5
    assert out["match_id"] == "1082591" and out["season"] == "2020" and out["batter"] == "1"
    assert out["match_date"] == "2020" and out["key_cricinfo"] == "253802"


def test_impossible_values_stop_the_export():
    es = _export_site()
    es._assert_rows([{"name": "x", "balls": 10, "sr": 150.0, "ngi_total": -3.2}], "ok")
    for bad in (
        {"balls": -1},
        {"sr": 900.0},
        {"econ": 50.0},
        {"bdr_pct": 140.0},
        {"runs": float("nan")},
    ):
        with pytest.raises(es.DataQualityError):
            es._assert_rows([{"name": "x", **bad}], "bad")
    good = {
        "cricsheet_id": "a",
        "name": "A",
        "display_name": "A",
        "country": "IND",
        "primary_role": "batter",
        "bowling_category": None,
        "capped": True,
        "active": True,
        "retired": False,
        "aliases": [],
        "dob": "1990-01-01",
        "balls_faced": 1,
        "balls_bowled": 0,
        "matches": 1,
    }
    es._assert_players([good], "ok", "2026-01-01")
    for bad in (
        {"country": "RSA"},
        {"primary_role": "keeper"},
        {"capped": "yes"},
        {"dob": "2020-01-01"},
        {"display_name": ""},
    ):
        with pytest.raises(es.DataQualityError):
            es._assert_players([{**good, **bad}], "bad", "2026-01-01")
    with pytest.raises(es.DataQualityError):
        es._assert_players([good, good], "dup", "2026-01-01")
