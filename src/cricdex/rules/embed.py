"""Embed parsed rule clauses into a local Qdrant collection.

v3: Snowflake/snowflake-arctic-embed-l-v2.0 — multilingual (100+
langs, incl. Hindi/Urdu/Bengali for vernacular rule queries), 8192-
token context, Matryoshka-trained (256-1024 dim) so we truncate to
384 dim with ~96% of full-quality retention. Net: ~2.7× faster
cosine queries + ~2.7× smaller index than the v2 BGE-M3 path, beats
BGE-M3 on MMTEB at release (Nov 2024).

Requires the active HuggingFace credential to be the user's personal account
(`hf auth login` with a personal token). Never falls back to a work token.
"""

from __future__ import annotations

import json
from pathlib import Path

from loguru import logger
from qdrant_client.models import Distance, PointStruct, VectorParams
from sentence_transformers import SentenceTransformer

from cricdex.common.qdrant import get_qdrant_client
from cricdex.config import DATA_DIR

COLLECTION = "rules_clauses"
EMBED_MODEL = "Snowflake/snowflake-arctic-embed-l-v2.0"
EMBED_DIM = 384  # MRL truncation from native 1024


def load_clauses(parsed_dir: Path, curated_dir: Path | None = None) -> list[dict]:
    """Merge auto-parsed JSONL with curated supplementary JSONL.

    Curated JSONL fills publisher gaps where the authoritative rule lives in
    a non-PDF source (announcement page, separate Player Regulations doc that
    is not publicly hosted, etc). Curated files follow the same per-line
    schema as parser output: source_id, edition, page, law_number,
    parent_chain, title, text.
    """
    rows: list[dict] = []
    for fp in sorted(parsed_dir.glob("*.jsonl")):
        with open(fp) as f:
            for line in f:
                rows.append(json.loads(line))
    curated_dir = curated_dir or (parsed_dir.parent / "curated")
    if curated_dir.exists():
        for fp in sorted(curated_dir.glob("*.jsonl")):
            with open(fp) as f:
                for line in f:
                    rows.append(json.loads(line))
    return rows


def embed_all(parsed_dir: Path | None = None, qdrant_path: Path | None = None) -> int:
    parsed_dir = parsed_dir or (DATA_DIR / "rules" / "parsed")
    clauses = load_clauses(parsed_dir)
    if not clauses:
        logger.warning(f"no clause files in {parsed_dir}")
        return 0
    logger.info(f"embedding {len(clauses)} clauses with {EMBED_MODEL}")

    model = SentenceTransformer(EMBED_MODEL, trust_remote_code=True, truncate_dim=EMBED_DIM)
    client = get_qdrant_client(local_path=qdrant_path)

    if client.collection_exists(COLLECTION):
        client.delete_collection(COLLECTION)
    client.create_collection(
        collection_name=COLLECTION,
        vectors_config=VectorParams(size=EMBED_DIM, distance=Distance.COSINE),
    )

    texts = [f"{c['title']}\n\n{c['text']}" for c in clauses]
    vectors = model.encode(
        texts,
        batch_size=64,
        show_progress_bar=True,
        normalize_embeddings=True,
    )

    points = [
        PointStruct(id=i, vector=vec.tolist(), payload=clauses[i]) for i, vec in enumerate(vectors)
    ]
    # Chunked upsert so we never hold a single multi-MB request open longer
    # than the server's idle window, especially under the Compose bridge.
    batch_size = 1024
    for start in range(0, len(points), batch_size):
        chunk = points[start : start + batch_size]
        client.upsert(collection_name=COLLECTION, points=chunk, wait=True)
    logger.info(f"upserted {len(points)} → {COLLECTION}")
    return len(points)
