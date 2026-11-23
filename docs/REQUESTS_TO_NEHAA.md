# Requests to Nehaa

Requests from Nikhil for changes to Nehaa-owned files or components.

---
- `2026-11-22T17:49:00Z` [Setup / scripts/tunnel.py] Added `get_cloudflared_path()` to search `CLOUDFLARED_PATH` env var, `PATH`, and `tools/cloudflared.exe` sequentially before showing install instructions. Preserved all tunnel execution logic.
- `2026-11-22T18:10:00Z` [Run / scripts/run_full.py] Added `--timeout` (default 20.0s), `--attacks-per-round` (default 4), `--benign-count` (default 5) options and fixed `Referee` instantiation to pass `events=events` and `budget=budget`. Added automated `BandDispatcherAgent` runner for `TRANSPORT=band` live runs.
- `2026-11-22T18:13:00Z` [Budget / api/budget.py] Added `can_spend(kind, count)` method to `Budget` class called by `arena/rounds.py:60` to check budget threshold without premature deduction.
- `2026-11-22T19:27:00Z` [Gate Cache Provenance / api/gate.py] Added implementation tagging (`impl: "lyzr" | "mock"`) to cache keys and serialized entries. Real runs (`USE_MOCKS=0`) now ignore untagged or mock-tagged cache entries to prevent mock test results from masquerading as live Lyzr detector hits.
- `2026-11-23T04:38:00Z` [Reports Fallback / api/main.py] Updated `get_report` to dynamically fall back to generating markdown from `data/mock/results.json` when `data/reports/` is missing (due to quarantine of invalid runs), matching the fallback behavior of `/api/results` and `/api/events`.
