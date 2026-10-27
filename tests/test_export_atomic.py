"""The export's swap-in: a finished league replaces the published one whole, a locked folder fails
loudly and leaves the published league in place, and the temp tables go between leagues."""

from __future__ import annotations

import sys
from pathlib import Path

import duckdb
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import export_site as ex  # noqa: E402


def _league(root: Path, tag: str) -> Path:
    (root / "profiles").mkdir(parents=True)
    (root / "meta.json").write_text(tag, encoding="utf-8")
    (root / "profiles" / f"{tag}.json").write_text("{}", encoding="utf-8")
    return root


def test_swap_replaces_the_whole_league(tmp_path):
    pub = _league(tmp_path / "ipl", "old")
    staged = _league(tmp_path / ".staging" / "ipl", "new")
    ex._swap_in(staged, pub)
    assert (pub / "meta.json").read_text(encoding="utf-8") == "new"
    assert not (pub / "profiles" / "old.json").exists()  # no stale file survives
    assert not staged.exists() and not (tmp_path / ".staging" / "ipl.old").exists()


@pytest.mark.skipif(sys.platform != "win32", reason="an open file locks its folder on Windows only")
def test_locked_league_fails_loudly_and_keeps_the_published_one(tmp_path, monkeypatch):
    monkeypatch.setattr(ex, "RENAME_TRIES", 2)
    monkeypatch.setattr(ex, "RENAME_WAIT_S", 0.0)
    pub = _league(tmp_path / "ipl", "old")
    staged = _league(tmp_path / ".staging" / "ipl", "new")
    with (pub / "meta.json").open("rb"), pytest.raises(RuntimeError, match="could not move"):
        ex._swap_in(staged, pub)
    assert (pub / "meta.json").read_text(encoding="utf-8") == "old"


def test_write_atomic_leaves_no_temp_file(tmp_path):
    ex._write_atomic(tmp_path / "collections.json", [{"collection": "ipl"}])
    ex._write_atomic(tmp_path / "collections.json", [{"collection": "psl"}])
    assert (tmp_path / "collections.json").read_text(encoding="utf-8") == '[{"collection":"psl"}]\n'
    assert [p.name for p in tmp_path.iterdir()] == ["collections.json"]


def test_drop_temp_tables_keeps_only_the_named_league():
    con = duckdb.connect()
    for t in ("_keyed_balls_ipl", "_keyed_balls_bbl", "_player_labels_bbl"):
        con.execute(f"CREATE TEMP TABLE {t} AS SELECT 1 AS x")
    ex._drop_temp_tables(con, keep="ipl")
    left = {
        r[0]
        for r in con.execute("SELECT table_name FROM duckdb_tables() WHERE temporary").fetchall()
    }
    assert left == {"_keyed_balls_ipl"}
    ex._drop_temp_tables(con)
    assert not con.execute("SELECT 1 FROM duckdb_tables() WHERE temporary").fetchall()
