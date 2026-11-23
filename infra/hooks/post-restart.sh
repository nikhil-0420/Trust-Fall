#!/bin/bash
# Post-restart boot hook for Agent37 sandbox
set -e

echo "[boot-hook] Running post-restart hook at $(date -u)" >> /tmp/post-restart.log

if [ -f "/home/node/run_worker.sh" ]; then
    /bin/bash /home/node/run_worker.sh
elif [ -f "worker_band.py" ] || [ -f "agents/worker_band.py" ]; then
    cd /home/node && (nohup python3 -u worker_band.py >> worker.log 2>&1 & disown)
fi
