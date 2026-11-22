#!/bin/bash
# Post-restart boot hook for Agent37 sandbox
# Runs on every boot: restores patch.json if present, relaunches worker agent in background.
set -e

cd /root || cd ~ || cd .

echo "[boot-hook] Running post-restart hook at $(date -u)" >> /tmp/post-restart.log

# Restore patch if saved in persistent location
if [ -f "/root/patch.json" ]; then
    echo "[boot-hook] Found existing patch.json" >> /tmp/post-restart.log
fi

# Kill any existing worker process cleanly to remain idempotent
pkill -f "python3.*worker_band.py" || true
sleep 1

# Launch worker in background with nohup if worker_band.py exists
if [ -f "worker_band.py" ] || [ -f "agents/worker_band.py" ]; then
    ENTRY="worker_band.py"
    if [ ! -f "worker_band.py" ] && [ -f "agents/worker_band.py" ]; then
        ENTRY="agents/worker_band.py"
    fi
    nohup python3 -u "$ENTRY" >> /tmp/worker.log 2>&1 &
    echo "[boot-hook] Relaunched $ENTRY with PID $!" >> /tmp/post-restart.log
fi
