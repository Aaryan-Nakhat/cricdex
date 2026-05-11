from cricdex.rules.qa import FORMAT_TO_SOURCE_IDS, resolve_formats
from cricdex.rules.retrieval import rrf_fuse


def test_resolve_formats_known():
    assert resolve_formats(["ipl"]) == ["ipl_pc_2026", "ipl_impact_player_2025_27"]
    assert resolve_formats(["odi"]) == ["icc_pc_men_odi_2025"]
    assert resolve_formats(["test"]) == [
        "icc_pc_men_test_2025",
        "icc_wtc_2025_2027",
    ]


def test_resolve_formats_empty():
    assert resolve_formats(None) is None
    assert resolve_formats([]) is None
    assert resolve_formats(["unknown_format"]) is None


def test_resolve_formats_combined():
    out = resolve_formats(["t20i", "ipl"])
    assert "icc_pc_men_t20i_2025" in out
    assert "ipl_pc_2026" in out
    assert "ipl_impact_player_2025_27" in out


def test_format_map_covers_all_known_sources():
    assert "mcc_laws_2017_4th_2026" in FORMAT_TO_SOURCE_IDS["mcc_laws"]
    assert "icc_anti_corruption_2024" in FORMAT_TO_SOURCE_IDS["anti_corruption"]


def test_rrf_fuse_orders_correctly():
    dense = [
        (0.9, {"source_id": "a", "law_number": "1", "page": 1}),
        (0.7, {"source_id": "b", "law_number": "2", "page": 1}),
    ]
    sparse = [
        (4.0, {"source_id": "b", "law_number": "2", "page": 1}),
        (1.0, {"source_id": "c", "law_number": "3", "page": 1}),
    ]
    fused = rrf_fuse(dense, sparse, top_k=3)
    keys = [(p["source_id"], p["law_number"]) for _, p in fused]
    assert keys[0] == ("b", "2"), "shared hit should rank first via RRF"
    assert ("a", "1") in keys
    assert ("c", "3") in keys
