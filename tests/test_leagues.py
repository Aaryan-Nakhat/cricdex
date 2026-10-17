"""The league registry (config/leagues.toml → cricdex.leagues): the one list every surface reads."""

from __future__ import annotations

import os
import subprocess
import sys

import pytest

from cricdex import leagues
from cricdex.leagues import RegistryError, parse

# The men's leagues the product exports (the original eight plus the six added with the registry).
EXPORTED_MEN = {
    "ipl",
    "indian_domestic_male",
    "bbl",
    "sa20",
    "cpl",
    "blast",
    "t20s_male",
    "recently_played_30_male",
    "psl",
    "ilt20",
    "hundred_male",
    "mlc",
    "bpl",
    "lpl",
    "super_smash",
    "csa_t20_challenge",
}

MINIMAL = """
schema = 1
[tiers.top]
discount = 0.0
calibrated = true
[tiers.low]
discount = 0.5
calibrated = false

[[league]]
key = "alpha"
name = "Alpha League"
short = "AL"
zips = ["alpha_json.zip"]
gender = "male"
kind = "league"
country = "Somewhere"
order = 1
tier = "top"
export = true
scout_pool = true
scout_group = "peers"
auction_pool = true
auction_target = true
auction_nationalities = ["AAA", "BBB"]
auction_excluded_nationalities = ["CCC"]

[[league]]
key = "beta"
name = "Beta League"
short = "BL"
zips = ["beta_male_json.zip"]
gender = "male"
kind = "league"
country = "Elsewhere"
order = 2
tier = "low"
export = true
scout_pool = true
scout_group = "overseas"
draftable = true
auction_pool = true
"""


def _with(extra: str = "", replace: tuple[str, str] | None = None) -> str:
    text = MINIMAL
    if replace:
        assert replace[0] in text, replace[0]
        text = text.replace(*replace)
    return text + extra


# ---- the shipped registry ---------------------------------------------------------------------


def test_registry_loads_and_validates():
    reg = leagues.load()
    assert len(reg.leagues) >= len(EXPORTED_MEN)
    assert [lg.order for lg in reg.leagues] == sorted(lg.order for lg in reg.leagues)


def test_exported_leagues_are_the_mens_t20_product():
    assert set(leagues.exported_keys()) == EXPORTED_MEN
    assert all(lg.gender == "male" for lg in leagues.exported())


def test_womens_and_long_formats_are_known_but_not_exported():
    for key in ("wpl", "wbbl", "hundred_female", "t20s_female", "tests_male", "odis_male"):
        assert leagues.exists(key)
        assert not leagues.get(key).export


def test_calibrated_discounts_keep_their_values():
    # the values the pricing curve and the published prices were fitted with — never drift
    d = leagues.tier_discounts()
    assert d["ipl"] == 0.0
    assert d["smat"] == 1.28
    assert d["bbl"] == d["sa20"] == 0.45
    assert d["cpl"] == d["blast"] == 0.64
    for t in ("ipl", "smat", "bbl", "sa20", "cpl", "blast"):
        assert leagues.tiers()[t].calibrated


def test_new_leagues_borrow_a_tier_by_analogy_and_say_so():
    t = leagues.tiers()
    for key, disc in {
        "psl": 0.45,
        "ilt20": 0.45,
        "hundred_male": 0.45,
        "mlc": 0.64,
        "bpl": 0.64,
        "lpl": 0.64,
        "super_smash": 0.64,
        "csa_t20_challenge": 0.64,
    }.items():
        lg = leagues.get(key)
        assert leagues.discount(key) == disc, key
        assert not t[lg.tier].calibrated, key


def test_fixed_cricsheet_zip_names():
    # these four 404'd under their old names; MLC was listed but never pulled; SMAT is one zip
    assert leagues.get("ilt20").zips == ("ilt_male_json.zip",)
    assert leagues.get("hundred_male").zips == ("hnd_male_json.zip",)
    assert leagues.get("hundred_female").zips == ("hnd_female_json.zip",)
    assert leagues.get("wbbl").zips == ("wbb_female_json.zip",)
    assert leagues.get("mlc").zips == ("mlc_male_json.zip",)
    assert leagues.get("indian_domestic_male").zips == ("sma_json.zip",)


def test_pools_and_auction_target():
    assert leagues.auction_target().key == "ipl"
    gem = leagues.gem_pool()
    assert gem is not None and gem.key == "indian_domestic_male" and gem.tier == "smat"
    pools = leagues.scout_pools()
    assert pools[0].scout_group == "peers" and pools[0].tier == "ipl"
    assert len({lg.tier for lg in pools}) == len(pools)
    # men's T20Is stay out of the auction pool (associate-nation value inflation)
    assert "t20s_male" not in {lg.key for lg in leagues.auction_pool()}
    assert leagues.by_tier("smat").key == "indian_domestic_male"


def test_auction_nationality_rule_is_data():
    ipl = leagues.auction_target()
    assert "PAK" in ipl.auction_excluded_nationalities
    assert not ipl.auction_eligible("PAK")
    assert ipl.auction_eligible("IND") and ipl.auction_eligible("AUS")
    assert not ipl.auction_eligible("UGA")  # an associate side, not on the allow-list
    assert not ipl.auction_eligible(None)


