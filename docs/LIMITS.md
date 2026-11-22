# Trust Fall — API Quotas, Latency & Limits

**Last Updated:** 2026-11-22T16:43:00.482625+00:00  
**Status:** LIVE SKIPPED (Mocks enabled / not approved)

---

## 1. Observed Automated Measurements

Automated live probing skipped per autonomy rules (`USE_MOCKS=1`, `LIVE_APPROVED=0`).

---

## 2. Human Verification & Account Quotas Template

The human operator must review and confirm the following values from external dashboards:

### Google AI Studio (Gemini)
- **Model Name:** `gemini-3.5-flash-lite`
- **Tier:** Free Tier / Pay-as-you-go
- **Requests Per Minute (RPM) limit:** _____ RPM (default 15 RPM for Flash Lite)
- **Requests Per Day (RPD) limit:** _____ RPD (default 1,500 RPD)
- **Tokens Per Minute (TPM) limit:** _____ TPM (default 1,000,000 TPM)

### Lyzr AI Platform
- **Credits balance before 5 screening calls:** _____
- **Credits balance after 5 screening calls:** _____
- **Consumes platform credits?** Yes / No (Detector API is typically unbilled on standard plans)

---

## 3. Recommended Production Caps

Based on measurements and tier allocations:
- **`LLM_DAILY_CAP`:** 200 (recommended ~150-200 to safely buffer below daily limits)
- **`LYZR_DAILY_CAP`:** 15 (recommended ~15-20 to preserve shared team credits)
