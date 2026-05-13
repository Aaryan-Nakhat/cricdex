"""CLI: backup / restore the local `data/` directory to Cloudflare R2.

R2 is the cheapest "always free" private object store (10 GB + zero
egress), so it's the safe long-term home for the indexes + tarballs
that we DON'T check in but DO want to survive a VM rebuild.

Bundles (keep them split so partial restores are cheap):

    rules     → data/rules/qdrant + data/rules/parsed + data/rules/curated
    metrics   → data/metrics + data/register
    cricsheet → data/cricsheet/cricsheet.duckdb

Object keys land under:

    s3://<bucket>/backups/<bundle>/cricdex-<bundle>-<YYYYMMDD-HHMMSS>.tar.gz

`restore <bundle>` pulls the latest tarball (or `--stamp 20260513-164100`
to pin a specific one) and untars in-place over `data/`.

Examples:
    uv run python scripts/backup_to_r2.py backup --what all
    uv run python scripts/backup_to_r2.py restore --what rules

Requires R2_* fields populated in `.env` (account id, access key id,
secret access key, bucket name). The script never falls back to the
host's `~/.aws/credentials` — credentials must live in the project
`.env` so personal / work boundaries stay clean.
"""

from __future__ import annotations

import datetime as dt
import subprocess
from pathlib import Path

import typer
from loguru import logger

from cricdex.config import ROOT, settings

BUNDLES: dict[str, list[str]] = {
    "rules": ["data/rules/qdrant", "data/rules/parsed", "data/rules/curated"],
    "metrics": ["data/metrics", "data/register"],
    "cricsheet": ["data/cricsheet"],
}

app = typer.Typer(add_completion=False)


def _client():
    if not settings.r2_account_id or not settings.r2_access_key_id:
        raise typer.BadParameter(
            "R2 credentials missing — fill R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, "
            "R2_SECRET_ACCESS_KEY, R2_BUCKET in .env"
        )
    import boto3
    from botocore.client import Config

    return boto3.client(
        "s3",
        endpoint_url=f"https://{settings.r2_account_id}.r2.cloudflarestorage.com",
        aws_access_key_id=settings.r2_access_key_id,
        aws_secret_access_key=settings.r2_secret_access_key,
        config=Config(signature_version="s3v4"),
        region_name="auto",
    )


@app.command()
def backup(
    what: str = typer.Option("all", "--what", help="rules|metrics|cricsheet|all"),
) -> None:
    targets = list(BUNDLES) if what == "all" else [what]
    if any(t not in BUNDLES for t in targets):
        raise typer.BadParameter(f"unknown bundle. choose from {list(BUNDLES)} or 'all'")
    client = _client()
    stamp = dt.datetime.now(dt.UTC).strftime("%Y%m%d-%H%M%S")
    for name in targets:
        rels = [p for p in BUNDLES[name] if (ROOT / p).exists()]
        if not rels:
            logger.info(f"skip {name}: no data on disk")
            continue
        tar = Path(f"/tmp/cricdex-{name}-{stamp}.tar.gz")
        logger.info(f"tar {rels} → {tar}")
        subprocess.run(
            ["tar", "-czf", str(tar), "-C", str(ROOT), *rels],
            check=True,
        )
        size_mb = tar.stat().st_size / 1024 / 1024
        key = f"backups/{name}/cricdex-{name}-{stamp}.tar.gz"
        logger.info(f"upload {size_mb:.1f} MB → s3://{settings.r2_bucket}/{key}")
        client.upload_file(str(tar), settings.r2_bucket, key)
        tar.unlink()
    logger.info("done")


@app.command()
def restore(
    what: str = typer.Argument(..., help="rules|metrics|cricsheet"),
    stamp: str = typer.Option("latest", "--stamp", help="YYYYMMDD-HHMMSS or 'latest'"),
) -> None:
    if what not in BUNDLES:
        raise typer.BadParameter(f"unknown bundle. choose from {list(BUNDLES)}")
    client = _client()
    prefix = f"backups/{what}/"
    if stamp == "latest":
        resp = client.list_objects_v2(Bucket=settings.r2_bucket, Prefix=prefix)
        contents = resp.get("Contents") or []
        if not contents:
            raise typer.Exit(f"no backups under {prefix}")
        key = sorted(o["Key"] for o in contents)[-1]
    else:
        key = f"{prefix}cricdex-{what}-{stamp}.tar.gz"
    tar = Path(f"/tmp/{Path(key).name}")
    logger.info(f"download s3://{settings.r2_bucket}/{key} → {tar}")
    client.download_file(settings.r2_bucket, key, str(tar))
    logger.info(f"extract {tar} → {ROOT}")
    subprocess.run(["tar", "-xzf", str(tar), "-C", str(ROOT)], check=True)
    tar.unlink()
    logger.info(f"restored {key}")


@app.command(name="ls")
def ls(
    what: str = typer.Argument("all", help="rules|metrics|cricsheet|all"),
) -> None:
    client = _client()
    targets = list(BUNDLES) if what == "all" else [what]
    for name in targets:
        resp = client.list_objects_v2(Bucket=settings.r2_bucket, Prefix=f"backups/{name}/")
        contents = resp.get("Contents") or []
        if not contents:
            typer.echo(f"{name}: (none)")
            continue
        typer.echo(f"{name}:")
        for obj in sorted(contents, key=lambda o: o["Key"]):
            size_mb = obj["Size"] / 1024 / 1024
            typer.echo(f"  {obj['Key']}  {size_mb:7.1f} MB  {obj['LastModified'].isoformat()}")


if __name__ == "__main__":
    app()
