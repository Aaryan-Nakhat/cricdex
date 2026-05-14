"""`cricdex config` — read / write the user's CricDex credential store.

Storage: `$CRICDEX_HOME/config.toml` (default `~/.cricdex/config.toml`),
chmod 600. Keys are flat strings — `gemini_api_key`, `jina_api_key`, etc.
"""

from __future__ import annotations

import os
import stat
import tomllib
from pathlib import Path

import typer

from cricdex.cli._shared import EXIT_USER_ERROR, console, die, render_kv

app = typer.Typer(add_completion=False, no_args_is_help=True)


# Whitelist what `cricdex config set` accepts — anything else is a typo
# and we'd rather error than silently write a useless key.
ALLOWED_KEYS = {
    "gemini_api_key",
    "gemini_tmp_url",
    "gemini_tmp_api_key",
    "jina_api_key",
    "qdrant_url",
    "neo4j_uri",
    "neo4j_user",
    "neo4j_password",
}


def _home() -> Path:
    return Path(os.environ.get("CRICDEX_HOME", str(Path.home() / ".cricdex")))


def _config_path() -> Path:
    return _home() / "config.toml"


def _read() -> dict:
    p = _config_path()
    if not p.exists():
        return {}
    with open(p, "rb") as f:
        return tomllib.load(f)


def _write(d: dict) -> None:
    p = _config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# CricDex CLI config — edit by hand or via `cricdex config set`.\n"]
    for k, v in d.items():
        # Simple TOML emit — keys are flat strings.
        lines.append(f'{k} = "{v}"\n')
    p.write_text("".join(lines))
    p.chmod(stat.S_IRUSR | stat.S_IWUSR)  # 600 — credential safety.


@app.command("path", help="Print the config file path.")
def path_cmd() -> None:
    typer.echo(str(_config_path()))


@app.command("get", help="Read a single config key (or list all when no key).")
def get_cmd(key: str = typer.Argument(None)) -> None:
    cfg = _read()
    if not key:
        if not cfg:
            console().print("[dim](empty — run `cricdex config set <key> <value>`)[/dim]")
            return
        masked = {k: ("****" if "key" in k or "password" in k else v) for k, v in cfg.items()}
        render_kv(masked, title=f"config @ {_config_path()}")
        return
    if key not in cfg:
        die(f"no such key: {key}", code=EXIT_USER_ERROR)
    typer.echo(cfg[key])


@app.command("set", help="Set a single config key.")
def set_cmd(
    key: str = typer.Argument(..., help=f"one of: {sorted(ALLOWED_KEYS)}"),
    value: str = typer.Argument(...),
) -> None:
    if key not in ALLOWED_KEYS:
        die(
            f"unknown key `{key}` — allowed: {sorted(ALLOWED_KEYS)}",
            code=EXIT_USER_ERROR,
        )
    cfg = _read()
    cfg[key] = value
    _write(cfg)
    typer.echo(f"wrote {key} to {_config_path()}")


@app.command("unset", help="Remove a single config key.")
def unset_cmd(key: str = typer.Argument(...)) -> None:
    cfg = _read()
    if key not in cfg:
        die(f"no such key: {key}", code=EXIT_USER_ERROR)
    del cfg[key]
    _write(cfg)
    typer.echo(f"removed {key}")


@app.command("edit", help="Open the config in $EDITOR.")
def edit_cmd() -> None:
    import subprocess

    editor = os.environ.get("EDITOR", "nano")
    p = _config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    if not p.exists():
        p.write_text("# CricDex CLI config.\n")
        p.chmod(stat.S_IRUSR | stat.S_IWUSR)
    subprocess.run([editor, str(p)], check=False)
