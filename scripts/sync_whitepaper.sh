#!/usr/bin/env bash
# scripts/sync_whitepaper.sh
# ───────────────────────────────────────────────────────────────
# Mirror the canonical methodology white paper into the frontend
# project so the /methodology/whitepaper route can read it at
# build time without reaching above the frontend project root.
#
# Usage:
#   ./scripts/sync_whitepaper.sh        # copy + verify
#   ./scripts/sync_whitepaper.sh --check # exit 1 if mirror is stale
#
# CI invokes the --check form so a PR that edits the source without
# updating the mirror fails the gate. Authors should run the bare
# form locally before pushing.
# ───────────────────────────────────────────────────────────────
set -euo pipefail

SRC="docs/methodology/whitepaper.md"
DST="frontend/content/methodology/whitepaper.md"

if [[ ! -f "$SRC" ]]; then
  echo "sync_whitepaper: source missing: $SRC" >&2
  exit 2
fi

if [[ "${1:-}" == "--check" ]]; then
  if ! diff -q "$SRC" "$DST" > /dev/null 2>&1; then
    echo "sync_whitepaper: mirror out of sync." >&2
    echo "  source: $SRC" >&2
    echo "  mirror: $DST" >&2
    echo "  fix:    ./scripts/sync_whitepaper.sh" >&2
    exit 1
  fi
  echo "sync_whitepaper: mirror in sync."
  exit 0
fi

mkdir -p "$(dirname "$DST")"
cp "$SRC" "$DST"
echo "sync_whitepaper: $SRC -> $DST"
