"""Competition rules (config/competitions.toml → cricdex.competitions) and the squads + salaries
file Keep or release reads (data/curated/ipl_squads_2026.json)."""

from __future__ import annotations

import pytest

from cricdex import competitions
from cricdex.competitions import RULE_FIELDS, CompetitionError, parse

MINIMAL = """
schema = 1
[[competition]]
key = "alpha_2030"
name = "Alpha 2030"
league = "ipl"
season = 2030
cycle = "mini"
currency = "INR"
unit = "cr"
squads = "curated/whatever.json"
retention_deadline = "2029-11-15"
auction_date = "2029-12-16"
auction_venue = "Somewhere"
purse = 100.0
squad_min = 18
squad_max = 25
overseas_max = 8
assumed = [ASSUMED]
"""
ALL = ", ".join(f'"{f}"' for f in RULE_FIELDS)


def _parse(text: str):
    return parse(text, check_league=True)


def test_minimal_entry_parses_with_everything_assumed():
    comps = _parse(MINIMAL.replace("ASSUMED", ALL))
    c = comps["alpha_2030"]
    assert c.purse == 100.0 and c.max_retained == 0 and c.retained_cost == "salary"
    assert c.rules()["squad_max"] == 25


def test_a_rule_needs_a_source_or_the_assumed_label():
    missing = ", ".join(f'"{f}"' for f in RULE_FIELDS if f != "purse")
    with pytest.raises(CompetitionError, match="`purse` has no source"):
        _parse(MINIMAL.replace("ASSUMED", missing))
    sourced = MINIMAL.replace("ASSUMED", missing) + (
        '[[competition.source]]\nabout = "purse"\nstatus = "official"\ntitle = "t"\n'
        'url = "https://example.org/x"\ndate = "2029-01-01"\n'
    )
    assert _parse(sourced)["alpha_2030"].source[0].about == "purse"


@pytest.mark.parametrize(
    "change, err",
    [
        (('league = "ipl"', 'league = "nope"'), "isn't in config/leagues.toml"),
        (('cycle = "mini"', 'cycle = "huge"'), "cycle must be"),
        (('auction_date = "2029-12-16"', 'auction_date = "2029-11-01"'), "falls after the auction"),
        (('auction_date = "2029-12-16"', 'auction_date = "16 Dec"'), "isn't an ISO date"),
        (("squad_min = 18", "squad_min = 30"), "squad_min ≤ squad_max"),
        (("overseas_max = 8", "overseas_max = 26"), "overseas_max can't exceed"),
        (("purse = 100.0", "purse = 0.0"), "purse must be positive"),
        (('key = "alpha_2030"', 'key = "Alpha"'), "key must be lowercase"),
        (("schema = 1", "schema = 2"), "expected `schema = 1`"),
    ],
)
def test_bad_entries_are_refused(change, err):
    text = MINIMAL.replace("ASSUMED", ALL).replace(*change)
    with pytest.raises(CompetitionError, match=err):
        _parse(text)


def test_unknown_fields_and_bad_sources_are_refused():
    base = MINIMAL.replace("ASSUMED", ALL)
    with pytest.raises(CompetitionError, match="unknown field"):
        _parse(base + "rtm = 2\n")
    with pytest.raises(CompetitionError, match="isn't a rule field"):
        _parse(
            base
            + '[[competition.source]]\nabout = "x"\nstatus = "official"\ntitle = "t"\nurl = "https://a.b"\n'
        )
    with pytest.raises(CompetitionError, match="status must be"):
        _parse(
            base
            + '[[competition.source]]\nabout = "purse"\nstatus = "rumour"\ntitle = "t"\nurl = "https://a.b"\n'
        )
    with pytest.raises(CompetitionError, match="unknown rule field"):
        _parse(MINIMAL.replace("ASSUMED", '"purse", "vibes"'))
    with pytest.raises(CompetitionError, match="duplicate competition"):
        _parse(base + base.replace("schema = 1", ""))


# ---- the shipped file ---------------------------------------------------------------------------


