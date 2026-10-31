"""Style twins (roadmap 25 / I12): same role, same bowling category, never yourself, and players a fan
would call alike rank above players who clearly aren't."""

from __future__ import annotations

import duckdb
import polars as pl
import pytest

from cricdesk.scout.search import style_twin as st

# Batting runs per ball, cycled: how each kind of batter scores.
PATTERNS = {
    "hitter_open": [4, 1, 6, 0, 1, 4, 2, 4],  # aggressive opener
    "anchor_open": [0, 1, 0, 1, 2, 0, 1, 4],  # slow opener
    "middle": [1, 1, 0, 2, 4, 1, 1, 0],
    "finisher": [6, 0, 4, 6, 1, 0, 6, 1],
}
# innings 0 / innings 1 batting order: (opening pair, middle pair, finishing pair)
LINEUPS = (
    (("O1", "A1"), ("M1", "M2"), ("F1", "F2")),
    (("O2", "A2"), ("M3", "M4"), ("F3", "F4")),
)
KIND = {
    **dict.fromkeys(("O1", "O2"), "hitter_open"),
    **dict.fromkeys(("A1", "A2"), "anchor_open"),
    **dict.fromkeys(("M1", "M2", "M3", "M4"), "middle"),
    **dict.fromkeys(("F1", "F2", "F3", "F4"), "finisher"),
}
# O1 and O2 open with the same tempo but differ a little, so they are each other's closest twin
NUDGE = {"O2": [4, 1, 6, 0, 2, 4, 1, 4]}
# who bowls each over: seamers up front and at the death, spinners (and a middle-overs medium-pacer)
# in the middle; PT is a part-timer under the evidence bar
BOWLERS = {o: ("S1" if o % 2 == 0 else "S2") for o in (*range(6), *range(16, 20))}
BOWLERS.update({6: "W1", 7: "W2", 8: "FS", 9: "SM", 10: "W1", 11: "W2", 12: "FS", 13: "SM"})
BOWLERS.update({14: "W1", 15: "W2"})
STYLES = {
    "S1": "right-arm-fast",
    "S2": "right-arm-fast",
    "SM": "right-arm-medium",
    "W1": "leg-spin",
    "W2": "leg-spin",
    "FS": "off-spin",
    "PT": "off-spin",
}
N_MATCHES = 14


def _phase(over: int) -> str:
    return "powerplay" if over < 6 else ("middle" if over < 16 else "death")


