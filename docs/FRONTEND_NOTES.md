# Frontend Integration Notes

## 1. Mock Datasets (`data/mock/`)

The web UI reads mock files from `web/public/mock/` when `VITE_USE_MOCK=true`:

- `results.json`: Overall benchmark results across baseline (R0), gated (R1), and patched (R2) rounds. Contains ASR metrics, benign pass rates, patch history, and contagion statistics.
- `events-R0.json`: Detailed event trace stream for round R0 (messages, gate screening, agent state, judge decisions).
- `events-R1.json`: Event trace stream for round R1.
- `events-R2.json`: Event trace stream for round R2.
- `presets.json`: Pre-configured attack templates categorized for the interactive "Try-to-break-it" break page.
- `leaderboard.json`: Public community break attempts, submission counts, and shared exploits.

## 2. Syncing Mock Data to Web

To synchronize mock data files from the backend `data/mock/` directory to the frontend assets folder `web/public/mock/`:

```bash
python scripts/sync_mock_to_web.py
```

This copies all JSON files and ensures the frontend has identical contract structures for local development and offline mock demonstrations.

## 3. Real Results Ingestion

Once the live evaluation run completes:
- The actual execution results will be written by the Referee to `data/results.json` (and `data/events/*.jsonl`).
- The API serves real results at `GET /api/results` and SSE event streams at `GET /api/events/{round}`.
- Setting `VITE_USE_MOCK=false` in `web/.env` configures the frontend to query the live backend API rather than the static mock files.
