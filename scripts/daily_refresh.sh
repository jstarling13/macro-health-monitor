#!/bin/zsh
# Daily refresh: pull fresh data, rebuild site/data.json behind the publish
# checks, append the gauge log. Exits non-zero (and changes nothing) if a
# hard check fails. The hosted site runs the same steps on GitHub Actions.
set -uo pipefail
ROOT="${0:A:h:h}"
cd "$ROOT"
mkdir -p logs
echo "=== $(date '+%Y-%m-%d %H:%M:%S') ===" >> logs/refresh.log
./.venv/bin/python -W ignore -m mhd.export "$@" 2>&1 | tee -a logs/refresh.log
code=${pipestatus[1]}
[ "$code" -eq 0 ] && cp data/history/gauge_log.csv site/gauge_log.csv
exit "$code"
