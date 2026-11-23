# Agent37 Sandbox Restart Survival Diagnosis

**Date**: 2026-11-23  
**Target Sandbox ID**: `<SANDBOX_ID>` (Agent37 remote microVM)  
**Component**: `worker_band.py` (Accommodating victim Worker under Gemini 3.5 Flash-Lite)

---

## 1. Initial State and Launch Configuration

- **Launch Command**: `cd /home/node && (python3 -u worker_band.py > worker.log 2>&1 &)`
- **Working Directory**: `/home/node`
- **Environment Source**: Sourced from local `.env` uploaded to `/home/node/.env` during initial deployment.
- **Hook Configuration**: Hook uploaded to `/home/node/.agent37/hooks/post-restart.sh` (chmod +x).

---

## 2. Experimental Observation (3 Isolated Restart Cycles)

Across 3 repeated restart cycles using the real sandbox, the following facts were observed:

| Cycle | Restart Duration | Active Python Worker PIDs | Worker Log Tail Post-Restart | Hook Execution (`/tmp/post-restart.log`) | BAND Benign Ticket Reply (30s) |
|---|---|---|---|---|---|
| **Cycle 1** | 6.3s | 0 active worker processes | Frozen at pre-restart timestamp (`11:51:17`) | File not found (`NO /tmp/post-restart.log`) | Timed out (no reply) |
| **Cycle 2** | 6.3s | 0 active worker processes | Frozen at pre-restart timestamp (`11:51:17`) | File not found (`NO /tmp/post-restart.log`) | Timed out (no reply) |
| **Cycle 3** | 7.2s | 0 active worker processes | Frozen at pre-restart timestamp (`11:51:17`) | File not found (`NO /tmp/post-restart.log`) | Timed out (no reply) |

### Key Evidence
1. **Boot Hook Non-Execution**: In all three cycles, `/tmp/post-restart.log` was completely absent. Agent37 microVM infrastructure does not automatically execute `/home/node/.agent37/hooks/post-restart.sh` upon container reboot.
2. **Process Eviction**: When the container restarted, the microVM kernel terminated all running processes (including PID 505 running `python3 -u worker_band.py`).
3. **Exec Session Lifespan / Missing Daemonization**: The inline shell relaunch in `Agent37Sandbox.restart()` ran inside an ephemeral exec session (`/.agent37/bin/agent37-init run -- sh -c ...`). When the exec command finished, any background subshell was reaped because it was not decoupled via `nohup` + `disown` / `flock` and did not have its environment variables explicitly preserved in a dedicated environment file.

---

## 3. Observed Root Cause

The failure of Worker survival across sandbox restarts is caused by a compound failure:
1. **Uninvoked Hook**: The Agent37 container environment does not trigger post-boot hooks in `/home/node/.agent37/hooks/`.
2. **Environment Loss and Session Reaping**: Post-restart exec commands run in a clean login shell without the credentials and settings required by the worker. Without an explicit, persistent, permission-secured environment file (`worker.env`) and a decoupled launcher script with a singleton lock (`flock`), the worker either fails to launch, crashes immediately due to missing environment keys, or is terminated when the exec wrapper session exits.
3. **Missing Ready Synchronization**: The supervisor returned immediately after restarting the container without waiting for the Worker to establish an active polling session with the BAND REST API.

---

## 4. Remediation Plan

1. **Persistent Environment File**:
   - Write `/home/node/.trustfall/worker.env` with `chmod 600` containing all required environment variables (`GEMINI_API_KEY`, `BAND_AGENT_B_ID`, `BAND_AGENT_B_KEY`, `BAND_ROOM_ID`, `INTERNAL_TOKEN`, `MODEL_NAME`, `WORKER_PROMPT`, `STATE_DIR`, `GATE_URL`).
   - Sourced explicitly by the unified launcher.
2. **Unified Launcher Script (`/home/node/run_worker.sh`)**:
   - Uses `flock -n /tmp/worker.lock` to guarantee singleton process execution.
   - Decouples process with `nohup python3 -u worker_band.py >> /home/node/worker.log 2>&1 & disown`.
   - Used by both boot hooks and `Agent37Sandbox.restart()`.
3. **Ready Marker Verification**:
   - `worker_band.py` writes `/home/node/worker_ready.marker` containing a timestamp as soon as the REST polling connection to BAND is established.
   - `Agent37Sandbox.restart()` removes any old marker, launches `run_worker.sh`, and polls until `worker_ready.marker` is updated and fresh.
4. **Post-Restart Ping Verification**:
   - `restart()` sends a ping verification to guarantee end-to-end responsiveness before returning.

---

## 5. Post-Fix Verification (3 Isolated Restart Cycles)

Following the implementation of `worker.env` (`chmod 600`), `run_worker.sh` (`flock`), and ready marker synchronization, 3 consecutive isolated restart cycles were conducted on sandbox `<SANDBOX_ID>`:

| Cycle | Restart Duration | Active Python Worker PIDs | Worker Log Tail Post-Restart | Hook Execution | BAND Benign Ticket Reply (<30s) |
|---|---|---|---|---|---|
| **Cycle 1** | 41.8s | 1 active worker (PID 508) | Active polling (200 OK) | `[boot-hook] Running post-restart hook at 12:11:54 UTC` | **SUCCESS** (`DIAG-CYCLE-1-...`) |
| **Cycle 2** | 40.5s | 1 active worker (PID 15) | Active polling (200 OK) | `[boot-hook] Running post-restart hook at 12:13:14 UTC` | **SUCCESS** (`DIAG-CYCLE-2-...`) |
| **Cycle 3** | 40.7s | 1 active worker (PID 15) | Active polling (200 OK) | `[boot-hook] Running post-restart hook at 12:14:27 UTC` | **SUCCESS** (`DIAG-CYCLE-3-...`) |

In all 3 verification cycles, the worker process cleanly survived/restarted, environment variables were safely retained without leakage, the singleton lock prevented duplicate workers, and the benign ping ticket received an end-to-end response over BAND within 30 seconds.

---

## 6. Step 5 Persistence Check Result

An explicit persistence test was conducted (`scripts/test_persistence_check.py`):
1. **Memory Marker**: Wrote test marker `PERSIST_MARKER_1795436624` to `/home/node/memory.json`.
2. **Patch Marker**: Wrote test patch `PERSIST_RULE_1795436624` to `/home/node/patch.json`.
3. **Restart**: Executed container reboot via `Agent37Sandbox.restart()` (duration 38.7s).
4. **Persistence Verification**:
   - `/home/node/memory.json`: **Persisted** (marker verified intact).
   - `/home/node/patch.json`: **Persisted** (patch rule verified intact).
5. **Worker Process Check**: Exactly **1 active python worker process** (`worker_band.py`, PID 15) running under singleton flock.
6. **Liveness & Roundtrip**: Sent benign ticket `PERSIST-CHECK-1795436674` over real BAND transport; received full response within 30s (`@[[...]] [Worker Report] [TICKET:PERSIST-CHECK-1795436674]: Ticket ...`).

**Overall Verdict**: **PASS** (Sandbox files persist across restarts, singleton worker auto-starts with full credentials, and processes live BAND traffic).