def _make_db(path) -> None:
    rows = []
    for m in range(N_MATCHES):
        for inn, lineup in enumerate(LINEUPS):
            stints = (
                (range(0, 6), lineup[0]),
                (range(6, 16), lineup[1]),
                (range(16, 20), lineup[2]),
            )
            n = 0
            for overs, pair in stints:
                for over in overs:
                    bowler = BOWLERS[over]
                    if (
                        m // 2
                    ) % 2:  # the two quicks swap ends, so neither always gets the wicket overs
                        bowler = {"S1": "S2", "S2": "S1"}.get(bowler, bowler)
                    if m == 0 and over == 13:
                        bowler = "PT"  # one over in one match: far under the evidence bar
                    for ball in range(1, 7):
                        striker = pair[n % 2]
                        other = pair[(n + 1) % 2]
                        pat = NUDGE.get(striker) or PATTERNS[KIND[striker]]
                        runs = pat[(n // 2 + m) % len(pat)]
                        last = over == overs[-1] and ball == 6
                        out = striker if (last and m % 2 == 0) else None
                        rows.append(
                            (
                                f"m{m}",
                                f"2024-04-{m + 1:02d}",
                                inn,
                                over,
                                ball,
                                _phase(over),
                                striker,
                                other,
                                bowler,
                                0 if out else runs,
                                "caught" if out else None,
                                out,
                            )
                        )
                        n += 1
    con = duckdb.connect(str(path))
    con.execute(
        "CREATE TABLE balls_t (match_id VARCHAR, match_date VARCHAR, innings_idx BIGINT, over BIGINT,"
        " ball_in_over BIGINT, phase VARCHAR, batter VARCHAR, non_striker VARCHAR, bowler VARCHAR,"
        " runs_batter BIGINT, wicket_kind VARCHAR, player_out VARCHAR, runs_extras BIGINT DEFAULT 0,"
        " extras_type VARCHAR DEFAULT NULL, runs_non_boundary BOOLEAN DEFAULT FALSE,"
        " match_type VARCHAR DEFAULT 'T20')"
    )
    con.executemany(
        "INSERT INTO balls_t (match_id, match_date, innings_idx, over, ball_in_over, phase, batter,"
        " non_striker, bowler, runs_batter, wicket_kind, player_out) VALUES"
        " (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    names = sorted({r[6] for r in rows} | {r[8] for r in rows})
    con.execute("CREATE TABLE people (identifier VARCHAR, unique_name VARCHAR)")
    con.executemany("INSERT INTO people VALUES (?, ?)", [(n.lower(), n) for n in names])
    con.close()


@pytest.fixture
def twins(tmp_path, monkeypatch):
    def styles() -> pl.DataFrame:
        rows = []
        for name, style in STYLES.items():
            family = "wrist" if style in st.WRIST else "finger" if style in st.FINGER else "seam"
            rows.append(
                {
                    "pid": name.lower(),
                    "family": family,
                    "pace": st.PACE_LEVEL.get(style),
                    "left_arm": 0.0,
                    "left_hand": 0.0,
                }
            )
        return pl.DataFrame(rows)

    monkeypatch.setattr(st, "_styles", styles)
    db = tmp_path / "twins.duckdb"
    _make_db(db)
    return {role: st.TwinIndex(role, collection="t", db_path=db) for role in ("batter", "bowler")}


def _names(df: pl.DataFrame) -> list[str]:
    return df["name"].to_list()


def test_no_player_is_his_own_twin(twins):
    for role, idx in twins.items():
        assert idx.names, role
        for pid in idx.names:
            got = idx.query(pid, k=20)
            assert pid not in (got["cricsheet_id"].to_list() if not got.is_empty() else [])


def test_similar_openers_rank_above_clearly_different_batters(twins):
    got = _names(twins["batter"].query("O1", k=10))
    assert got[0] == "O2"  # the other aggressive opener
    assert got.index("O2") < got.index("A1")  # ...ahead of the slow opener
    # openers' twins are openers first: every finisher ranks below every opener
    assert max(got.index(p) for p in ("O2", "A1", "A2")) < min(
        got.index(p) for p in ("F1", "F2", "F3", "F4") if p in got
    )
    fin = _names(twins["batter"].query("F1", k=4))
    assert set(fin[:3]) <= {"F2", "F3", "F4"}


def test_bowler_twins_keep_the_bowling_category(twins):
    idx = twins["bowler"]
    # a leg-spinner: the other wrist spinner first, then the finger spinner; never a seamer, not
    # even the medium-pacer who bowls the same middle overs
    w1 = _names(idx.query("W1", k=10))
    assert w1 == ["W2", "FS"]
    seam = _names(idx.query("SM", k=10))
    assert set(seam) == {"S1", "S2"}
    s1 = _names(idx.query("S1", k=10))
    assert s1[0] == "S2"  # same phases, same pace
    assert "PT" not in idx.names  # a part-timer is under the evidence bar


def test_alike_is_a_percentage_and_distance_its_complement(twins):
    got = twins["batter"].query("O1", k=10)
    alike = got["alike"].to_list()
    assert all(0 <= a <= 100 for a in alike)
    for a, d in zip(alike, got["distance"].to_list(), strict=True):
        assert abs((1 - d) * 100 - a) < 0.1
    openers = got.filter(pl.col("name").is_in(["O2", "A1", "A2"]))["alike"].to_list()
    assert openers == sorted(openers, reverse=True)  # closest first within a tier


def test_unknown_player_raises_keyerror(twins):
    with pytest.raises(KeyError):
        twins["batter"].query("Nobody")
