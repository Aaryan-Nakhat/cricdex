"""Download cricket rulebook PDFs into a local cache directory.

Skips entries with empty URLs (un-verified manifest rows).
"""

from __future__ import annotations

from pathlib import Path

import httpx
from loguru import logger
from tqdm import tqdm

from cricdex.rules.manifest import SOURCES, RuleSource


def download_pdf(source: RuleSource, dest: Path, force: bool = False) -> Path | None:
    if not source.url:
        logger.warning(f"skip {source.id}: empty url (verify + fill manifest)")
        return None
    dest.mkdir(parents=True, exist_ok=True)
    out = dest / f"{source.id}.pdf"
    if out.exists() and not force:
        logger.info(f"cached: {out}")
        return out

    logger.info(f"downloading {source.id} from {source.url}")
    try:
        with httpx.stream("GET", source.url, timeout=120.0, follow_redirects=True) as r:
            r.raise_for_status()
            total = int(r.headers.get("content-length", 0))
            with open(out, "wb") as f, tqdm(total=total, unit="B", unit_scale=True) as bar:
                for chunk in r.iter_bytes(chunk_size=1 << 16):
                    f.write(chunk)
                    bar.update(len(chunk))
    except httpx.HTTPError as e:
        logger.error(f"download failed for {source.id}: {e}")
        if out.exists():
            out.unlink()
        return None
    return out


def download_all(dest: Path, force: bool = False) -> list[Path]:
    paths: list[Path] = []
    for src in SOURCES:
        p = download_pdf(src, dest, force=force)
        if p is not None:
            paths.append(p)
    return paths
