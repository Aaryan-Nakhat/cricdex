"""Unit tests for the dismissal fingerprint (batter / bowler / matchup)."""

from __future__ import annotations

import duckdb
import pytest

from cricdex.metrics import dismissal_fingerprint as df


@pytest.fixture
def mini_db(tmp_path):
    """A tiny balls table: A gets out 3 ways, B (bowler) takes the wickets."""
    path = tmp_path / "mini.duckdb"
    con = duckdb.connect(str(path))
    con.execute(
        """
        CREATE TABLE balls_test (
            batter TEXT, bowler TEXT, player_out TEXT,
            wicket_kind TEXT, extras_type TEXT
        )
        """
    )
    con.executemany(
        "INSERT INTO balls_test VALUES (?,?,?,?,?)",
        [
            # A caught by B ×3, bowled by B ×1, run out ×1 (not bowler-credited)
            ("A", "B", "A", "caught", None),
            ("A", "B", "A", "caught", None),
            ("A", "B", "A", "caught", None),
            ("A", "B", "A", "bowled", None),
            ("A", "C", "A", "run out", None),
            # plain balls faced (no wicket) to make the balls count meaningful
            ("A", "B", None, None, None),
            ("A", "B", None, None, "wides"),  # wide — excluded from balls
        ],
    )
    con.close()
    return path


def test_batter_modes_includes_run_out(mini_db):
    out = df.batter_modes("A", collection="test", db_path=mini_db)
    kinds = {r["kind"]: r["count"] for r in out["rows"]}
    assert out["total"] == 5  # 3 caught + 1 bowled + 1 run out
    assert kinds["caught"] == 3
    assert kinds["run out"] == 1  # batters DO count run-outs
    # caught is 60% → "false / aerial shots" read
    assert "false" in out["read"] or "aerial" in out["read"]


def test_bowler_modes_excludes_run_out(mini_db):
    out = df.bowler_modes("B", collection="test", db_path=mini_db)
    kinds = {r["kind"]: r["count"] for r in out["rows"]}
    assert out["total"] == 4  # 3 caught + 1 bowled — run out NOT credited to B
    assert "run out" not in kinds
    assert kinds["caught"] == 3


def test_bowler_modes_run_out_not_credited(mini_db):
    # C only has a run-out → no bowler-credited wickets.
    out = df.bowler_modes("C", collection="test", db_path=mini_db)
    assert out["total"] == 0


def test_matchup_log_counts_and_balls(mini_db):
    log = df.matchup_log("A", "B", collection="test", db_path=mini_db)
    assert log["total"] == 4  # B dismissed A 4× (3 caught + 1 bowled)
    # A-vs-B rows: 3 caught + 1 bowled + 1 no-wicket + 1 wide → 5 legal
    # (the run-out row is A-vs-C, the wide is excluded).
    assert log["balls"] == 5
    kinds = {r["kind"]: r["count"] for r in log["rows"]}
    assert kinds["caught"] == 3
    assert kinds["bowled"] == 1


def test_missing_table_graceful(tmp_path):
    empty = tmp_path / "empty.duckdb"
    duckdb.connect(str(empty)).close()
    assert df.batter_modes("X", collection="test", db_path=empty)["total"] == 0
    assert df.matchup_log("X", "Y", collection="test", db_path=empty)["total"] == 0
