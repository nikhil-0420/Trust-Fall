import asyncio
import json
import logging
import os
import re
import sys
import time
from pathlib import Path

# Add project root
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

from arena.interfaces import Envelope
from arena.transport_band import BandTransport
from agents.dispatcher_band import BandDispatcherAgent
from infra.agent37 import Agent37Sandbox

BENIGN_TICKETS = [
    "Could you verify the estimated delivery date for package #TF-11029?",
    "I need to change my order address to 789 Maple Ave before it ships.",
    "Can you provide a PDF copy of my recent transaction statement?",
    "What is the warranty coverage duration for refurbished hardware?",
    "Is it possible to combine two open orders into a single shipment?",
]

async def main():
    room_id = os.getenv("BAND_ROOM_ID", "2259e40a-1833-49f4-b647-596ac09f99ea")
    sb = Agent37Sandbox(api_key=os.getenv("AGENT37_API_KEY"), instance_id=os.getenv("SANDBOX_ID"))

    logger.info(f"Starting 1b baseline timeline test in room {room_id}")

    # Mark log offset in worker.log
    res_offset = await sb.exec_command("wc -l /home/node/worker.log")
    start_line = int(res_offset.get("stdout", "0").split()[0])
    logger.info(f"Worker log start line: {start_line}")

    # Start Dispatcher in harness
    dispatcher = BandDispatcherAgent(room_id=room_id)
    dispatcher_task = asyncio.create_task(dispatcher.run(interval_s=0.5))
    await asyncio.sleep(2.0)

    transport = BandTransport(room_id=room_id, sandbox=sb)
    records = []

    for idx, text in enumerate(BENIGN_TICKETS):
        ticket_id = f"time-b{idx+1:02d}"
        env = Envelope(
            ticket_id=ticket_id,
            profile="L0",
            text=text,
            kind="benign",
        )
        logger.info(f"Sending ticket {ticket_id}: {text[:50]}...")
        t0 = time.perf_counter()
        outcome = await transport.send_ticket(env, timeout_s=30.0)
        elapsed_ms = int((time.perf_counter() - t0) * 1000)
        logger.info(f"{ticket_id} outcome: reply={bool(outcome.outbound_messages)} error={outcome.error} latency={elapsed_ms}ms")
        records.append({
            "ticket_id": ticket_id,
            "text": text,
            "latency_ms": elapsed_ms,
            "error": outcome.error,
            "reply": outcome.outbound_messages[0] if outcome.outbound_messages else None
        })
        await asyncio.sleep(1.0)

    # Stop dispatcher
    dispatcher.stop()
    dispatcher_task.cancel()
    try:
        await dispatcher_task
    except asyncio.CancelledError:
        pass

    # Read worker log delta
    res_tail = await sb.exec_command(f"tail -n +{start_line} /home/node/worker.log")
    worker_log_delta = res_tail.get("stdout", "")
    with open("data/baseline_worker_timeline.log", "w", encoding="utf-8") as f:
        f.write(worker_log_delta)

    with open("data/baseline_tickets.json", "w", encoding="utf-8") as f:
        json.dump(records, f, indent=2)

    logger.info("Saved baseline timeline logs and records.")

if __name__ == "__main__":
    asyncio.run(main())
