"""Playing time (scout/playing_time.py, METHODOLOGY §6c): contribution per match, the projected XI,
the P(plays) inputs and the shipped model file."""

from __future__ import annotations

import math

import pytest

from cricdex.scout import playing_time as pt
from cricdex.web_parity import bidplan as bp

REPL = {"bat": {"top": -7.0, "middle": -17.0, "lower": -23.0, "tail": -63.0},
        "bowl": {"frontline": -11.0, "part_time": -27.0}}  # fmt: skip


def test_slot_groups():
    assert [pt.slot_group(x) for x in (1, 3, 4, 5, 6, 7, 8, None)] == [
        "top", "top", "middle", "middle", "lower", "lower", "tail", "tail"]  # fmt: skip


def test_contribution_counts_both_disciplines_at_their_balls():
    # an all-rounder: batting at No. 6 (13 balls) and bowling 3 overs (18 balls)
    c, sd, parts = pt.contribution((2.0, 4.0), (10.0, 3.0), 13.0, 18.0, 6.0, REPL)
    assert parts["bat"] == pytest.approx((2.0 + 23.0) * 13 / 100)
    assert parts["bowl"] == pytest.approx((10.0 + 11.0) * 18 / 100)
    assert c == pytest.approx(parts["bat"] + parts["bowl"])
    assert sd == pytest.approx(math.hypot(4.0 * 0.13, 3.0 * 0.18))
    # a bowler who rarely bats: his batting is measured against a tail-ender's, at his 1 ball
    c2, _, p2 = pt.contribution((-40.0, 5.0), (20.0, 2.0), 1.0, 23.0, 10.0, REPL)
    assert p2["bat"] == pytest.approx(0.23) and p2["repl_bat"] == -63.0
    # no rating in a discipline: counted at replacement (0)
    c3, _, p3 = pt.contribution(None, (5.0, 2.0), 0.0, 22.0, None, REPL)
    assert p3["bat"] == 0.0 and c3 == pytest.approx(16.0 * 0.22)
    # part-time bowler group below FRONTLINE_BALLS
    _, _, p4 = pt.contribution((10.0, 2.0), (-5.0, 3.0), 25.0, 6.0, 2.0, REPL)
    assert p4["repl_bowl"] == -27.0


def test_unknown_position_takes_the_roles_typical_one():
    """A player with no batting position in the window (no recent match) gets his role's median
    position, so a batter is measured against a batter's replacement level, not a tail-ender's:
    a batter rated −9 must not be worth +8 runs a match (audit item 6, follow-up)."""
    import polars as pl

    rows = []
    for k, (cid, pos) in enumerate([("b1", 2), ("b2", 4), ("b3", 3), ("w1", 10), ("w2", 9)]):
        for m in range(3):
            rows.append({"match_id": f"m{k}{m}", "date": "2026-04-0" + str(m + 1), "team": "T",
                         "cid": cid, "bat_pos": float(pos), "faced": 20.0 if pos < 8 else 2.0,
                         "bowled": 0.0 if pos < 8 else 24.0, "team_faced": 115.0,
                         "team_bowled": 115.0, "league": "ipl", "season": 2026})  # fmt: skip
    u = pl.DataFrame(rows)
    roles = {"b1": "batter", "b2": "batter", "b3": "batter", "w1": "bowler", "w2": "bowler",
             "new_bat": "batter", "new_bowl": "bowler"}  # fmt: skip
    bm = {"bat": pt.BallsModel("bat", mu={"batter": 0.15, "bowler": 0.02}),
          "bowl": pt.BallsModel("bowl", mu={"batter": 0.0, "bowler": 0.18})}  # fmt: skip
    us = pt.expected_usage(u, "2026-12-01", list(roles), bm, 115.0, roles)
    assert us["b2"]["pos"] == 4.0  # his own
    assert us["new_bat"]["pos"] == 3.0  # batters' median (2, 3, 4)
    assert us["new_bowl"]["pos"] == 9.5  # bowlers' median: still the tail
    c, _, parts = pt.contribution((-9.0, 17.0), None, us["new_bat"]["faced"], 0.0,
                                  us["new_bat"]["pos"], REPL)  # fmt: skip
    assert parts["repl_bat"] == REPL["bat"]["top"] and c < 0


