# BAND Transport Demo Qualification Status

**Status:** `BAND PATH VERIFIED & OPTIMIZED`  
**Qualified Fresh Demo Room:** `0ff67f25-e8a4-42a5-a4ac-54d0c4ed727e`  
**Legacy Fallback Room:** `2259e40a-1833-49f4-b647-596ac09f99ea`  
**Qualification Date:** 2026-11-24T16:28:00+05:30  
**Qualification Test:** 10 Post-Fix Tickets (5 Old Room + 5 Fresh Room)  

---

## Qualification Summary

- **Total Post-Fix Tickets Tested:** 10
- **Total Success Rate:** `10/10` (`100%`)
- **Total Timeouts:** `0/10` (`0%`)
- **Worker Internal Processing Time:** ~600ms – 1000ms (sub-second model inference & handling)
- **Fresh Room Median Round-Trip Latency:** `8,551 ms`
- **Old Room Median Round-Trip Latency:** `7,750 ms`
- **Validated Latency Budget:** 7.5s – 8.5s round trip; recommended timeout setting `TICKET_TIMEOUT_S=35.0s`.

## Architecture & Optimizations Applied
- `GEMINI_MIN_INTERVAL_S=0` configured in `/home/node/.trustfall/worker.env`, cutting out artificial 13-second pacing delay.
- Rest loop in `BandWorkerAgent` runs every 1.0s, Dispatcher loop runs every 0.5s.
- Participant registry fully synced in fresh room across all 5 agents (Worker, Dispatcher, Red, Blue, Analyst).

## Demo Readiness
The BAND real transport with sandbox worker (`<SANDBOX_ID>`) in fresh room `0ff67f25-e8a4-42a5-a4ac-54d0c4ed727e` is verified and ready for live video demonstration.
