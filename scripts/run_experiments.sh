#!/usr/bin/env bash
# One command: run E1 to E5, score, and export the site data. Resumable: finished trials are skipped.
#   scripts/run_experiments.sh [split] [limit]      e.g. scripts/run_experiments.sh dev 4
# Needs the local model server on GPU 1 for the local staffings (scripts/local_models.sh).
set -euo pipefail
cd "$(dirname "$0")/.."
SPLIT="${1:-test}"
LIMIT=()
[ -n "${2:-}" ] && LIMIT=(--limit "$2")
mkdir -p logs
uv run python -m experiments.e1 --split "$SPLIT" "${LIMIT[@]}"
uv run python -m experiments.e2 --split "$SPLIT" "${LIMIT[@]}"
uv run python -m experiments.e3 --split "$SPLIT" "${LIMIT[@]}"
uv run python -m experiments.e4
uv run python -m experiments.e5 --bench
uv run python -m experiments.score e1 e2 e3 e4 e5
uv run python scripts/export_site.py --split "$SPLIT"
