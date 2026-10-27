#!/bin/zsh
# Daily refresh: pull fresh data, rebuild site/data.json, append the gauge log.
# Run by hand or by the launchd agent in scripts/com.macrohealth.refresh.plist.
set -euo pipefail
ROOT="${0:A:h:h}"
cd "$ROOT"
mkdir -p logs
{
  echo "=== $(date '+%Y-%m-%d %H:%M:%S') ==="
  ./.venv/bin/python -W ignore -m mhd.export
  cp data/history/gauge_log.csv site/gauge_log.csv
} >> logs/refresh.log 2>&1
tail -1 logs/refresh.log
