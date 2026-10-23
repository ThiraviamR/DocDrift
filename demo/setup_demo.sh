#!/usr/bin/env bash
# Creates a fresh git repo from sample_app/ so the demo is repeatable.
# Usage: ./demo/setup_demo.sh [target_dir]   (default: ./demo_repo)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TARGET="${1:-$ROOT/demo_repo}"

rm -rf "$TARGET"
mkdir -p "$TARGET"
cp -R "$ROOT/sample_app/." "$TARGET/"
cd "$TARGET"
git init -q -b main
git config user.email "demo@docdrift.local"
git config user.name "DocDrift Demo"
git add -A
git commit -q -m "Inventory API v1"
echo "Demo repo ready at $TARGET"
