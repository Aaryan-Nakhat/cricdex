"""Repo-wide pytest hooks.

On GitHub Actions, each failing test is also printed as a workflow `::error` annotation, so the failure (file,
test name and the last lines of the error) shows on the run's summary page without opening the raw log."""

from __future__ import annotations

import os


def pytest_runtest_logreport(report):
    if not os.environ.get("GITHUB_ACTIONS") or not report.failed:
        return
    path = report.location[0] if report.location else ""
    line = (
        (report.location[1] or 0) + 1 if report.location and report.location[1] is not None else 1
    )
    text = str(report.longrepr or "")
    tail = " | ".join(t.strip() for t in text.strip().splitlines()[-6:] if t.strip())
    # annotations are one line; escape the characters the workflow-command format reserves
    msg = (
        f"{report.nodeid} ({report.when}): {tail}"[:1800]
        .replace("%", "%25")
        .replace("\r", "")
        .replace("\n", " ")
    )
    print(f"\n::error file={path},line={line},title=pytest failure::{msg}")
