"""Smoke test for the People-Register loader.

Hand-rolls two tiny CSVs that mirror the real register schema and
checks the loader hydrates two DuckDB tables with the expected
identifier mapping. Avoids any network dependency.
"""

from __future__ import annotations

import duckdb

from cricdex.scout.ingest.people_register import load


def _write_people_csv(path) -> None:
    path.write_text(
        "identifier,name,unique_name,key_bcci,key_bcci_2,key_bigbash,key_cricbuzz,"
        "key_cricheroes,key_crichq,key_cricinfo,key_cricinfo_2,key_cricinfo_3,"
        "key_cricingif,key_cricketarchive,key_cricketarchive_2,key_cricketworld,"
        "key_nvplay,key_nvplay_2,key_opta,key_opta_2,key_pulse,key_pulse_2\n"
        "abc123,Virat Kohli,V Kohli,,,,,,,253802,,,,,,,,,,,,\n"
        "def456,Jasprit Bumrah,J Bumrah,,,,,,,625371,,,,,,,,,,,,\n"
    )


def _write_names_csv(path) -> None:
    path.write_text("identifier,name\nabc123,Virat\nabc123,V. Kohli\ndef456,Bumrah\n")


def test_load_creates_both_tables(tmp_path):
    people_csv = tmp_path / "people.csv"
    names_csv = tmp_path / "people_names.csv"
    _write_people_csv(people_csv)
    _write_names_csv(names_csv)

    db_path = tmp_path / "test.duckdb"
    n_people, n_names = load(people_csv, names_csv, db_path=db_path)
    assert n_people == 2
    assert n_names == 3

    con = duckdb.connect(str(db_path), read_only=True)
    try:
        kohli = con.execute(
            "SELECT key_cricinfo FROM people WHERE unique_name = 'V Kohli'"
        ).fetchone()
        assert kohli is not None
        assert kohli[0] == 253802

        variants = con.execute(
            "SELECT name FROM people_names WHERE identifier = 'abc123' ORDER BY name"
        ).fetchall()
        assert [v[0] for v in variants] == ["V. Kohli", "Virat"]
    finally:
        con.close()
