# Questions (Nikhil)

Entries logged by Nikhil during execution when an assumption is made. Format:
`[UTC timestamp] [Phase/Task] Question | Assumption made | How to reverse`

---
- `2026-11-22T15:52:00Z` [Phase N3 / N3.4] Which identity should BandTransport use to post benign tickets? | Assumed BandTransport sends benign tickets using the same RED sender identity in the shared BAND room because BAND room access is keyed by registered agent credentials, and RED credentials represent the test harness sender. | Configure an independent test/customer identity or Dispatcher self-ticket in `arena/transport_band.py`.

