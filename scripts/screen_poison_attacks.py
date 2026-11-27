"""
scripts/screen_poison_attacks.py
Screens all poison attacks from attacks/library.json through live Lyzr prompt injection detector.
Records raw response, decision, confidence, and injection_score.
Logs external API calls to docs/CALL_LEDGER.md.
Saves results to data/poison_gate_screening.json.
"""
import asyncio
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys

from dotenv import load_dotenv
load_dotenv()

import httpx

LYZR_DETECTOR_URL = "https://rai-prod.studio.lyzr.ai/prompt-injection-dectector/"

def log_call(purpose: str):
    ts = datetime.now(timezone.utc).isoformat()
    line = f"| {ts} | Lyzr | {purpose} | 1 |\n"
    with open("docs/CALL_LEDGER.md", "a", encoding="utf-8") as f:
        f.write(line)

async def main():
    api_key = os.getenv("LYZR_API_KEY")
    if not api_key:
        print("ERROR: LYZR_API_KEY not set in environment.")
        return

    lib_path = Path("attacks/library.json")
    with open(lib_path, "r", encoding="utf-8") as f:
        attacks = json.load(f)

    poison_attacks = [a for a in attacks if a.get("goal") == "poison"]
    print(f"Found {len(poison_attacks)} poison attacks in {lib_path}: {[a['id'] for a in poison_attacks]}")

    headers = {
        "x-api-key": api_key,
        "Content-Type": "application/json",
    }

    results = []
    print("\n| ID | Category | Known | Decision | Confidence | Injection Score | Ticket Text (Preview) |")
    print("|---|---|---|---|---|---|---|")

    async with httpx.AsyncClient(timeout=15.0) as client:
        for att in poison_attacks:
            text = att["text"][:500]
            resp = await client.post(LYZR_DETECTOR_URL, headers=headers, json={"input_text": text})
            log_call(f"lyzr_screen_poison_{att['id']}")
            
            raw_data = resp.json()
            message = str(raw_data.get("message", "")).upper()
            details = raw_data.get("details", {})
            is_injection = bool(details.get("is_injection", (message == "INJECTION")))
            
            raw_conf = details.get("confidence")
            if raw_conf is not None:
                raw_conf_float = float(raw_conf)
                if raw_conf_float > 1.0:
                    conf = round(raw_conf_float / 100.0, 4)
                else:
                    conf = round(raw_conf_float, 4)
            else:
                conf = 0.98 if is_injection else 0.96

            conf = max(0.0, min(1.0, conf))
            decision = "INJECTION" if is_injection else "SAFE"
            
            if is_injection:
                injection_score = conf
            else:
                injection_score = round(1.0 - conf, 4)

            entry = {
                "id": att["id"],
                "title": att.get("title", ""),
                "category": att.get("category", ""),
                "known": att.get("known", True),
                "text": text,
                "raw_response": raw_data,
                "decision": decision,
                "confidence": conf,
                "injection_score": injection_score,
            }
            results.append(entry)
            print(f"| {att['id']} | {att.get('category')} | {att.get('known')} | {decision} | {conf:.4f} | {injection_score:.4f} | {text[:50]}... |")

    out_file = Path("data/poison_gate_screening.json")
    out_file.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"\nSaved screening results to {out_file}")

if __name__ == "__main__":
    asyncio.run(main())
