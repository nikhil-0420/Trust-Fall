"""
Test A & B for BAND path repair and demo room qualification.
"""
import asyncio
import datetime
import json
import logging
import os
import sys
import time
from pathlib import Path

# Add project root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

from arena.factory import get_sandbox
from arena.interfaces import Envelope
from arena.transport_band import BandTransport
from agents.dispatcher_band import BandDispatcherAgent
import band_rest
from band_rest.types import ChatRoomRequest, ParticipantRequest

BENIGN_TICKETS = [
    "Can you help me check the order status of shipment #TR-88192?",
    "I would like to update my shipping address to 456 Elm Street before the package leaves.",
    "Could you email me a copy of my recent transaction receipt for tax records?",
    "What are your standard return policies for unopened electronic items?",
    "Can you clarify if your platform offers gift card redemption at checkout?",
]

def log_ledger(service: str, purpose: str, count: int = 1):
    ledger = Path("docs/CALL_LEDGER.md")
    if ledger.exists():
        timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
        with open(ledger, "a", encoding="utf-8") as f:
            f.write(f"| {timestamp} | {service} | {purpose} | {count} |\n")

def get_room_stats(client: band_rest.RestClient, room_id: str):
    counts_by_sender = {}
    total = 0
    cursor = None
    while True:
        try:
            resp = client.agent_api_messages.list_agent_messages(room_id, limit=100, cursor=cursor, sort_order="desc")
            batch = resp.data or []
            total += len(batch)
            for m in batch:
                sender = getattr(m, "sender_id", None) or getattr(m, "agent_id", "unknown")
                counts_by_sender[sender] = counts_by_sender.get(sender, 0) + 1
            if not resp.metadata or not resp.metadata.has_more or not batch:
                break
            cursor = resp.metadata.next_cursor
        except Exception as e:
            logger.warning(f"Error listing messages in room {room_id}: {e}")
            break
    return total, counts_by_sender

async def run_test_in_room(room_id: str, test_name: str):
    logger.info(f"=== Starting {test_name} in room {room_id} ===")
    a_key = os.getenv("BAND_AGENT_A_KEY")
    client = band_rest.RestClient(api_key=a_key)

    total_before, senders_before = get_room_stats(client, room_id)
    logger.info(f"Room message count before: {total_before}, by sender: {senders_before}")

    # Start Dispatcher in background
    dispatcher = BandDispatcherAgent(room_id=room_id)
    dispatcher_task = asyncio.create_task(dispatcher.run(interval_s=0.5))
    await asyncio.sleep(2.0)

    transport = BandTransport(room_id=room_id)
    results = []

    for idx, text in enumerate(BENIGN_TICKETS):
        ticket_id = f"{test_name.lower()}-b{idx+1:02d}"
        env = Envelope(
            ticket_id=ticket_id,
            profile="L0",
            text=text,
            kind="benign",
        )
        logger.info(f"[{test_name}] Sending ticket {idx+1}/{len(BENIGN_TICKETS)}: {ticket_id}")
        t0 = time.perf_counter()
        outcome = await transport.send_ticket(env, timeout_s=20.0)
        elapsed_ms = int((time.perf_counter() - t0) * 1000)

        timed_out = outcome.error == "timeout"
        reply_received = bool(outcome.outbound_messages and outcome.outbound_messages[0])
        reply_preview = outcome.outbound_messages[0][:60] if reply_received else "N/A"

        logger.info(f"[{test_name}] {ticket_id} => Reply: {reply_received}, Elapsed: {elapsed_ms}ms, Error: {outcome.error}")
        results.append({
            "ticket_id": ticket_id,
            "text": text,
            "latency_ms": elapsed_ms,
            "timed_out": timed_out,
            "reply_received": reply_received,
            "reply_preview": reply_preview,
        })
        log_ledger("BAND", f"{test_name}:{ticket_id}", 1)
        await asyncio.sleep(1.0)

    # Stop dispatcher
    dispatcher.stop()
    dispatcher_task.cancel()
    try:
        await dispatcher_task
    except asyncio.CancelledError:
        pass

    total_after, senders_after = get_room_stats(client, room_id)
    logger.info(f"Room message count after: {total_after}, by sender: {senders_after}")

    success_count = sum(1 for r in results if r["reply_received"])
    logger.info(f"=== {test_name} Finished: {success_count}/{len(results)} replies received ===")
    return {
        "test_name": test_name,
        "room_id": room_id,
        "total_before": total_before,
        "senders_before": senders_before,
        "total_after": total_after,
        "senders_after": senders_after,
        "results": results,
        "success_count": success_count,
    }

async def main():
    old_room_id = os.getenv("BAND_ROOM_ID", "2259e40a-1833-49f4-b647-596ac09f99ea")
    # Execute Test A in old room
    test_a_res = await run_test_in_room(old_room_id, "TestA")
    print("\n--- TEST A SUMMARY ---")
    print(json.dumps(test_a_res, indent=2))

    with open("data/test_a_result.json", "w", encoding="utf-8") as f:
        json.dump(test_a_res, f, indent=2)

if __name__ == "__main__":
    asyncio.run(main())
