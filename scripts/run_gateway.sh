#!/usr/bin/env bash
# Runs the AlphaCourt gateway (FastAPI under uvicorn) on 127.0.0.1:8787, logging to logs/gateway.log.
#
#   scripts/run_gateway.sh [start]   start in the background
#   scripts/run_gateway.sh stop | restart | status
#
# Listens on localhost only; the tunnel points at this port. The models run in llm/local_server.py.
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p logs
PORT=8787
PIDFILE=logs/gateway.pid
LOG=logs/gateway.log
export CUDA_VISIBLE_DEVICES="${CUDA_VISIBLE_DEVICES:-0}" HF_HUB_OFFLINE=1 PYTHONUNBUFFERED=1

running() { [[ -f $PIDFILE ]] && kill -0 "$(cat $PIDFILE)" 2>/dev/null; }

start() {
  if running; then echo "Gateway already running (pid $(cat $PIDFILE))."; return 0; fi
  nohup uv run uvicorn gateway.app:app --host 127.0.0.1 --port $PORT --workers 1 \
      --limit-concurrency 100 --timeout-keep-alive 10 --timeout-graceful-shutdown 5 --no-access-log \
      >>"$LOG" 2>&1 &
  echo $! >"$PIDFILE"
  for _ in $(seq 1 60); do
    if curl -fsS "http://127.0.0.1:$PORT/api/health" >/dev/null 2>&1; then
      echo "Gateway up on http://127.0.0.1:$PORT (pid $(cat $PIDFILE)). Log: $LOG"; return 0
    fi
    if ! running; then echo "Gateway failed to start. See $LOG."; tail -20 "$LOG"; return 1; fi
    sleep 1
  done
  echo "Gateway did not answer within 60 s. See $LOG."; return 1
}

stop() {
  if running; then
    kill "$(cat $PIDFILE)" && echo "Stopped gateway (pid $(cat $PIDFILE))."
    for _ in $(seq 1 20); do running || break; sleep 0.5; done
  else
    echo "Gateway not running."
  fi
  rm -f "$PIDFILE"
}

case "${1:-start}" in
  start) start ;;
  stop) stop ;;
  restart) stop; start ;;
  status)
    if running; then echo "running (pid $(cat $PIDFILE))"; curl -fsS "http://127.0.0.1:$PORT/api/health" || true; echo
    else echo "not running"; fi ;;
  *) echo "usage: $0 [start|stop|restart|status]"; exit 2 ;;
esac
