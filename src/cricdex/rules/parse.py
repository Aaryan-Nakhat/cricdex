"""Parse cricket rulebook PDFs into clause-hierarchy records.

v1 uses pdfplumber + a regex-based clause splitter. Real PDFs need
per-source tuning; promote to Marker / layout-aware parser if retrieval
quality stalls.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from pathlib import Path

import pdfplumber
from loguru import logger

from cricdex.rules.manifest import SOURCES, RuleSource

CLAUSE_RE = re.compile(r"^(\s*)((?:Law\s+)?\d+(?:\.\d+)*)\s+([A-Z][^\n]{0,80})")


@dataclass(slots=True)
class Clause:
    source_id: str
    edition: str
    page: int
    law_number: str
    parent_chain: list[str]
    title: str
    text: str


def _split_clauses(page_text: str, page_num: int, source: RuleSource) -> list[Clause]:
    out: list[Clause] = []
    current: Clause | None = None
    parent_chain: list[str] = []

    for raw_line in page_text.splitlines():
        line = raw_line.rstrip()
        m = CLAUSE_RE.match(line)
        if m:
            if current and current.text:
                out.append(current)
            num = m.group(2).replace("Law ", "")
            title = m.group(3).strip()
            depth = num.count(".")
            parent_chain = parent_chain[:depth]
            parent_chain.append(num)
            current = Clause(
                source_id=source.id,
                edition=source.edition,
                page=page_num,
                law_number=num,
                parent_chain=parent_chain.copy(),
                title=title,
                text="",
            )
        elif current is not None and line.strip():
            current.text = (current.text + " " + line.strip()).strip()

    if current and current.text:
        out.append(current)
    return out


def parse_pdf(pdf_path: Path, source: RuleSource) -> list[Clause]:
    clauses: list[Clause] = []
    with pdfplumber.open(pdf_path) as pdf:
        for i, page in enumerate(pdf.pages, start=1):
            text = page.extract_text() or ""
            clauses.extend(_split_clauses(text, i, source))
    logger.info(f"{source.id}: {len(clauses)} clauses extracted")
    return clauses


def parse_all(pdf_dir: Path) -> dict[str, list[Clause]]:
    out: dict[str, list[Clause]] = {}
    for src in SOURCES:
        pdf_path = pdf_dir / f"{src.id}.pdf"
        if not pdf_path.exists():
            continue
        out[src.id] = parse_pdf(pdf_path, src)
    return out


def to_records(clauses: list[Clause]) -> list[dict]:
    return [asdict(c) for c in clauses]
