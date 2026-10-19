#!/usr/bin/env bash
# Rebuild everything from Cricsheet, for every league the registry exports (config/leagues.toml):
#   ingest every league → People Register → ratings for ALL leagues → metrics for ALL → ONE export.
# The export runs only after every league is refit: the IPL export reads every league's ratings
# (Scout index, auction pool), so exporting league by league would mix fresh and stale values.
#
# Resumable: each finished step leaves a marker in $STATE; re-run to continue after a failure or a
# reboot. Start over with --fresh. Multi-hour on a laptop — on Windows run it as a scheduled task.
#
#   bash scripts/rebuild_all.sh            # resume (or start)
#   bash scripts/rebuild_all.sh --fresh    # clear markers and rebuild from scratch
#   bash scripts/rebuild_all.sh --from ratings   # keep the ingested data + People Register: refit
#                                          # ratings, recompute metrics, export (no re-download)
#   bash scripts/rebuild_all.sh --from metrics   # only metrics + export
#   LEAGUES="ipl psl" bash scripts/rebuild_all.sh   # only these (still exports everything at the end)
set -u
cd "$(dirname "$0")/.." || exit 1
export PYTHONIOENCODING=utf-8

if [ -x ".venv/Scripts/python.exe" ]; then PY=".venv/Scripts/python.exe"
elif [ -x ".venv/bin/python" ]; then PY=".venv/bin/python"
else PY="uv run python"; fi

STATE="${CRICDEX_REBUILD_STATE:-data/.rebuild_state}"
LOG="${CRICDEX_REBUILD_LOG:-data/rebuild.log}"
FROM=""
case "${1:-}" in
  --fresh) rm -rf "$STATE" ;;
  --from)
    FROM="${2:-}"
    case "$FROM" in ratings|metrics|export) ;; *) echo "usage: $0 [--fresh | --from ratings|metrics|export]"; exit 2 ;; esac ;;
esac
mkdir -p "$STATE" "$(dirname "$LOG")"
# --from <stage>: mark everything before it done and clear its markers (and later ones), so the
# run starts there; ingest + People Register are kept as they are
if [ -n "$FROM" ]; then
  touch "$STATE/people"
  for C in ${LEAGUES:-$($PY -m cricdex.leagues list --exported --sep " ")}; do touch "$STATE/ingest_$C"; done
  rm -f "$STATE/export_all" "$STATE/READY"
  [ "$FROM" != export ] && rm -f "$STATE"/metrics_*
  [ "$FROM" = ratings ] && rm -f "$STATE"/ratings_*
fi

say() { echo "=== $(date '+%F %H:%M:%S') $*" | tee -a "$LOG"; }
step() {  # step <marker> <label> <command...>
  local m="$1" label="$2"; shift 2
  [ -f "$STATE/$m" ] && return 0
  say "$label"
  if "$@" >> "$LOG" 2>&1; then touch "$STATE/$m"; else say "!! $label failed — see $LOG, then re-run to resume"; exit 1; fi
}

COLS="${LEAGUES:-$($PY -m cricdex.leagues list --exported --sep " ")}"
say "leagues: $COLS"
for C in $COLS; do
  step "ingest_$C" "ingest $C" $PY scripts/ingest_cricsheet.py ingest --collection "$C" --force
done
step people "People Register" $PY scripts/ingest_people.py --force
for C in $COLS; do
  step "ratings_$C" "ratings $C" $PY scripts/scout_rate.py --collection "$C" --advi-steps 12000
done
for C in $COLS; do
  step "metrics_$C" "metrics $C" $PY scripts/compute_metrics.py all --collection "$C"
done
step export_all "export every league" $PY scripts/export_site.py
touch "$STATE/READY"
say "READY — run the tests, check the site, then commit site/public/data"
