#!/usr/bin/env bash
# Attach Claude Code to the AlphaCourt gateway and ask it for a strategy. Spends the Claude subscription.
# Usage: scripts/attach_claude.sh "<brief>" [mcp-url]     (default http://127.0.0.1:8787/mcp)
set -euo pipefail
BRIEF="${1:?usage: attach_claude.sh \"<brief>\" [mcp-url]}"
URL="${2:-http://127.0.0.1:8787/mcp}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CLAUDE="${CLAUDE_BIN:-claude}"
OUT="$ROOT/results/attach"
mkdir -p "$OUT"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
CFG="$(mktemp --suffix=.json)"
trap 'rm -f "$CFG"' EXIT
cat > "$CFG" <<JSON
{"mcpServers": {"alphacourt": {"type": "http", "url": "$URL"}}}
JSON
LOG="$OUT/claude_$STAMP.txt"
# Run from an empty folder so the agent sees only the brief and the gateway's tools.
WORK="$(mktemp -d)"
( cd "$WORK" && "$CLAUDE" -p "$BRIEF" --model "${CLAUDE_MODEL:-sonnet}" --mcp-config "$CFG" --strict-mcp-config \
    --allowedTools "mcp__alphacourt__*" ) | tee "$LOG"
rm -rf "$WORK"
CASE="$(grep -oE 'AC-[0-9]{4}' "$LOG" | tail -n1 || true)"
echo "${CASE:-none}" > "$OUT/claude_$STAMP.case"
echo
echo "case id: ${CASE:-none}   transcript: $LOG"
