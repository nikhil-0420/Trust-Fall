# BAND Transport Demo Qualification Status

**Status:** `BAND PATH VERIFIED`  
**Verified Demo Room:** `2259e40a-1833-49f4-b647-596ac09f99ea` (Old Room)  
**Qualification Date:** 2026-11-24T12:39:18+05:30  
**Qualification Test:** Test A (5/5 sequential benign customer support tickets)  

---

## Qualification Summary

- **Success Rate:** `5/5` replies received (`100%`)
- **Timeouts:** `0/5` (`0%`)
- **Average Latency:** `9,769.6 ms` (~9.8s per ticket roundtrip)
- **Room Message Delta:** 561 messages -> 571 messages (exactly 5 inbound tickets + 5 worker outbound reports)
- **Sender Breakdown:**
  - Worker Agent (`b883bc3f...`): 185 -> 190 messages (+5)
  - Red / Dispatcher Agent (`acfa6e7d...`): 376 -> 381 messages (+5)

## Demo Readiness
The BAND real transport with sandbox worker (`<SANDBOX_ID>`) is verified operational for demo recording and live verification walkthroughs.
