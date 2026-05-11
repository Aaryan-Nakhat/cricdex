"""Download cricket rulebook PDFs into a local cache directory.

Skips entries with empty URLs (un-verified manifest rows). Validates the
fetched bytes start with the PDF magic header to catch sites that serve a
SPA shell instead of the real file.
"""

from __future__ import annotations

from pathlib import Path

import httpx
from loguru import logger
from tqdm import tqdm

from cricdex.rules.manifest import SOURCES, RuleSource

PDF_MAGIC = b"%PDF"
BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "application/pdf,*/*;q=0.8",
}


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
        with httpx.stream(
            "GET",
            source.url,
            timeout=120.0,
            follow_redirects=True,
            headers=BROWSER_HEADERS,
        ) as r:
            r.raise_for_status()
            total = int(r.headers.get("content-length", 0))
            first_chunk = True
            with open(out, "wb") as f, tqdm(total=total, unit="B", unit_scale=True) as bar:
                for chunk in r.iter_bytes(chunk_size=1 << 16):
                    if first_chunk:
                        if not chunk.startswith(PDF_MAGIC):
                            raise RuntimeError(
                                "response is not a PDF (missing %PDF magic) — "
                                f"first bytes: {chunk[:32]!r}"
                            )
                        first_chunk = False
                    f.write(chunk)
                    bar.update(len(chunk))
    except (httpx.HTTPError, RuntimeError) as e:
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
