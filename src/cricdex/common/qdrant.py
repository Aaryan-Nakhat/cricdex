"""Single source of truth for Qdrant client construction.

If `QDRANT_URL` is set we hit a real server (Qdrant Cloud or the local
`docker compose` service). Otherwise we fall back to embedded on-disk
storage so a developer without any external services can still embed +
query locally.
"""

from __future__ import annotations

from pathlib import Path

from qdrant_client import QdrantClient

from cricdex.config import DATA_DIR, settings


def get_qdrant_client(local_path: Path | None = None) -> QdrantClient:
    if settings.qdrant_url:
        return QdrantClient(
            url=settings.qdrant_url,
            prefer_grpc=False,
            timeout=300,
        )
    path = local_path or (DATA_DIR / "rules" / "qdrant")
    path.mkdir(parents=True, exist_ok=True)
    return QdrantClient(path=str(path))
