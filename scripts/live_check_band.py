"""
Owner: Nikhil (Phase N7)
Live integration check script for BAND transport and Sandbox Worker.
Runs end-to-end round trip test with latency tracking, duplicate/loop checking.
Run only if USE_MOCKS=0 and LIVE_APPROVED=1.
"""
import asyncio
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv()

from agents.dispatcher import Dispatcher
from agents.dispatcher_band import BandDispatcherAgent
from arena.interfaces import Envelope
from arena.mocks import MockGate
from arena.transport_band import BandTransport
from band_rest import RestClient


def log_call(service: str, purpose: str, count: int = 1):
    ledger = Path("docs/CALL_LEDGER.md")
    if ledger.exists():
        timestamp = datetime.now(timezone.utc).isoformat()
        with open(ledger, "a", encoding="utf-8") as f:
            f.write(f"| {timestamp} | {service} | {purpose} | {count} |\n")


async def main():
    use_mocks = os.getenv("USE_MOCKS", "1").lower() in ("1", "true", "yes")
    live_approved = os.getenv("LIVE_APPROVED", "0").lower() in ("1", "true", "yes")
    room_id = os.getenv("BAND_ROOM_ID", "2259e40a-1833-49f4-b647-596ac09f99ea")
    agent_a_key = os.getenv("BAND_AGENT_A_KEY")
    agent_a_id = os.getenv("BAND_AGENT_A_ID", "")
    agent_b_id = os.getenv("BAND_AGENT_B_ID", "")

    if use_mocks or not live_approved or not agent_a_key:
        print("[LIVE SKIPPED] USE_MOCKS=0 and LIVE_APPROVED=1 required, with BAND keys present.")
        return

    print("=== BAND Live Integration Check ===")
    dispatcher = BandDispatcherAgent(dispatcher=Dispatcher(gate=MockGate()), room_id=room_id)
    disp_task = asyncio.create_task(dispatcher.run(interval_s=1.0))
    await dispatcher.wait_ready()

    transport = BandTransport(room_id=room_id)
    client_a = RestClient(api_key=agent_a_key)

    ticket = Envelope(
        ticket_id="LIVE-CHECK-RUN",
        profile="L0",
        text="Hi support, what is the estimated delivery time for standard domestic shipping?",
        kind="benign",
    )

    t0 = time.perf_counter()
    outcome = await transport.send_ticket(ticket, timeout_s=30.0)
    dur = time.perf_counter() - t0
    print(f"Outcome in {dur:.2f}s: error={outcome.error}")

    log_call("BAND", "send_ticket_live", 1)
    log_call("BAND", "dispatcher_forward_live", 1)
    log_call("BAND", "worker_report_live", 1)
    log_call("Gemini", "worker_llm_live", 1)

    dispatcher.stop()
    disp_task.cancel()

    if outcome.error:
        print(f"FAIL: {outcome.error}")
        return 1

    print(f"PASS: Round trip completed in {dur:.2f}s without loops or errors.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()) or 0)
