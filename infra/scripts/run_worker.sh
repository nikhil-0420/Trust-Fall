#!/bin/bash
# Unified launcher for worker_band.py with flock and persistent env sourcing
set -e
LOCKFILE="/tmp/worker.lock"
exec 200>"$LOCKFILE"
flock -n 200 || { echo "[launcher] Worker already running or starting, exiting."; exit 0; }

cd /home/node

# Source persistent environment if present
if [ -f "/home/node/.trustfall/worker.env" ]; then
    set -a
    . /home/node/.trustfall/worker.env
    set +a
fi

# Ensure STATE_DIR is set
export STATE_DIR="${STATE_DIR:-.}"
export WORKER_PROMPT="${WORKER_PROMPT:-victim}"
export MODEL_NAME="${MODEL_NAME:-gemini-3.5-flash-lite}"

# If worker is already active, do not relaunch
if ps aux | grep '[w]orker_band.py' >/dev/null 2>&1; then
    echo "[launcher] worker_band.py is already active."
    exit 0
fi

# Remove stale ready marker before launch
rm -f /home/node/worker_ready.marker

echo "[launcher] Starting worker_band.py at $(date -u)" >> /home/node/worker_launcher.log
nohup python3 -u worker_band.py >> /home/node/worker.log 2>&1 &
echo $! > /home/node/worker.pid
disown
