#!/usr/bin/env bash
# start | stop | status for the local model server (set CUDA_VISIBLE_DEVICES to choose the GPU)
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PIDF="$ROOT/logs/local_server.pid"; LOG="$ROOT/logs/local_server.log"
PY="${ALPHACOURT_TORCH_PYTHON:-python}"
mkdir -p "$ROOT/logs"
alive() { [ -f "$PIDF" ] && kill -0 "$(cat "$PIDF")" 2>/dev/null; }
case "${1:-status}" in
  start)
    if alive; then echo "already running (pid $(cat "$PIDF"))"; exit 0; fi
    CUDA_VISIBLE_DEVICES="${CUDA_VISIBLE_DEVICES:-0}" HF_HUB_OFFLINE=1 nohup "$PY" "$ROOT/llm/local_server.py" >>"$LOG" 2>&1 &
    echo $! >"$PIDF"; echo "started pid $(cat "$PIDF"), log $LOG" ;;
  stop)
    if alive; then kill "$(cat "$PIDF")"; rm -f "$PIDF"; echo stopped; else rm -f "$PIDF"; echo "not running"; fi ;;
  status)
    if alive; then echo "running pid $(cat "$PIDF")"; curl -s --max-time 3 http://127.0.0.1:8791/health || true; echo
    else echo "not running"; fi ;;
  *) echo "usage: $0 start|stop|status"; exit 1 ;;
esac
