# Requests to Nehaa

Requests from Nikhil for changes to Nehaa-owned files or components.

---
- `2026-11-22T17:49:00Z` [Setup / scripts/tunnel.py] Added `get_cloudflared_path()` to search `CLOUDFLARED_PATH` env var, `PATH`, and `tools/cloudflared.exe` sequentially before showing install instructions. Preserved all tunnel execution logic.
- `2026-11-22T18:10:00Z` [Run / scripts/run_full.py] Added `--timeout` (default 20.0s), `--attacks-per-round` (default 4), `--benign-count` (default 5) options and fixed `Referee` instantiation to pass `events=events` and `budget=budget`. Added automated `BandDispatcherAgent` runner for `TRANSPORT=band` live runs.
- `2026-11-22T18:13:00Z` [Budget / api/budget.py] Added `can_spend(kind, count)` method to `Budget` class called by `arena/rounds.py:60` to check budget threshold without premature deduction.
- `2026-11-22T19:27:00Z` [Gate Cache Provenance / api/gate.py] Added implementation tagging (`impl: "lyzr" | "mock"`) to cache keys and serialized entries. Real runs (`USE_MOCKS=0`) now ignore untagged or mock-tagged cache entries to prevent mock test results from masquerading as live Lyzr detector hits.
- `2026-11-23T04:38:00Z` [Reports Fallback / api/main.py] Updated `get_report` to dynamically fall back to generating markdown from `data/mock/results.json` when `data/reports/` is missing (due to quarantine of invalid runs), matching the fallback behavior of `/api/results` and `/api/events`.
- `2026-11-23T04:48:00Z` [Multi-Step Attacks / arena/rounds.py & arena/transport_loopback.py] Added sequential multi-step execution in `arena/rounds.py` when `attack.steps` is provided. Sequentially delivers steps without resetting sandbox state, screens each step at L1/L2, and judges after final step. Added `reset_state(canary)` to `LoopbackTransport` to clear state between attacks while preserving state across sequential steps within an attack.
- `2026-11-23T07:37:00Z` [Gate Circuit Breaker / api/gate.py] Added consecutive error counter to `LyzrGate` that raises `RuntimeError("INVALID-GATE: 3 consecutive REAL Lyzr calls returned ERROR")` if 3 consecutive live Lyzr API requests return non-200 or timeout, ensuring runs fail closed without masking credit exhaustion or outages.
- `2026-11-23T11:58:00Z` [Hot-Reload Patch Delivery / arena/rollback.py & arena/referee.py] Removed `await referee.sandbox.restart()` from `apply_or_rollback` during patch proposal, rejection, and rollback. Patches and rollbacks are now delivered hot and verified via `patch_applied.json` without restarting the sandbox microVM, preventing worker process eviction during the Blue defense turn.
- `2026-11-23T12:35:00Z` [Pre-Round Liveness & Transport / arena/referee.py] Added `check_worker_liveness(round_id)` before R0, R1, and R2 (sends a 30s benign ping, redeploys once on failure, raises INVALID-WORKER if down), added `transport` attribute assignment to `Results`, and passed `attacks_per_round` dynamically to `self.red.attacks_per_round`.

### Request 2026-11-24: Paging support for BAND room message polling
- **Files Modified**: `arena/transport_band.py`, `agents/dispatcher_band.py`, `agents/worker_band.py`
- **Owner**: Nikhil
- **Summary**: Updated `_fetch_room_messages()` and `_fetch_messages()` to support cursor-based pagination with `max_pages` parameter. Prevents messages beyond the initial 100 limit from being dropped during high-volume test runs in long-lived rooms.

### Request 2026-11-24: Deterministic Patch Self-Test in Rollback Flow
- **Files Modified**: `arena/rollback.py`
- **Owner**: Nehaa (WS-C C4, C5) - additive edit by Nikhil
- **Summary**: Added `run_patch_self_test(patch_dict)` before benign regression testing. Tests whether candidate patch's `tool_policy.send_report.redact_patterns` successfully redacts 5 random canaries in the format `CANARY-<6 hex>-DEMO-ONLY`. If not, rejects the patch with reason "redaction does not cover the secret format" and requests an adjusted proposal from Blue.
