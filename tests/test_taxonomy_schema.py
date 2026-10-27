"""The LLM taxonomy and name-check answers are checked against allow-lists (no LLM is called)."""

from __future__ import annotations

import json

from cricdex.scout.identity import taxonomy


def test_good_record_kept_and_country_normalised():
    rec = taxonomy.clean_record(
        {
            "name": "V Kohli",
            "full_name": "Virat Kohli",
            "primary_role": "batter",
            "bowling_category": "none",
            "bowling_style": "none",
            "batting_position": "no3",
            "batting_hand": "Right",
            "country": "India",
            "confidence": "high",
        },
        cid="ba607b88",
    )
    assert rec["primary_role"] == "batter"
    assert rec["batting_hand"] == "right"
    assert rec["batting_position"] == "no3"
    assert rec["country"] == "IND"
    assert rec["source"] == "llm"


def test_bad_values_dropped():
    rec = taxonomy.clean_record(
        {
            "name": "<script>alert(1)</script>",
            "full_name": "x" * 500,
            "primary_role": "captain; DROP TABLE",
            "bowling_category": "seam",
            "bowling_style": "underarm",
            "batting_position": 3,
            "batting_hand": ["left"],
            "country": "Atlantis",
            "confidence": "certain",
            "source": "web",
            "extra_field": "ignored",
        },
        cid="deadbeef",
    )
    for field in (
        "name",
        "full_name",
        "primary_role",
        "bowling_style",
        "batting_position",
        "batting_hand",
        "country",
        "confidence",
    ):
        assert rec[field] is None, field
    assert rec["bowling_category"] == "seam"
    assert rec["source"] == "llm"
    assert "extra_field" not in rec


def test_style_without_bowling_dropped():
    rec = taxonomy.clean_record({"bowling_category": "none", "bowling_style": "off-spin"})
    assert rec["bowling_style"] is None


def test_country_aliases_and_unknown():
    assert taxonomy.clean_country("RSA") == "ZAF"
    assert taxonomy.clean_country("GB-SCT") == "SCO"
    assert taxonomy.clean_country("unknown") is None
    assert taxonomy.clean_country("ZZZ") is None  # three letters but not a listed code
    assert taxonomy.clean_country(42) is None


def test_whole_file_skips_bad_ids_and_records(tmp_path):
    path = tmp_path / "player_taxonomy.json"
    path.write_text(
        json.dumps(
            {
                "ba607b88": {"primary_role": "bowler", "country": "AUS"},
                "../../etc": {"primary_role": "bowler"},
                "abc12345": "not a record",
            }
        ),
        encoding="utf-8",
    )
    out = taxonomy.load_taxonomy(path)
    assert set(out) == {"ba607b88"}
    assert out["ba607b88"]["country"] == "AUS"
    assert taxonomy.load_taxonomy(tmp_path / "missing.json") == {}


def test_name_answers_checked(tmp_path):
    path = tmp_path / "player_names_llm.json"
    path.write_text(
        json.dumps(
            {
                "ba607b88": {
                    "candidate": "V Kohli",
                    "display_name": "  Virat   Kohli ",
                    "verdict": "corrected",
                    "confidence": "high",
                },
                "deadbeef": {"candidate": "A B", "display_name": "x" * 200, "verdict": "corrected"},
                "cafe0001": {"candidate": "C D", "display_name": "C D", "verdict": "maybe"},
            }
        ),
        encoding="utf-8",
    )
    out = taxonomy.load_names(path)
    assert out["ba607b88"]["display_name"] == "Virat Kohli"
    assert "deadbeef" not in out  # an unbounded name is no answer at all
    assert out["cafe0001"]["verdict"] is None
