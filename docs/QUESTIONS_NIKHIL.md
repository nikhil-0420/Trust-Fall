# Questions (Nikhil)

Entries logged by Nikhil during execution when an assumption is made. Format:
`[UTC timestamp] [Phase/Task] Question | Assumption made | How to reverse`

---
- `2026-11-22T15:52:00Z` [Phase N3 / N3.4] Which identity should BandTransport use to post benign tickets? | Assumed BandTransport sends benign tickets using the same RED sender identity in the shared BAND room because BAND room access is keyed by registered agent credentials, and RED credentials represent the test harness sender. | Configure an independent test/customer identity or Dispatcher self-ticket in `arena/transport_band.py`.

- `2026-11-22T18:05:00Z` [Phase H8 / Preflight] `data/budget.json` contained committed mock usage (`lyzr_used: 21, lyzr_cap: 15`) while `CALL_LEDGER.md` had 0 real Lyzr calls. Planned full run (16 calls) would exceed 15 cap. | Assumed per instructions: shrank run to `ATTACKS_PER_ROUND=4, BENIGN_COUNT=5` so live Lyzr calls stay <= 15 cap; aligned `data/budget.json` to 1 call (smoke test) and cap 15 so live detector calls can execute cleanly without artificial governor abort. | Revert `data/budget.json` and run parameters if higher quota is available.
