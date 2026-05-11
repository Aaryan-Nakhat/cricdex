from cricdex.scout.ingest.cricsheet import _phase


def test_phase_t20():
    assert _phase(0, 20) == "powerplay"
    assert _phase(5, 20) == "powerplay"
    assert _phase(8, 20) == "middle"
    assert _phase(16, 20) == "death"


def test_phase_odi():
    assert _phase(0, 50) == "powerplay"
    assert _phase(25, 50) == "middle"
    assert _phase(45, 50) == "death"


def test_phase_test_fallback():
    assert _phase(50, None, "Test") == "test"
    assert _phase(0, None, "MDM") == "test"
    assert _phase(0, None, "ODI") == "powerplay"
    assert _phase(0, None) == "powerplay"
