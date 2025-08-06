#!/usr/bin/env bash
# Tail assistant logs from the repository root's log directory

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
LOG_DIR="$ROOT_DIR/log"

mkdir -p "$LOG_DIR"

# Ensure at least one log file exists so tail doesn't exit immediately
shopt -s nullglob
log_files=("$LOG_DIR"/*.log)
shopt -u nullglob

if [ ${#log_files[@]} -eq 0 ]; then
  echo "No log files found in $LOG_DIR. Creating placeholder log."
  placeholder="$LOG_DIR/placeholder.log"
  : > "$placeholder"
fi

tail -F "$LOG_DIR"/*.log || true