def test_pricing_reads_the_registry():
    from cricdex.web_parity.pricing import TIER_PENALTY

    assert TIER_PENALTY == leagues.tier_discounts()


def test_labels_and_window_keys():
    assert leagues.label("indian_domestic_male") == "Syed Mushtaq Ali (SMAT)"
    assert leagues.short("indian_domestic_male") == "SMAT"
    assert leagues.label("ipl_last1y") == leagues.label("ipl")
    assert leagues.label("no_such_league") == "no_such_league"
    assert leagues.base_key("bbl_last3y") == "bbl"


def test_validate_collection():
    assert leagues.validate_collection("ipl") == "ipl"
    assert leagues.validate_collection("psl_last1y") == "psl_last1y"
    with pytest.raises(ValueError, match="Valid: ipl"):
        leagues.validate_collection("nope")
    with pytest.raises(ValueError):
        leagues.validate_collection("wpl", exported_only=True)
    with pytest.raises(ValueError):
        leagues.validate_collection("ipl; DROP TABLE x")


def test_site_payload_shape():
    p = leagues.site_payload()
    assert p["schema"] == leagues.SCHEMA
    assert [lg["key"] for lg in p["leagues"]] == leagues.keys()
    assert p["auction"]["target"] == "ipl"
    assert "PAK" in p["auction"]["excluded_nationalities"]
    assert p["gem_tier"] == "smat"
    assert p["tiers"]["smat"] == {"discount": 1.28, "calibrated": True}


def test_cli_lists_exported_keys():
    out = subprocess.run(
        [sys.executable, "-m", "cricdex.leagues", "list", "--exported", "--sep", " "],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    assert out == leagues.exported_keys()


# ---- validation -------------------------------------------------------------------------------


def test_minimal_registry_parses():
    reg = parse(MINIMAL)
    assert [lg.key for lg in reg.leagues] == ["alpha", "beta"]


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (("schema = 1", "schema = 9"), "schema"),
        (('key = "beta"', 'key = "alpha"'), "duplicate"),
        (('key = "beta"', 'key = "Beta"'), "lowercase"),
        (('key = "beta"', 'key = "beta_last1y"'), "time-window"),
        (('zips = ["beta_male_json.zip"]', 'zips = "beta_male_json.zip"'), "non-empty list"),
        (('zips = ["beta_male_json.zip"]', 'zips = ["beta.csv"]'), "_json.zip"),
        (('tier = "low"', 'tier = "nope"'), "unknown tier"),
        (
            (
                'gender = "male"\nkind = "league"\ncountry = "Elsewhere"',
                'gender = "x"\nkind = "league"\ncountry = "Elsewhere"',
            ),
            "gender",
        ),
        (('country = "Elsewhere"', 'country = "Elsewhere"\ncolour = "red"'), "unknown field"),
        (('scout_group = "overseas"', 'scout_group = "everyone"'), "scout_group"),
        (
            (
                'auction_excluded_nationalities = ["CCC"]',
                'auction_excluded_nationalities = ["AAA"]',
            ),
            "both allowed and excluded",
        ),
        (("auction_target = true\n", ""), "auction target"),
    ],
)
def test_registry_rejects(change, message):
    with pytest.raises(RegistryError, match=message):
        parse(_with(replace=change))


def test_pool_needs_export():
    with pytest.raises(RegistryError, match="export = true"):
        parse(
            _with(
                replace=(
                    'export = true\nscout_pool = true\nscout_group = "overseas"',
                    'export = false\nscout_pool = true\nscout_group = "overseas"',
                )
            )
        )


def test_scout_flags_need_a_pool():
    text = _with(
        """
[[league]]
key = "gamma"
name = "Gamma"
short = "G"
zips = ["gamma_json.zip"]
gender = "male"
kind = "league"
country = "X"
order = 3
draftable = true
"""
    )
    with pytest.raises(RegistryError, match="scout_pool"):
        parse(text)


def test_two_scout_pools_cannot_share_a_tier():
    with pytest.raises(RegistryError, match="share a tier"):
        parse(_with(replace=('tier = "low"', 'tier = "top"')))


def test_nationality_lists_only_on_the_target():
    text = _with(
        replace=(
            "draftable = true\nauction_pool = true",
            'draftable = true\nauction_pool = true\nauction_nationalities = ["AAA"]',
        )
    )
    with pytest.raises(RegistryError, match="auction target"):
        parse(text)


def test_registry_path_override(tmp_path, monkeypatch):
    f = tmp_path / "leagues.toml"
    f.write_text(MINIMAL, encoding="utf-8")
    monkeypatch.setenv("CRICDEX_LEAGUES", str(f))
    assert leagues.keys() == ["alpha", "beta"]
    assert leagues.auction_target().key == "alpha"


# ---- network (opt-in) -------------------------------------------------------------------------


@pytest.mark.skipif(
    os.environ.get("CRICDEX_NET_TESTS") != "1",
    reason="set CRICDEX_NET_TESTS=1 to hit cricsheet.org",
)
@pytest.mark.parametrize("url", sorted({u for lg in leagues.all() for u in lg.urls}))
def test_every_registry_zip_exists(url):
    import httpx

    r = httpx.head(url, follow_redirects=True, timeout=30)
    assert r.status_code == 200, f"{url} → {r.status_code}"
