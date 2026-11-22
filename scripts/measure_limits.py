#!/usr/bin/env python3
"""
scripts/measure_limits.py
Measures API latency, rate limits, and quota headers for Google Gemini.
Cap: 8 Gemini calls total, spaced 1.5s apart.
Only runs if USE_MOCKS=0, LIVE_APPROVED=1, and GEMINI_API_KEY is present.
Writes results to docs/LIMITS.md.
Owner: Nehaa (WS-D D1)
"""
import asyncio
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

repo_root = Path(__file__).resolve().parent.parent
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

TEMPLATE = """# Trust Fall — API Quotas, Latency & Limits

**Last Updated:** {timestamp}  
**Status:** {status}

---

## 1. Observed Automated Measurements

{measurements}

---

## 2. Human Verification & Account Quotas Template

The human operator must review and confirm the following values from external dashboards:

### Google AI Studio (Gemini)
- **Model Name:** `{model_name}`
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
- **`LLM_DAILY_CAP`:** {llm_cap} (recommended ~150-200 to safely buffer below daily limits)
- **`LYZR_DAILY_CAP`:** {lyzr_cap} (recommended ~15-20 to preserve shared team credits)
"""


async def measure():
    use_mocks = os.getenv("USE_MOCKS", "1").strip().lower() in {"1", "true", "yes"}
    live_approved = os.getenv("LIVE_APPROVED", "0").strip() == "1"
    gemini_key = os.getenv("GEMINI_API_KEY", "").strip()
    model_name = os.getenv("MODEL_NAME", "gemini-3.5-flash-lite")

    limits_file = repo_root / "docs" / "LIMITS.md"
    now_str = datetime.now(timezone.utc).isoformat()

    if use_mocks or not live_approved or not gemini_key:
        print("[*] LIVE SKIPPED (not approved or GEMINI_API_KEY unset). Writing limits template.")
        content = TEMPLATE.format(
            timestamp=now_str,
            status="LIVE SKIPPED (Mocks enabled / not approved)",
            measurements="Automated live probing skipped per autonomy rules (`USE_MOCKS=1`, `LIVE_APPROVED=0`).",
            model_name=model_name,
            llm_cap="200",
            lyzr_cap="15",
        )
        limits_file.write_text(content, encoding="utf-8")
        return

    import httpx

    print(f"[*] Running live limit probe for {model_name} (cap 8 calls, 1.5s interval)...")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={gemini_key}"

    results_log = []
    headers_seen = {}

    for i in range(1, 9):
        prompt_payload = {"contents": [{"parts": [{"text": f"Ping test #{i}: reply 'pong'"}]}]}
        t0 = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.post(url, json=prompt_payload)
            elapsed_ms = int((time.perf_counter() - t0) * 1000)

            for h, v in res.headers.items():
                if any(k in h.lower() for k in ("ratelimit", "quota", "retry")):
                    headers_seen[h] = v

            results_log.append(f"- Call {i}: Status {res.status_code}, Latency {elapsed_ms}ms")
        except Exception as e:
            results_log.append(f"- Call {i}: Error {type(e).__name__}")

        if i < 8:
            await asyncio.sleep(1.5)

    headers_str = "\n".join(f"  - `{k}`: `{v}`" for k, v in headers_seen.items()) or "  - None reported"
    measurements = (
        "### Probe Calls:\n"
        + "\n".join(results_log)
        + "\n\n### Quota Response Headers:\n"
        + headers_str
    )

    content = TEMPLATE.format(
        timestamp=now_str,
        status="LIVE COMPLETED (8 probe calls executed)",
        measurements=measurements,
        model_name=model_name,
        llm_cap="200",
        lyzr_cap="15",
    )
    limits_file.write_text(content, encoding="utf-8")
    print(f"[*] Successfully wrote {limits_file}")


if __name__ == "__main__":
    asyncio.run(measure())
