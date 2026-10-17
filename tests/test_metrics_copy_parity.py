"""The metric explainer copy is written twice (web `metrics.ts`, Python `common/metrics.py`); keep them word for word."""

from __future__ import annotations

import json
from pathlib import Path

from cricdex.common.metrics import METRICS

TS = Path(__file__).resolve().parents[1] / "site" / "src" / "lib" / "metrics.ts"


def test_metric_copy_matches_the_web_app():
    ts = TS.read_text(encoding="utf-8")
    for m in METRICS:
        assert f'slug: "{m.slug}"' in ts, m.slug
        for field in ("name", "one_liner", "what", "how", "read", "good", "direction"):
            text = getattr(m, field)
            assert f"{field}: {json.dumps(text, ensure_ascii=False)}" in ts, (m.slug, field)
        for c in m.columns:
            assert f'key: "{c.key}", label: {json.dumps(c.label, ensure_ascii=False)}' in ts, (
                m.slug,
                c.key,
            )