def test_projected_xi_overseas_and_line():
    squad = [pt.squad_member(f"o{i}", 9.0 - i, "batter", True) for i in range(6)]
    squad += [pt.squad_member(f"b{i}", 4.0 - i * 0.5, "bowler", False) for i in range(6)]
    squad += [
        pt.squad_member("k", 1.0, "keeper", False),
        pt.squad_member("x", 0.5, "batter", False),
    ]
    xi = pt.projected_xi(squad)
    assert sum(1 for c, v in xi.items() if v["in_xi"] and c.startswith("o")) == 4
    assert xi["k"]["in_xi"]  # a keeper must play
    assert xi["o4"]["os_rank"] == 5 and not xi["o4"]["in_xi"]


def test_features_bounded():
    f = pt.play_features({"contrib": 40.0, "in_xi": True, "margin": -20.0, "rank": 1, "overseas": True,
                          "os_rank": 6, "ipl_matches": 100, "age": 40.0, "last_share": None,
                          "keeper": False, "captain": True, "season": 2026})  # fmt: skip
    assert f["contrib"] == 12.0 and f["margin"] == -6.0 and f["no_last"] == 1.0
    assert f["os_out"] == 1.0 and f["os_rank_gt4"] == 2.0 and f["impact_era"] == 1.0
    g = pt.fa_features({"contrib": 3.0, "margin": 1.0, "ipl_matches": 0, "gap": None, "age": None,
                        "last_share": None, "season": 2020})  # fmt: skip
    assert g["never_ipl"] == 1.0 and g["gap"] == 0.0 and g["played_last"] == 0.0


def test_shipped_model_sane():
    m = pt.load_model()
    if m is None:
        pytest.skip("no config/playing_time_model.json")
    assert 100 < m["balls_per_innings"] < 125
    assert m["balls_per_innings"] == pytest.approx(bp.TEAM_BALLS, abs=1.0)
    r = m["replacement"]
    assert r["bat"]["top"] > r["bat"]["tail"] and r["bowl"]["frontline"] > r["bowl"]["part_time"]
    pm = pt.PlayModel.from_json(m["play"])
    regular = {"contrib": 6.0, "in_xi": True, "margin": 3.0, "rank": 2, "overseas": False,
               "os_rank": 0, "ipl_matches": 120, "age": 28.0, "last_share": 1.0, "keeper": False,
               "captain": False, "season": 2027}  # fmt: skip
    bench = {**regular, "contrib": 0.2, "in_xi": False, "margin": -3.0, "rank": 20, "ipl_matches": 3,
             "last_share": 0.0}  # fmt: skip
    assert pm.prob(pt.play_features(regular)) > 0.7 > 0.3 > pm.prob(pt.play_features(bench))
    fm = pt.PlayModel.from_json(m["free_agent"])
    young = {"contrib": 5.0, "margin": 2.0, "ipl_matches": 40, "gap": 0.5, "age": 26.0,
             "last_share": 0.8, "overseas": False, "season": 2027}  # fmt: skip
    veteran = {**young, "age": 42.0, "gap": 2.5, "last_share": None}
    assert fm.prob(pt.fa_features(young)) > 10 * fm.prob(pt.fa_features(veteran))


def test_piece_counts_expected_contribution():
    p = bp.piece("a", "A", 5.0, "all_rounder", False, "", (2.0, 3.0, 12.0, 18.0, 0.5))
    assert p["v"] == pytest.approx(2.5) and p["fb"] == pytest.approx(6.0)
    q = bp.piece("b", "B", 5.0, "batter", False, "", (5.0, 0.0, 20.0, 0.0))  # no P: counts whole
    assert q["v"] == pytest.approx(5.0)
