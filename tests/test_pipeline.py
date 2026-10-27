"""The pipeline's step list and its resume / --from / --only / --refit rules (no step really runs)."""

from __future__ import annotations

import pytest

from cricdex import pipeline


@pytest.fixture
def ran(monkeypatch, tmp_path):
    calls: list[list[str]] = []
    fail: set[str] = set()

    def fake_run(argv, log):
        calls.append(argv[1:])
        return 1 if any(a in fail for a in argv) else 0

    monkeypatch.setattr(pipeline, "_run", fake_run)
    monkeypatch.setenv("CRICDEX_REBUILD_STATE", str(tmp_path / "state"))
    monkeypatch.setenv("CRICDEX_REBUILD_LOG", str(tmp_path / "rebuild.log"))
    monkeypatch.setenv("LEAGUES", "ipl psl")
    return calls, fail, tmp_path / "state"


def _scripts(calls):
    return [c[0].removeprefix("scripts/") for c in calls]


def test_order_and_refit_flags():
    names = [s.name for s in pipeline.STEPS]
    assert names.index("people") < names.index("master") < names.index("ratings")
    assert names.index("ratings") < names.index("metrics") < names.index("forecast")
    assert names[-1] == "export"
    refits = {s.name for s in pipeline.STEPS if s.refit}
    assert refits == {"translation", "drift", "shrink", "playing_time", "price", "keep"}


def test_default_run_skips_refits_and_resumes(ran):
    calls, fail, state = ran
    fail.add("build")  # the forecast build fails
    assert pipeline.main([]) == 1
    scripts = _scripts(calls)
    assert scripts.count("ingest_cricsheet.py") == 2 and "export_site.py" not in scripts
    assert not any(s.endswith("_fit.py") or s.startswith(("ipl_price", "keep_")) for s in scripts)
    assert (state / "metrics_psl").exists() and not (state / "forecast").exists()
    calls.clear()
    fail.clear()
    assert pipeline.main([]) == 0
    # resumed at the forecast: the fits again (cached by the script itself), build, export
    assert _scripts(calls) == ["form_forecast.py", "form_forecast.py", "export_site.py"]
    assert (state / "READY").exists()


def test_from_marks_earlier_steps_done(ran):
    calls, _, state = ran
    assert pipeline.main(["--from", "ratings"]) == 0
    assert "ingest_cricsheet.py" not in _scripts(calls)
    assert (state / "ingest_ipl").exists() and (state / "people").exists()
    calls.clear()
    assert pipeline.main([]) == 0
    assert calls == []  # everything is done


def test_refit_steps_only_on_request(ran):
    calls, _, _ = ran
    with pytest.raises(SystemExit):
        pipeline.main(["--from", "drift"])
    assert pipeline.main(["--only", "drift"]) == 0
    assert [c[1] for c in calls] == ["obs", "validate", "test", "ship"]
    with pytest.raises(SystemExit):
        pipeline.main(["--only", "nope"])
