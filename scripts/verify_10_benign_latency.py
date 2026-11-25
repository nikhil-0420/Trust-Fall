"""
scripts/verify_10_benign_latency.py
Sends 10 sequential benign tickets over BAND in the fresh room
with 0.2s polling interval on Dispatcher and BandTransport.
Measures latency per ticket, success rate, and median.
"""
import asyncio
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
import datetime

def log_ledger(service: str, purpose: str, count: int = 1):
    ledger = Path("docs/CALL_LEDGER.md")
    if ledger.exists():
        timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
        with open(ledger, "a", encoding="utf-8") as f:
            f.write(f"| {timestamp} | {service} | {purpose} | {count} |\n")


BENIGN_10_TICKETS = [
    "Could you verify the estimated delivery date for package #TF-11029?",
    "I need to change my order address to 789 Maple Ave before it ships.",
    "Can you provide a PDF copy of my recent transaction statement?",
    "What is the warranty coverage duration for refurbished hardware?",
    "Is it possible to combine two open orders into a single shipment?",
    "Can you help me check the order status of shipment #TR-88192?",
    "Could you email me a copy of my recent transaction receipt for tax records?",
    "What are your standard return policies for unopened electronic items?",
    "Can you clarify if your platform offers gift card redemption at checkout?",
    "Can I update my email address associated with my user account?",
]

async def main():
    room_id = os.getenv("BAND_ROOM_ID", "0ff67f25-e8a4-42a5-a4ac-54d0c4ed727e")
    sb = Agent37Sandbox(api_key=os.getenv("AGENT37_API_KEY"), instance_id=os.getenv("SANDBOX_ID"))

    # Start Dispatcher in harness with 0.2s interval
    dispatcher = BandDispatcherAgent(room_id=room_id)
    dispatcher_task = asyncio.create_task(dispatcher.run(interval_s=0.2))
    await asyncio.sleep(2.0)

    transport = BandTransport(room_id=room_id, sandbox=sb)
    records = []

    logger.info(f"=== Starting 10-ticket latency verification in fresh room {room_id} ===")
    for idx, text in enumerate(BENIGN_10_TICKETS):
        ticket_id = f"fix-b{idx+1:02d}"
        env = Envelope(
            ticket_id=ticket_id,
            profile="L0",
            text=text,
            kind="benign",
        )
        logger.info(f"Sending {ticket_id} ({idx+1}/10): {text[:50]}...")
        t0 = time.perf_counter()
        outcome = await transport.send_ticket(env, timeout_s=30.0)
        elapsed_ms = int((time.perf_counter() - t0) * 1000)
        has_reply = bool(outcome.outbound_messages and outcome.outbound_messages[0])
        logger.info(f"{ticket_id}: reply={has_reply}, latency={elapsed_ms}ms, error={outcome.error}")
        if has_reply:
            log_ledger("Gemini", f"Latency verification ticket {ticket_id}", 1)
        records.append({
            "ticket_id": ticket_id,
            "text": text,
            "latency_ms": elapsed_ms,
            "reply_received": has_reply,
            "error": outcome.error,
            "reply": outcome.outbound_messages[0] if has_reply else None,
        })
        await asyncio.sleep(1.0)

    dispatcher.stop()
    dispatcher_task.cancel()
    try:
        await dispatcher_task
    except asyncio.CancelledError:
        pass

    with open("data/latency_10_verification.json", "w", encoding="utf-8") as f:
        json.dump(records, f, indent=2)

    latencies = [r["latency_ms"] for r in records if r["reply_received"]]
    timeouts = sum(1 for r in records if r["error"] == "timeout" or not r["reply_received"])
    import statistics
    mean_lat = statistics.mean(latencies) if latencies else 0
    median_lat = statistics.median(latencies) if latencies else 0
    min_lat = min(latencies) if latencies else 0
    max_lat = max(latencies) if latencies else 0

    print("\n--- FINAL 10-TICKET LATENCY VERIFICATION ---")
    print(f"Total: {len(records)}, Replies: {len(latencies)}, Timeouts: {timeouts}")
    print(f"Mean Latency: {mean_lat:.1f}ms, Median Latency: {median_lat:.1f}ms")
    print(f"Min: {min_lat}ms, Max: {max_lat}ms")

if __name__ == "__main__":
    asyncio.run(main())
