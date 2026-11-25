"""
scripts/verify_20_benign_l0.py
Executes all 20 calibrated benign tickets ONCE over the real BAND + Agent37 transport at L0.
Measures pass rate, latency, memory utility preservation, and trigger word handling.
"""
import asyncio
import datetime
import json
import logging
import os
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from dotenv import load_dotenv
load_dotenv()

os.environ["LIVE_APPROVED"] = "1"
os.environ["LLM_DAILY_CAP"] = "100000000"
os.environ["LYZR_DAILY_CAP"] = "100000000"
os.environ["BAND_POLL_INTERVAL_S"] = "0.2"

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

from arena.interfaces import Envelope
from arena.transport_band import BandTransport
from agents.dispatcher_band import BandDispatcherAgent
from infra.agent37 import Agent37Sandbox
from arena.benign import BENIGN_TICKETS, is_benign_passed

def log_ledger(service: str, purpose: str, count: int = 1):
    ledger = Path("docs/CALL_LEDGER.md")
    if ledger.exists():
        timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
        with open(ledger, "a", encoding="utf-8") as f:
            f.write(f"| {timestamp} | {service} | {purpose} | {count} |\n")

async def main():
    room_id = os.getenv("BAND_ROOM_ID", "0ff67f25-e8a4-42a5-a4ac-54d0c4ed727e")
    sb = Agent37Sandbox(api_key=os.getenv("AGENT37_API_KEY"), instance_id=os.getenv("SANDBOX_ID"))

    # Start Dispatcher in harness with 0.2s interval
    dispatcher = BandDispatcherAgent(room_id=room_id)
    dispatcher_task = asyncio.create_task(dispatcher.run(interval_s=0.2))
    await asyncio.sleep(2.0)

    transport = BandTransport(room_id=room_id, sandbox=sb)
    records = []

    logger.info(f"=== Starting 20-ticket benign calibration over real BAND transport at L0 ===")
    
    passed_count = 0
    mem_total = 0
    mem_passed = 0
    trig_total = 0
    trig_passed = 0

    for idx, ticket in enumerate(BENIGN_TICKETS):
        ticket_id = f"calib-b{idx+1:02d}-{ticket['id']}"
        cat = ticket.get("category")
        exp_kw = ticket.get("expected_keyword")
        is_mem = (cat == "memory_utility")
        is_trig = (cat == "trigger_word")

        if is_mem:
            mem_total += 1
        elif is_trig:
            trig_total += 1

        # Reset memory state between tickets to evaluate clean utility
        try:
            await sb.reset_state(canary="CANARY-calib-benign-demo")
        except Exception as e:
            logger.warning(f"Failed to reset sandbox state: {e}")

        env = Envelope(
            ticket_id=ticket_id,
            profile="L0",
            text=ticket["text"],
            kind="benign",
        )

        logger.info(f"[{idx+1}/20] Sending {ticket_id} ({cat}): {ticket['text'][:60]}...")
        t0 = time.perf_counter()
        outcome = await transport.send_ticket(env, timeout_s=45.0)
        elapsed_ms = int((time.perf_counter() - t0) * 1000)

        passed = is_benign_passed(outcome, expected_keyword=exp_kw)
        if passed:
            passed_count += 1
            if is_mem:
                mem_passed += 1
            elif is_trig:
                trig_passed += 1

        reply = outcome.outbound_messages[0] if (outcome.outbound_messages and outcome.outbound_messages[0]) else None
        logger.info(f"{ticket_id}: passed={passed}, latency={elapsed_ms}ms, error={outcome.error}")
        log_ledger("Gemini", f"Benign calibration {ticket['id']}", 1)

        records.append({
            "ticket_id": ticket["id"],
            "category": cat,
            "text": ticket["text"],
            "expected_keyword": exp_kw,
            "latency_ms": elapsed_ms,
            "passed": passed,
            "error": outcome.error,
            "reply": reply,
            "memory_after": outcome.memory_after,
        })
        await asyncio.sleep(1.0)

    dispatcher.stop()
    dispatcher_task.cancel()
    try:
        await dispatcher_task
    except asyncio.CancelledError:
        pass

    latencies = [r["latency_ms"] for r in records if r["reply"]]
    timeouts = sum(1 for r in records if r["error"] == "timeout" or not r["reply"])
    import statistics
    mean_lat = statistics.mean(latencies) if latencies else 0
    median_lat = statistics.median(latencies) if latencies else 0

    summary = {
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "room_id": room_id,
        "total": len(records),
        "passed": passed_count,
        "pass_rate": round(passed_count / len(records), 3),
        "timeouts": timeouts,
        "mean_latency_ms": round(mean_lat, 1),
        "median_latency_ms": round(median_lat, 1),
        "memory_utility": {"total": mem_total, "passed": mem_passed, "rate": round(mem_passed / mem_total, 3) if mem_total else 0},
        "trigger_word": {"total": trig_total, "passed": trig_passed, "rate": round(trig_passed / trig_total, 3) if trig_total else 0},
        "tickets": records,
    }

    output_path = Path("data/benign_calibration_results.json")
    output_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print("\n================ BENIGN CALIBRATION SUMMARY ================")
    print(f"Total: {len(records)} | Passed: {passed_count} ({summary['pass_rate']*100:.1f}%) | Timeouts: {timeouts}")
    print(f"Latency: Median={median_lat:.1f}ms | Mean={mean_lat:.1f}ms")
    print(f"Memory Utility: {mem_passed}/{mem_total} ({summary['memory_utility']['rate']*100:.1f}%)")
    print(f"Trigger Words: {trig_passed}/{trig_total} ({summary['trigger_word']['rate']*100:.1f}%)")
    print("============================================================\n")

if __name__ == "__main__":
    asyncio.run(main())
