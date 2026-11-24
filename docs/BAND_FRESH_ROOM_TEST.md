# Fresh-Room BAND Transport Test Report (Diagnosed & Corrected)

**Execution Date:** 2026-11-24T05:43:16.894487+00:00  
**Diagnosis & Audit Date:** 2026-11-24T12:35:00+05:30  
**Fresh Room ID:** `df5f87eb-6507-4b62-8587-3346a332c018`  
**Old Room ID:** `2259e40a-1833-49f4-b647-596ac09f99ea`  
**Worker Updated in Sandbox:** `No` (Update command exited with code 137 during `pkill -9 -f python3`)  
**Agents in Fresh Room:**  
1. `acfa6e7d-94d7-463d-82d2-28b3a5ef42a0` (Red Agent)
2. `b883bc3f-7e9b-4ecf-a0bb-1e4a4ddb1dfb` (Worker Agent)
3. `3a930431-fe67-428a-821d-91b75fa59b48` (Dispatcher Agent)
4. `69c27771-0677-44bc-8774-a6fcda8591ef` (Blue Agent)
5. `d360980c-e170-4f81-a7fc-4e14beab3fe2` (Analyst Agent)

---

## Room Message Count and Sender Breakdown

- **Fresh Room Total Message Count:** `10` messages
- **Sender Breakdown in Fresh Room:**
  - Red Agent (`acfa6e7d-94d7-463d-82d2-28b3a5ef42a0`): **10 messages** (the 10 test tickets)
  - Dispatcher Agent (`3a930431-fe67-428a-821d-91b75fa59b48`): **0 messages**
  - Worker Agent (`b883bc3f-7e9b-4ecf-a0bb-1e4a4ddb1dfb`): **0 messages**

- **Old Room Message Count:** `561` messages
  - Red Agent: 376 messages
  - Worker Agent: 185 messages

---

## Root Cause Analysis: Why 10 Messages for 10 Tickets?

The initial speculative finding in this document attributed the 0/10 replies to "BAND delivery delays / agent polling latency or sandbox Worker connectivity over REST" or message backlog. **That speculation was incorrect.**

The root cause was determined via direct inspection of sandbox process state and execution logs:
1. **Worker Process Dead in Sandbox:** In `scripts/test_band_fresh.py`, the script attempted to update the worker environment to `BAND_ROOM_ID="df5f87eb-6507-4b62-8587-3346a332c018"` and restart it using `pkill -9 -f python3`. The Agent37 sandbox exec runner itself uses a Python process or helper; `pkill -9 -f python3` killed the exec session itself, returning exit code 137 (`Worker update failed: Command failed with exit code 137`).
2. **Worker Never Restarted:** Because the command failed with code 137, `/home/node/run_worker.sh` was never executed. The Worker process was dead inside the container throughout the entire 10-ticket test.
3. **Static Room Subscription:** Worker processes do not dynamically inspect or join newly created rooms via BAND SDK; they read the static `BAND_ROOM_ID` environment variable at boot time. Because the environment update failed and the process was dead, no worker was listening on `df5f87eb-6507-4b62-8587-3346a332c018`.
4. **All 10 Messages were Inbound Red Sends:** The 10 messages in the fresh room were solely the 10 inbound ticket requests submitted by `BandTransport` (Red Agent). Zero worker responses were sent because no worker was alive to receive or process them.

---

## Conclusion & Fix

- **Corrected Finding:** The timeout was not caused by BAND infrastructure latency or backlog; it was caused by a dead worker process inside the Agent37 sandbox due to unsafe process killing (`pkill -9 -f python3`).
- **Fix Implemented:** Replaced broad `pkill` patterns with exact PID tracking via `/home/node/worker.pid` and process filtering (`grep '[w]orker_band.py'`). The worker has now been redeployed and verified running with PID 1306.
