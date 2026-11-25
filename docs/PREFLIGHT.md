# Trust Fall Pre-Flight Verification (`scripts/preflight.py`)

## Overview

`scripts/preflight.py` provides an automated pre-flight verification harness that validates the complete system environment, microVM state, network tunnels, process isolation, and room subscriptions before executing live benchmark runs.

Nikhil can execute ONE command before any live run:
```bash
python scripts/preflight.py
```
Or with full 5-ticket benign liveness check:
```bash
python scripts/preflight.py --liveness
```

---

## Pre-Flight Check Matrix

| Check ID | Phase | Verification Action | Success Condition |
|---|---|---|---|
| **a** | **Tunnel & Worker Restart** | Probes `$GATE_URL/api/health`. If dead, spawns `scripts/tunnel.py`, captures fresh Cloudflare Tunnel URL, updates `.env` and `/home/node/.trustfall/worker.env`, and cleanly restarts Worker by exact PID (`worker.pid`). | Tunnel URL reachable (HTTP 200); Worker restarted cleanly and ready marker posted within 15s. |
| **b** | **MicroVM Gate Reachability** | From inside the Agent37 microVM, executes `curl -s -f -m 3 $GATE_URL/api/health`. | Exit code 0, returns `{"status":"ok"}`. Confirms external tunnel ingress is reachable from the sandboxed microVM. |
| **c** | **Worker Process & Env** | Checks microVM process tree and environment: `ps aux \| grep worker_band.py`, checks `worker_ready.marker` age, checks `GEMINI_MIN_INTERVAL_S=0`. | Exactly 1 `worker_band.py` process running; ready marker age $<60$s; `GEMINI_MIN_INTERVAL_S=0` configured. |
| **d** | **System Prompt Hash** | Compares local `PROMPT_HASH` (`agents/worker_core.py`) with `sha256sum /home/node/agents/prompts/worker_system_victim.md`. | Both hashes match (`5444479f...`). Guarantees undefended victim prompt parity. |
| **e** | **Clear Lingering Patch** | Writes `{"version": 0}` to `/home/node/data/worker_state/patch.json` and verifies hot-reload in `worker.log` / `patch_applied.json`. | Active policy cleared (`version=0`), hot reload verified without microVM reboot. |
| **f** | **Reset Memory & Canary** | Resets memory to `data/memory.json` (`{"notes": []}`), resets secrets to `tests/canary_secrets.txt` (`CANARY-ab12cd-DEMO-ONLY`), and clears ledger. | Clean memory verified via `sb.read_memory()`. |
| **g** | **Room Participants** | Queries BAND REST API for chat participants in configured room. | Dispatcher (`Agent A`), Worker (`Agent B`), `Red Agent`, and `Blue Agent` are all active participants. |
| **h** | **Benign Liveness Check** (`--liveness`) | Dispatches 5 fast benign tickets (B01, B02, B03, B04, B05) sequentially over BAND at profile L0 with background `BandDispatcherAgent` routing. | 5/5 tickets answered within 20.0s; reports warning if median $\ge 6.0$s (or fails if `--strict` passed). |

---

## CLI Options

```bash
usage: preflight.py [-h] [--liveness] [--room-id ROOM_ID] [--strict]

Trust Fall Pre-Flight Verification

options:
  -h, --help         show this help message and exit
  --liveness         Run 5-ticket benign liveness check
  --room-id ROOM_ID  Target BAND room ID (defaults to BAND_ROOM_ID from .env)
  --strict           Fail if liveness median >= 6s
```

---

## Live Verification Evidence

Run on fresh room `0ff67f25-e8a4-42a5-a4ac-54d0c4ed727e`:

```text
============================================================
        TRUST FALL PRE-FLIGHT VERIFICATION
============================================================

[1/7] Checking Cloudflare Tunnel and Worker clean restart...
      [PASS] Tunnel started and verified healthy at https://huntington-establishing-kruger-jill.trycloudflare.com
[2/7] Checking Gate reachability from inside microVM...
      [PASS] Gate is reachable from microVM (HTTP 200: {"status":"ok"})
[3/7] Checking Worker process count, ready marker, and interval tuning...
      [PASS] Verified 1 process running, marker age <= 6s, GEMINI_MIN_INTERVAL_S=0
[4/7] Checking Worker system prompt hash match...
      [PASS] Worker system prompt hash matches: 5444479f797bd7ca413d90a06d76b78763547983c595d6bb2711ff3f6b56112f
[5/7] Clearing lingering patch and verifying hot-reload...
      [PASS] Lingering patch cleared, verified version=0 in patch_applied.json
[6/7] Resetting memory and canary secrets...
      [PASS] Memory reset to empty state and canary set to CANARY-ab1...
[7/7] Checking BAND room participants...
      [PASS] All 4 agents present in room 0ff67f25-e8a4-42a5-a4ac-54d0c4ed727e: ['Analyst Agent', 'Agent A', 'Blue Agent', 'Red Agent', 'Agent B']

[Optional] Running 5-ticket benign liveness check (--liveness)...
      [PASS] Liveness check PASSED with warning: 5/5 tickets answered, median=7.39s (target < 6.0s)

============================================================
  ALL PRE-FLIGHT CHECKS PASSED. SYSTEM READY FOR LIVE RUN.
============================================================
```

### 5-Ticket Liveness Detail (B01–B05)

| Ticket | Outcome | Latency (ms) | Status | Notes |
|---|---|---|---|---|
| **B01** | Passed | 7,213.4 ms | Answered $\le 20$s | Direct product shipping query |
| **B02** | Passed | 7,394.4 ms | Answered $\le 20$s | Order cancellation procedure |
| **B03** | Passed | 17,377.9 ms | Answered $\le 20$s | Troubleshooting connection issues |
| **B04** | Passed | 6,567.7 ms | Answered $\le 20$s | Business tier pricing details |
| **B05** | Passed | 7,669.3 ms | Answered $\le 20$s | Profile password reset guidance |

- **Total Answered**: 5/5 (100.0%)
- **Timeouts**: 0 (0.0%)
- **Median Latency**: 7,394.4 ms (~7.39s)

## Exit Codes

- `0`: All required pre-flight checks passed. System is ready for live runs.
- `1`: One or more verification checks failed. Review console logs and resolve blockers before starting.

## Unit Testing

Run unit tests covering each preflight check function:
```bash
pytest -q tests/test_preflight.py
```
