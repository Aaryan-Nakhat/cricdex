from cricdex.rules.manifest import SOURCES, RuleSource
from cricdex.rules.parse import _split_clauses


def _src() -> RuleSource:
    return RuleSource(
        id="dummy",
        title="x",
        organization="MCC",
        tier="laws",
        url="",
        edition="v1",
    )


def test_split_clauses_basic():
    text = "21 No ball\nWhen the bowler oversteps...\n21.1 Definition\nA delivery is...\n"
    out = _split_clauses(text, page_num=1, source=_src())
    assert len(out) == 2
    assert out[0].law_number == "21"
    assert out[1].law_number == "21.1"
    assert "oversteps" in out[0].text
    assert out[1].parent_chain == ["21", "21.1"]


def test_manifest_has_sources():
    assert len(SOURCES) >= 15
    for s in SOURCES:
        assert s.id
        assert s.title
        assert s.organization
        assert s.tier
