"""Dependency-free Unicode sparkline — shared by the CLI/TUI (`cli/_render`)
and the Streamlit dashboard so the inline Intent-Curve shape renders identically
on every surface.
"""

from __future__ import annotations

_SPARK_BARS = "▁▂▃▄▅▆▇█"


def sparkline(values: list[float]) -> str:
    """8-glyph Unicode sparkline. Maps the numbers into the 8 block characters
    proportionally; clamps to min/max so a flat line renders as the lowest
    glyph. Non-numeric entries render as a space.
    """
    nums = [v for v in values if isinstance(v, int | float) and not isinstance(v, bool)]
    if not nums:
        return ""
    lo = min(nums)
    hi = max(nums)
    span = (hi - lo) or 1.0
    out: list[str] = []
    for v in values:
        if not isinstance(v, int | float) or isinstance(v, bool):
            out.append(" ")
            continue
        idx = int((v - lo) / span * (len(_SPARK_BARS) - 1))
        out.append(_SPARK_BARS[idx])
    return "".join(out)


__all__ = ["sparkline"]
