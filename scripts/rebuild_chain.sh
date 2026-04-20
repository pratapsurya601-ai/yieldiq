#!/usr/bin/env bash
# Sequential rebuild chain after data backfills:
#   1. peer_groups   (now sector-aware via 2287 enriched stocks)
#   2. ratio_history (now with 9759 corp-action rows for split adjustment)
#   3. analytics extensions (Piotroski / Altman / DuPont / CAGR)
#   4. parquet export
#   5. coverage verify
#
# Each step prints a milestone the Monitor will pick up.
set -euo pipefail
cd "$(dirname "$0")/.."

set -a
. ./.env.local
set +a

PY=/c/ProgramData/miniconda3/envs/dcf_screener/python.exe

echo "======= STEP 1/5: peer_groups (sector-aware) ======="
"$PY" scripts/build_peer_groups.py --all 2>&1 | grep -E "^starting|^done\." || true
echo "======= STEP 1/5 DONE ======="

echo "======= STEP 2/5: ratio_history (corp-actions adjusted) ======="
"$PY" scripts/build_ratio_history.py --all 2>&1 | grep -E "^starting|^done|^[0-9]+/[0-9]+ .+processed [0-9]+ periods" | grep -E "^starting|^done|/[0-9]00 " || true
echo "======= STEP 2/5 DONE ======="

echo "======= STEP 3/5: analytics extensions ======="
"$PY" scripts/build_analytics_extensions.py --all 2>&1 | grep -E "^processing|^done|^\[[0-9]00/" || true
echo "======= STEP 3/5 DONE ======="

echo "======= STEP 4/5: parquet export ======="
"$PY" scripts/export_to_parquet.py 2>&1 | grep -E "exporting|SUMMARY|MB total"
echo "======= STEP 4/5 DONE ======="

echo "======= STEP 5/5: coverage verify ======="
"$PY" scripts/verify_coverage.py
echo "======= STEP 5/5 DONE ======="

echo "ALL REBUILD STEPS COMPLETE"
