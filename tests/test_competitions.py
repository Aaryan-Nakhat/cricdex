"""Competition rules (config/competitions.toml → cricdex.competitions) and the squads + salaries
file Keep or release reads (data/curated/ipl_squads_2026.json)."""

from __future__ import annotations

import json

import pytest

from cricdex import competitions
from cricdex.competitions import RULE_FIELDS, CompetitionError, parse
from cricdex.config import DATA_DIR as DATA

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


def test_salaries_reproduce_the_published_purses(ipl):
    """125 cr − the retained salaries − the 2025 retention-slab charge = each team's published purse
    entering the 2026 auction, exactly, for all ten teams; and the published pre-auction purse less
    our auction prices = the published purse left after the auction (issue I6)."""
    _, sq = ipl
    chk = sq["purse_check_2026"]
    slab = chk.get("slab_charge") or {}
    ours: dict[str, float] = {}
    bought: dict[str, float] = {}
    for team, rows in sq["squads"].items():
        for r in rows:
            src = (r.get("trade") or {}).get("from") or team
            sal = (r.get("trade") or {}).get("salary_before_cr", r["salary_cr"])
            if r.get("status") == "retained":
                ours[src] = ours.get(src, 0.0) + sal
            elif r.get("status") == "bought":
                bought[src] = bought.get(src, 0.0) + sal
    for t, v in chk["remaining"].items():
        assert abs(chk["purse"] - ours[t] - slab.get(t, 0.0) - v) < 0.01, t
    for t, v in chk["remaining_after_auction"].items():
        assert abs(chk["remaining"][t] - bought[t] - v) < 0.01, t
    # the slab only ever adds to what the purse counts (a fixed charge at least the salary in sum)
    assert all(v > 0 for v in slab.values())


def test_slab_rule_reproduces_2025_and_2026_purses(ipl):
    """The retention-slab mechanism, not a hand-entered charge: the purse counts a team's 2025 mega
    retentions together as max(the first n capped slabs + 4 cr per uncapped one, their salaries).
    That reproduces every team's published purse entering the 2025 mega auction and, charging the
    2025 retentions still on each squad on 15 Nov 2025, the 2026 one (and the hand-kept per-team
    `slab_charge`)."""
    from cricdex.web_parity.keep import slab_charge

    c, sq = ipl
    rules = c.rules()
    assert rules["retained_cost"] == "slabs" and rules["retention_slabs"] == [18, 14, 11, 18, 14]
    mr = sq["mega_retentions_2025"]
    hist = json.loads((DATA / "curated" / "ipl_auction_history.json").read_text(encoding="utf-8"))
    sal25 = {
        (r["team"], r["name"]): r["salary_cr"] for r in hist["retentions"] if r["season"] == 2025
    }
    for t, v in mr["teams"].items():
        holders = [
            {"name": n, "salary": sal25[(t, n)], "slab_holder": k}
            for k in ("capped", "uncapped")
            for n in v[k]
        ]
        assert (
            abs(mr["purse_2025"] - slab_charge(holders, rules) - mr["remaining_2025"][t]) < 0.01
        ), t
    chk = sq["purse_check_2026"]
    for t, published in chk["remaining"].items():
        holders, other = [], 0.0
        for team, rows in sq["squads"].items():
            for r in rows:
                src = (r.get("trade") or {}).get("from") or team
                if src != t or r.get("status") != "retained":
                    continue
                sal = (r.get("trade") or {}).get("salary_before_cr", r["salary_cr"])
                # a move since the season (Kuldeep Yadav, DC -> LSG) was still a DC retention then
                then = {
                    **r,
                    "trade": None,
                    "acquired": "retained" if r.get("trade") else r.get("acquired"),
                }
                k = competitions.slab_holder(sq, t, then)
                if k:
                    holders.append({"name": r["name"], "salary": sal, "slab_holder": k})
                else:
                    other += sal
        charged = other + (slab_charge(holders, rules) if holders else 0.0)
        assert abs(chk["purse"] - charged - published) < 0.01, t
        salaries = other + sum(h["salary"] for h in holders)
        assert abs(charged - salaries - chk.get("slab_charge", {}).get(t, 0.0)) < 0.01, t
