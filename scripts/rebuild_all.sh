#!/usr/bin/env bash
# Rebuild everything from Cricsheet, for every league the registry exports (config/leagues.toml).
# A thin wrapper: the steps, their order and the resume markers live in src/cricdex/pipeline.py
# (docs/PIPELINE.md). `python -m cricdex.pipeline --list` prints them.
#
# Resumable: each finished step leaves a marker in $CRICDEX_REBUILD_STATE (default
# data/.rebuild_state); re-run to continue after a failure or a reboot. Output goes to
# $CRICDEX_REBUILD_LOG (default data/rebuild.log). Multi-hour on a laptop: on Windows run it as a
# scheduled task.
#
#   bash scripts/rebuild_all.sh                  # resume (or start)
#   bash scripts/rebuild_all.sh --fresh          # clear markers and rebuild from scratch
#   bash scripts/rebuild_all.sh --from ratings   # keep the ingested data + People Register and
#                                                # player master: ratings, metrics, forecast, export
#   bash scripts/rebuild_all.sh --from metrics   # only metrics, forecast and export
#   bash scripts/rebuild_all.sh --refit          # also the model fits (never run by default)
#   LEAGUES="ipl psl" bash scripts/rebuild_all.sh   # only these (still exports everything at the end)
set -u
cd "$(dirname "$0")/.." || exit 1
export PYTHONIOENCODING=utf-8

if [ -x ".venv/Scripts/python.exe" ]; then PY=".venv/Scripts/python.exe"
elif [ -x ".venv/bin/python" ]; then PY=".venv/bin/python"
else PY="uv run python"; fi

exec $PY -m cricdex.pipeline "$@"
