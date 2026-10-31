"""`cricdesk config` — read / write the user's CricDesk credential store.

Storage: `$CRICDESK_HOME/config.toml` (default `~/.cricdesk/config.toml`),
chmod 600. Keys are flat strings — `llm_model`, `llm_api_key`, `llm_api_base`.
"""

from __future__ import annotations

import os
import re
import stat
import tomllib
from pathlib import Path

import typer

from cricdesk.cli._shared import EXIT_USER_ERROR, console, die, render_kv

app = typer.Typer(add_completion=False, no_args_is_help=True)


# Whitelist what `cricdesk config set` accepts — anything else is a typo
# and we'd rather error than silently write a useless key.
ALLOWED_KEYS = {
    "llm_model",
    "llm_api_key",
    "llm_api_base",
}


def _home() -> Path:
    return Path(os.environ.get("CRICDESK_HOME", str(Path.home() / ".cricdesk")))


def _config_path() -> Path:
    return _home() / "config.toml"


def _read() -> dict:
    p = _config_path()
    if not p.exists():
        return {}
    try:
        with open(p, "rb") as f:
            return tomllib.load(f)
    except tomllib.TOMLDecodeError as e:
        die(
            f"{p} is not valid TOML ({e})",
            code=EXIT_USER_ERROR,
            hint="fix it with `cricdesk config edit`, or delete the file and `config set` again",
        )


_TOML_ESCAPES = {
    '"': '\\"',
    "\\": "\\\\",
    "\b": "\\b",
    "\t": "\\t",
    "\n": "\\n",
    "\f": "\\f",
    "\r": "\\r",
}
_BARE_KEY = re.compile(r"[A-Za-z0-9_-]+")


def _toml_str(s: str) -> str:
    """A TOML basic string: quotes, backslashes and control characters escaped."""
    out = []
    for ch in s:
        if ch in _TOML_ESCAPES:
            out.append(_TOML_ESCAPES[ch])
        elif ord(ch) < 0x20 or ord(ch) == 0x7F:
            out.append(f"\\u{ord(ch):04X}")
        else:
            out.append(ch)
    return '"' + "".join(out) + '"'


def _toml_value(v: object) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int | float):
        return repr(v)
    return _toml_str(str(v))


def _write(d: dict) -> None:
    p = _config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# CricDesk CLI config — edit by hand or via `cricdesk config set`.\n"]
    for k, v in d.items():
        key = k if _BARE_KEY.fullmatch(k) else _toml_str(k)
        lines.append(f"{key} = {_toml_value(v)}\n")
    p.write_text("".join(lines), encoding="utf-8")
    p.chmod(stat.S_IRUSR | stat.S_IWUSR)  # 600 — credential safety.


@app.command("path", help="Print the config file path.")
def path_cmd() -> None:
    typer.echo(str(_config_path()))


@app.command("get", help="Read a single config key (or list all when no key).")
def get_cmd(key: str = typer.Argument(None)) -> None:
    cfg = _read()
    if not key:
        if not cfg:
            console().print("[dim](empty — run `cricdesk config set <key> <value>`)[/dim]")
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
        p.write_text("# CricDesk CLI config.\n")
        p.chmod(stat.S_IRUSR | stat.S_IWUSR)
    subprocess.run([editor, str(p)], check=False)
