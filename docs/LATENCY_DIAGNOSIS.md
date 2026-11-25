# BAND Latency Diagnosis & Qualification Report

**Owner:** Nikhil  
**Status:** Completed  
**Qualified Room ID:** `0ff67f25-e8a4-42a5-a4ac-54d0c4ed727e`  
**Legacy Room ID:** `2259e40a-1833-49f4-b647-596ac09f99ea`

---

## 1. Executive Summary & Root Cause

Live runs over BAND previously exhibited round-trip latencies of 30-45 seconds per ticket, occasionally hitting the 30-second timeout.

Through source tracing and live telemetry instrumentation, we identified the primary root causes:
1. **Gemini Pacing Default (`13.0s`)**: In `agents/llm_gemini.py`, `_min_call_interval` defaulted to 13.0 seconds if `GEMINI_MIN_INTERVAL_S` was unset. When deploying to Agent37 sandbox via `infra/sandbox_deploy.py`, `GEMINI_MIN_INTERVAL_S` was omitted from `/home/node/.trustfall/worker.env`. Every worker step was forced to sleep for at least 13 seconds before issuing an API call, and 26 seconds if any formatting retry occurred.
2. **REST Polling Transport Multi-Hop**: The live architecture involves 3 network hops across the BAND REST API:
   - Hop 1: Sender (Test Harness / Red) posts ticket to BAND room.
   - Hop 2: Dispatcher agent polls BAND, runs input gate screening, and forwards ticket.
   - Hop 3: Worker agent inside Agent37 sandbox polls BAND, processes ticket via Gemini, and posts worker report back to BAND.
   - Hop 4: Sender polling loop detects worker report.
   With polling loops set to 0.5s–1.0s, transport transit overhead alone is ~6.5–7.5 seconds across the 3 asynchronous REST handoffs.

---

## 2. Quantitative Baseline vs Post-Fix Comparison

### 2.1 Baseline (Before Fix: 13s Gemini Pacing Active)
- Room: `2259e40a-1833-49f4-b647-596ac09f99ea` (Old room, 580+ msgs)
- 5 Sequential Benign Tickets:
  - `time-b01`: 32,002 ms (Timeout)
  - `time-b02`: 31,841 ms (Timeout)
  - `time-b03`: 32,758 ms (Timeout)
  - `time-b04`: 32,044 ms (Timeout)
  - `time-b05`: 31,829 ms (Timeout)
- **Timeouts:** 5 / 5 (100% failure rate at 30s deadline)

### 2.2 Post-Fix: Old Room (`GEMINI_MIN_INTERVAL_S=0`)
- Room: `2259e40a-1833-49f4-b647-596ac09f99ea`
- 5 Sequential Benign Tickets:
  - `post-b01`: 7,811 ms (Success, 0 timeouts)
  - `post-b02`: 7,484 ms (Success, 0 timeouts)
  - `post-b03`: 7,376 ms (Success, 0 timeouts)
  - `post-b04`: 8,346 ms (Success, 0 timeouts)
  - `post-b05`: 7,750 ms (Success, 0 timeouts)
- **Median Latency:** 7,750 ms (7.75s)
- **Timeouts:** 0 / 5 (0%)
- **Delta:** Worker execution dropped from 30+ seconds to < 1.0 second.

### 2.3 Post-Fix: Qualified Fresh Room (`GEMINI_MIN_INTERVAL_S=0`)
- Room: `0ff67f25-e8a4-42a5-a4ac-54d0c4ed727e`
- 5 Sequential Benign Tickets:
  - `fresh-b01`: 8,128 ms (Success, 0 timeouts)
  - `fresh-b02`: 8,551 ms (Success, 0 timeouts)
  - `fresh-b03`: 9,331 ms (Success, 0 timeouts)
  - `fresh-b04`: 8,096 ms (Success, 0 timeouts)
  - `fresh-b05`: 9,170 ms (Success, 0 timeouts)
- **Median Latency:** 8,551 ms
- **Timeouts:** 0 / 5 (0%)
- **Aggregate Post-Fix Timeouts across all 10 tickets:** **0 / 10 (0.0% failure rate)**

---

## 3. High-Resolution Internal Timeline Breakdown

From `/home/node/worker.log` high-resolution telemetry:

| Ticket ID | Patch Check | Memory Load | LLM Call (Gemini Flash Lite) | Report Post | Total Worker Processing |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `post-b01` | 0.1 ms | 0.8 ms | 634.7 ms | 52.3 ms | **687.9 ms** |
| `post-b02` | 0.1 ms | 0.3 ms | 797.5 ms | 55.5 ms | **853.4 ms** |
| `post-b03` | 0.1 ms | 0.2 ms | 559.0 ms | 46.8 ms | **606.1 ms** |
| `post-b04` | 0.1 ms | 0.2 ms | 516.3 ms | 48.6 ms | **565.2 ms** |
| `post-b05` | 0.1 ms | 0.3 ms | 658.4 ms | 50.4 ms | **709.2 ms** |
| `fresh-b01` | 0.1 ms | 0.3 ms | 851.2 ms | 41.9 ms | **893.5 ms** |
| `fresh-b02` | 0.1 ms | 0.1 ms | 880.8 ms | 41.2 ms | **922.2 ms** |
| `fresh-b03` | 0.1 ms | 0.3 ms | 628.7 ms | 35.0 ms | **664.1 ms** |
| `fresh-b04` | 0.1 ms | 0.3 ms | 913.9 ms | 44.0 ms | **958.3 ms** |
| `fresh-b05` | 0.1 ms | 0.3 ms | 1061.8 ms | 33.6 ms | **1095.8 ms** |

**Conclusion:** Worker core and model inference are sub-second (~600–1000 ms). Total round-trip time is dominated by BAND REST polling intervals across the multi-agent chain.

---

## 4. Prompt Context & Chat History Verification

**Hypothesis Tested:** Does the BAND SDK or Worker agent attach room message history into the Gemini prompt context, causing ballooning prompt sizes?

**Findings:**
- **Prompt Isolation:** `agents/worker_core.py` builds prompt context strictly from:
  1. Base system instructions (`worker_system_victim.md`)
  2. Secret canary string
  3. Internal memory notes (`data/worker_state/memory.json`)
  4. The isolated incoming ticket payload.
- Message history from the BAND room is **never** injected into the LLM prompt. Context size remains strictly invariant regardless of room age or message volume.
- Network payload differences between old room (580+ msgs) and fresh room (0 msgs) on single-page fetch (`limit=100`):
  - In fresh room: Polling overhead is minimal and room listing returns quickly.

---

## 5. Validated Latency Budget for Live Demo

For live video and demo execution:
- **Single-turn timeout deadline:** 30.0s is safe; recommend setting `TICKET_TIMEOUT_S=35.0` to accommodate cloud network jitter.
- **Worker compute budget:** 1.0s.
- **BAND transport budget (3 REST hops):** 6.5s – 8.0s.
- **Expected demo turn latency:** 7.5s – 8.5s per ticket.