def test_shipped_competitions_file_is_valid():
    comps = competitions.load()
    assert "ipl_2027" in comps
    c = comps["ipl_2027"]
    assert c.league == "ipl" and c.cycle == "mini" and c.season == 2027
    assert c.retention_deadline == "2026-11-15"
    assert c.squad_max == 25 and c.overseas_max == 8 and c.max_retained == 0 and c.rtm_cards == 0
    # the 2027 purse isn't published: it must be labelled an assumption
    assert "purse" in c.assumed
    assert all(s.url.startswith("https://") for s in c.source)
    assert competitions.default().key == "ipl_2027"


# ---- the squads + salaries file -------------------------------------------------------------------


@pytest.fixture(scope="module")
def ipl():
    c = competitions.get("ipl_2027")
    return c, competitions.load_squads(c)


def test_every_squad_player_has_a_positive_salary_and_an_acquisition(ipl):
    _, sq = ipl
    rows = [r for team in sq["squads"].values() for r in team]
    assert len(rows) >= 250
    for r in rows:
        assert isinstance(r.get("salary_cr"), int | float) and r["salary_cr"] > 0, r
        assert r.get("acquired") in {"retained", "trade", "auction", "replacement"}, r
        assert isinstance(r.get("overseas"), bool), r


def test_every_player_is_matched_or_listed_as_unmatched(ipl):
    _, sq = ipl
    listed = {(u["team"], u["name"]) for u in sq.get("_unmatched") or []}
    for team, rows in sq["squads"].items():
        for r in rows:
            assert r.get("cricsheet_id") or (team, r["name"]) in listed, (team, r["name"])
    # and nobody on the unmatched list has an id after all
    ids = {
        (t, r["name"]) for t, rows in sq["squads"].items() for r in rows if r.get("cricsheet_id")
    }
    assert not listed & ids


def test_no_player_in_two_squads(ipl):
    _, sq = ipl
    seen: dict[str, str] = {}
    for team, rows in sq["squads"].items():
        for r in rows:
            cid = r.get("cricsheet_id")
            if cid:
                assert cid not in seen or seen[cid] == team, (cid, seen.get(cid), team)
                seen[cid] = team


def test_squads_within_the_rules(ipl):
    c, sq = ipl
    keepable = competitions.squad_rows(c, sq)
    assert set(keepable) == set(sq["squads"])
    for team, rows in keepable.items():
        # the retention list is drawn from the current squad: at most the cap (replacements
        # signed during the season can push a squad's listed size past it, not the keepable core)
        core = [r for r in rows if r.get("acquired") != "replacement"]
        assert c.squad_min <= len(core) <= c.squad_max, (team, len(core))
        assert sum(1 for r in core if r["overseas"]) <= c.overseas_max, team


def test_retired_and_released_players_are_not_keepable(ipl):
    c, sq = ipl
    keepable = {r["name"] for rows in competitions.squad_rows(c, sq).values() for r in rows}
    assert "Ajinkya Rahane" not in keepable  # retired, July 2026
    assert "Mustafizur Rahman" not in keepable  # released at the BCCI's request
    assert "Rishabh Pant" in {r["name"] for r in sq["squads"]["DC"]}  # traded LSG -> DC for 2027


def test_salaries_reproduce_most_published_purses(ipl):
    """125 cr − the retained salaries = each team's published purse entering the 2026 auction:
    exact for most teams (the rest are listed in the docs as known differences)."""
    _, sq = ipl
    chk = sq["purse_check_2026"]
    ours: dict[str, float] = {}
    for team, rows in sq["squads"].items():
        for r in rows:
            src = (r.get("trade") or {}).get("from") or team
            sal = (r.get("trade") or {}).get("salary_before_cr", r["salary_cr"])
            if r.get("status") == "retained":
                ours[src] = ours.get(src, 0.0) + sal
    exact = [t for t, v in chk["remaining"].items() if abs(chk["purse"] - ours[t] - v) < 0.01]
    assert len(exact) >= 6, exact
