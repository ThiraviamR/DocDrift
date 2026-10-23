#!/usr/bin/env bash
# Simulates a developer merging a breaking API change without touching the docs:
#   /v1/stock -> /v1/inventory, limit -> page_size (default 20 -> 50),
#   ttl_minutes -> hold_minutes, INV_DB_URL -> INVENTORY_DATABASE_URL
# Usage: ./demo/make_change.sh [target_dir]
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TARGET="${1:-$ROOT/demo_repo}"

cp "$ROOT/demo/after/main.py" "$TARGET/app/main.py"
cd "$TARGET"
git add -A
git commit -q -m "Rename stock API to inventory, switch to page_size pagination"
git --no-pager log --oneline -2
