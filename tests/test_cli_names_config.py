"""CLI name lookup, leaderboard sorting and config.toml writing.

Names resolve from the exported players.json, so the JSON-backed commands work on
a fresh clone with no DuckDB (checked in a subprocess with an empty CRICDEX_DATA_DIR).
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tomllib

from typer.testing import CliRunner

from cricdex.cli import _shared, app
from cricdex.cli._shared import load_players, match_player, sort_missing_last

runner = CliRunner(env={"NO_COLOR": "1", "TERM": "dumb", "COLUMNS": "200"})
_ANSI = re.compile(r"\x1b\[[0-9;]*m")

PLAYERS = [
    {"name": "RG Sharma", "full_name": "Rohit Sharma", "cricsheet_id": "a", "matches": 250},
    {"name": "I Sharma", "full_name": "Ishant Sharma", "cricsheet_id": "b", "matches": 110},
    {"name": "JJ Bumrah", "full_name": "Jasprit Bumrah", "cricsheet_id": "c", "matches": 130},
    {"name": "V Kohli", "full_name": "Virat Kohli", "cricsheet_id": "d", "matches": 270},
    {"name": "Kohli Jr", "full_name": None, "cricsheet_id": "e", "matches": 3},
]


def _run(*args, env=None):
    r = runner.invoke(app, list(args), env=env)
    return r.exit_code, _ANSI.sub("", r.output)


def _fresh_clone(tmp_path, *args):
    """Run the CLI in a subprocess whose DATA_DIR is empty (no DuckDB, no metrics)."""
    env = {
        **os.environ,
        "CRICDEX_DATA_DIR": str(tmp_path / "data"),
        "CRICDEX_HOME": str(tmp_path / "home"),
        "NO_COLOR": "1",
        "COLUMNS": "200",
        "PYTHONIOENCODING": "utf-8",
    }
    r = subprocess.run(
        [sys.executable, "-c", "from cricdex.cli import main; main()", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        timeout=180,
    )
    return r.returncode, _ANSI.sub("", r.stdout + r.stderr)


# ---- name matching ------------------------------------------------------------


def test_match_exact_is_case_insensitive_and_takes_full_names():
    assert match_player("jj bumrah", PLAYERS)[0]["cricsheet_id"] == "c"
    assert match_player("Jasprit Bumrah", PLAYERS)[0]["cricsheet_id"] == "c"


def test_exact_beats_a_longer_substring_match():
    # "V Kohli" is exact even though "Kohli Jr" would also contain "kohli"
    assert match_player("v kohli", PLAYERS)[0]["cricsheet_id"] == "d"


def test_unique_prefix_or_substring_resolves():
    assert match_player("Jasp", PLAYERS)[0]["cricsheet_id"] == "c"
    assert match_player("bumr", PLAYERS)[0]["cricsheet_id"] == "c"


def test_ambiguous_names_list_candidates_instead_of_guessing():
    row, candidates = match_player("Sharma", PLAYERS)
    assert row is None
    assert [p["name"] for p in candidates] == ["RG Sharma", "I Sharma"]  # most matches first
    row, candidates = match_player("kohli", PLAYERS)
    assert row is None and len(candidates) == 2


def test_no_match_is_empty():
    assert match_player("Bradman", PLAYERS) == (None, [])
    assert match_player("  ", PLAYERS) == (None, [])


def test_cli_ambiguous_name_lists_players_and_exits_1():
    players = load_players("ipl")
    assert players, "needs the committed site/public/data/ipl/players.json"
    _, candidates = match_player("Sharma", players)
    assert len(candidates) > 1
    code, out = _run("matchups", "Sharma", "-c", "ipl")
    assert code == 1
    assert "matches" in out and candidates[0]["name"] in out
    assert "--name" not in out


def test_cli_unknown_name_has_no_bogus_flag_hint():
    code, out = _run("matchups", "Zzqxv Nobody", "-c", "ipl")
    assert code == 1
    assert "--name" not in out
    assert "spelling" in out or "closest" in out


def test_dead_credential_helpers_are_gone():
    for gone in ("EXIT_MISSING_CRED", "require_cred", "require_path"):
        assert not hasattr(_shared, gone)


# ---- fresh clone (no DuckDB) ----------------------------------------------------


def test_fresh_clone_json_commands_resolve_names_from_players_json(tmp_path):
    code, out = _fresh_clone(tmp_path, "matchups", "Kohli", "-c", "ipl", "--json")
    assert code == 0, out
    assert json.loads(out[out.index("{") :])  # the raw matchups JSON
    code, out = _fresh_clone(tmp_path, "partnerships", "V Kohli", "-c", "ipl", "-n", "3")
    assert code == 0, out
    assert "Partnerships" in out


def test_fresh_clone_profile_says_the_duckdb_is_missing(tmp_path):
    code, out = _fresh_clone(tmp_path, "profile", "V Kohli", "-c", "ipl")
    assert code == 2, out
    assert "DuckDB" in out and "data ingest cricsheet" in out
    assert "spelling" not in out


def test_fresh_clone_without_any_player_list_is_missing_data(tmp_path):
    code, out = _fresh_clone(tmp_path, "matchups", "V Kohli", "-c", "nosuchcoll")
    assert code == 2, out
    assert "players.json" in out and "export_site.py" in out


# ---- leaderboard sorting ---------------------------------------------------------


def test_sort_missing_last_both_directions():
    rows = [{"v": None}, {"v": 2.0}, {"v": float("nan")}, {"v": -1.0}, {"v": 5}, {}]
    hi = sort_missing_last(rows, "v", True)
    lo = sort_missing_last(rows, "v", False)
    assert [r.get("v") for r in hi[:3]] == [5, 2.0, -1.0]
    assert [r.get("v") for r in lo[:3]] == [-1.0, 2.0, 5]
    for out in (hi, lo):
        assert all(r.get("v") is None or r["v"] != r["v"] for r in out[3:])


def test_cli_leaderboard_puts_missing_values_last(tmp_path, monkeypatch):
    import cricdex.cli.metrics_cmd as metrics_cmd

    board = tmp_path / "ipl" / "leaderboards"
    board.mkdir(parents=True)
    # a missing value used to rank as 0, i.e. above real values on some boards
    m = metrics_cmd.METRICS["slow_start_cost"]
    sort_col, name_col = m[0], m[1]
    rows = [
        {name_col: "Has None", sort_col: None},
        {name_col: "Worse", sort_col: 9.0},
        {name_col: "Better", sort_col: -2.0},
    ]
    (board / "slow_start_cost.json").write_text(json.dumps(rows), encoding="utf-8")
    monkeypatch.setattr(metrics_cmd, "SITE_DATA", tmp_path)
    code, out = _run("leaderboard", "slow_start_cost", "-c", "ipl", "--json")
    assert code == 0, out
    best_two = ["Worse", "Better"] if m[2] else ["Better", "Worse"]
    assert [r[name_col] for r in json.loads(out)] == [*best_two, "Has None"]


# ---- config.toml --------------------------------------------------------------------


def test_config_set_escapes_quotes_and_backslashes(tmp_path):
    env = {"CRICDEX_HOME": str(tmp_path)}
    value = 'C:\\Users\\me\\"quoted"\tpath'
    code, out = _run("config", "set", "llm_api_base", value, env=env)
    assert code == 0, out
    cfg = tomllib.loads((tmp_path / "config.toml").read_text(encoding="utf-8"))
    assert cfg["llm_api_base"] == value
    code, out = _run("config", "get", "llm_api_base", env=env)
    assert code == 0 and out.strip() == value
    # a second write round-trips too
    code, _ = _run("config", "set", "llm_model", "x/y", env=env)
    assert code == 0
    cfg = tomllib.loads((tmp_path / "config.toml").read_text(encoding="utf-8"))
    assert cfg == {"llm_api_base": value, "llm_model": "x/y"}


def test_corrupt_config_gives_a_clear_error(tmp_path):
    (tmp_path / "config.toml").write_text('llm_model = "broken\n', encoding="utf-8")
    code, out = _run("config", "get", env={"CRICDEX_HOME": str(tmp_path)})
    assert code == 1
    assert "not valid TOML" in out and "config.toml" in out


def test_corrupt_config_does_not_break_other_commands(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    (home / "config.toml").write_text('llm_api_base = "C:\\bad\\path"\n', encoding="utf-8")
    code, out = _fresh_clone(tmp_path, "leaderboard", "ngi", "-c", "ipl", "-n", "2")
    assert code == 0, out
    assert "not valid TOML" in out  # the warning on stderr names the problem
