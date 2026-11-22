# Requests to Nehaa

Requests from Nikhil for changes to Nehaa-owned files or components.

---
- `2026-11-22T17:49:00Z` [Setup / scripts/tunnel.py] Added `get_cloudflared_path()` to search `CLOUDFLARED_PATH` env var, `PATH`, and `tools/cloudflared.exe` sequentially before showing install instructions. Preserved all tunnel execution logic.
- `2026-11-22T18:10:00Z` [Run / scripts/run_full.py] Added `--timeout` (default 20.0s), `--attacks-per-round` (default 4), `--benign-count` (default 5) options and fixed `Referee` instantiation to pass `events=events` and `budget=budget`. Added automated `BandDispatcherAgent` runner for `TRANSPORT=band` live runs.
- `2026-11-22T18:13:00Z` [Budget / api/budget.py] Added `can_spend(kind, count)` method to `Budget` class called by `arena/rounds.py:60` to check budget threshold without premature deduction.
