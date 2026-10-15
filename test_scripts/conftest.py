"""The parity tests skip on a machine without Node or the exported JSON. In CI (GitHub sets CI=true) a skip would
hide drift between the web and Python ports, so there it fails instead."""

from __future__ import annotations

import os

import pytest


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    if (
        os.environ.get("CI")
        and report.skipped
        and item.fspath.basename.startswith("test_")
        and call.when in ("setup", "call")
    ):
        report.outcome = "failed"
        report.longrepr = f"parity test skipped in CI (Node or data missing): {report.longrepr}"
