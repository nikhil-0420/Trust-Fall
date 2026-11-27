"""
scripts/measure_10_hops.py
Measures per-hop timing for 10 sequential benign tickets over BAND in the qualified room.
Captures:
- Local timestamps: send start, dispatcher start/end, transport detection
- Server-side created_at: ticket, forward, report messages from BAND REST API
- Worker timeline: receive, LLM start/end, report post from worker.log
Computes per-hop breakdown.
"""
import asyncio
import datetime
import json
import logging
import os
import re
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

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

from arena.interfaces import Envelope
from arena.transport_band import BandTransport
from agents.dispatcher_band import BandDispatcherAgent
from infra.agent37 import Agent37Sandbox
from arena.benign import BENIGN_TICKETS

async def get_worker_log_tail(sb: Agent37Sandbox, lines: int = 60) -> str:
    res = await sb.exec_command(f"tail -n {lines} /home/node/worker.log 2>/dev/null || true")
    return res.get("stdout", "")

async def measure_10_tickets(output_path: str, poll_interval_s: float = 0.2):
    room_id = os.getenv("BAND_ROOM_ID", "0ff67f25-e8a4-42a5-a4ac-54d0c4ed727e")
    sb = Agent37Sandbox(api_key=os.getenv("AGENT37_API_KEY"), instance_id=os.getenv("SANDBOX_ID"))

    # Set env var
    os.environ["BAND_POLL_INTERVAL_S"] = str(poll_interval_s)

    dispatcher = BandDispatcherAgent(room_id=room_id)
    # Monkey-patch dispatcher to record exact local timestamps
    dispatcher_events = {}

    orig_process = dispatcher._process_ticket_message
    async def instrumented_process(content):
        t_recv = time.time()
        # Find ticket id
        m = re.search(r'\[TICKET:([^\]]+)\]', content)
        tid = m.group(1) if m else "unknown"
        dispatcher_events[tid] = {"t_disp_recv": t_recv}
        await orig_process(content)
        dispatcher_events[tid]["t_disp_post"] = time.time()

    dispatcher._process_ticket_message = instrumented_process

    dispatcher_task = asyncio.create_task(dispatcher.run(interval_s=poll_interval_s))
    await asyncio.sleep(2.0)

    transport = BandTransport(room_id=room_id, sandbox=sb)

    tickets_to_run = BENIGN_TICKETS[:10]
    records = []

    logger.info(f"=== Starting 10-ticket Hop Measurement (poll={poll_interval_s}s) ===")

    for idx, ticket in enumerate(tickets_to_run, 1):
        tid = f"hop-{ticket['id']}"
        env = Envelope(
            ticket_id=tid,
            profile="L0",
            text=ticket["text"],
            kind="benign",
        )

        t_send_start = time.time()
        t_perf_start = time.perf_counter()

        # Send ticket
        outcome = await transport.send_ticket(env, timeout_s=45.0)

        t_detected = time.time()
        roundtrip_ms = int((time.perf_counter() - t_perf_start) * 1000)

        disp_ev = dispatcher_events.get(tid, {})
        t_disp_recv = disp_ev.get("t_disp_recv")
        t_disp_post = disp_ev.get("t_disp_post")

        # Now query BAND server messages to get server-side created_at for all 3 messages
        messages = transport._fetch_room_messages(max_pages=2)
        ticket_msg = None
        forward_msg = None
        report_msg = None

        for m in messages:
            content = getattr(m, "content", "")
            if tid in content:
                if "[Worker Report]" in content or "Report" in content:
                    report_msg = m
                elif "agent-b" in content or "Worker" in content:
                    forward_msg = m
                elif "agent-a" in content or "Dispatcher" in content:
                    ticket_msg = m

        server_ticket_created = getattr(ticket_msg, "created_at", None) if ticket_msg else None
        server_forward_created = getattr(forward_msg, "created_at", None) if forward_msg else None
        server_report_created = getattr(report_msg, "created_at", None) if report_msg else None

        # Fetch worker log timeline from sandbox
        log_tail = await get_worker_log_tail(sb, lines=40)
        # Parse timeline entries for this ticket
        # Worker message received: msg_id=... at <ts>
        # Worker LLM call start ticket=... at <ts>
        # Worker LLM call end ticket=... at <ts>
        # Worker report posted: msg_id=... at <ts>
        worker_ev = {}
        for line in log_tail.splitlines():
            if tid in line or "[TIMELINE]" in line:
                if "Worker message received" in line:
                    m = re.search(r'at ([\d\.]+)', line)
                    if m: worker_ev["t_worker_recv"] = float(m.group(1))
                elif "Worker LLM call start" in line and tid in line:
                    m = re.search(r'at ([\d\.]+)', line)
                    if m: worker_ev["t_llm_start"] = float(m.group(1))
                elif "Worker LLM call end" in line and tid in line:
                    m = re.search(r'at ([\d\.]+)', line)
                    if m: worker_ev["t_llm_end"] = float(m.group(1))
                elif "Worker report posted" in line:
                    m = re.search(r'at ([\d\.]+)', line)
                    if m: worker_ev["t_worker_post"] = float(m.group(1))

        rec = {
            "ticket_id": ticket["id"],
            "tid": tid,
            "roundtrip_ms": roundtrip_ms,
            "passed": not bool(outcome.error) and len(outcome.outbound_messages) == 1,
            "timestamps": {
                "t_send_start": t_send_start,
                "t_disp_recv": t_disp_recv,
                "t_disp_post": t_disp_post,
                "t_detected": t_detected,
                "server_ticket_created": server_ticket_created,
                "server_forward_created": server_forward_created,
                "server_report_created": server_report_created,
                "worker_timeline": worker_ev,
            }
        }
        logger.info(f"[{idx}/10] {ticket['id']}: roundtrip={roundtrip_ms}ms, disp_wait={round((t_disp_recv - t_send_start)*1000) if t_disp_recv else 'N/A'}ms")
        records.append(rec)
        await asyncio.sleep(0.5)

    dispatcher.stop()
    dispatcher_task.cancel()
    try:
        await dispatcher_task
    except asyncio.CancelledError:
        pass

    latencies = [r["roundtrip_ms"] for r in records if r["roundtrip_ms"] > 0]
    import statistics

    sorted_lat = sorted(latencies)
    median_lat = float(statistics.median(latencies)) if latencies else 0.0
    mean_lat = float(statistics.mean(latencies)) if latencies else 0.0
    idx_p90 = min(int(len(sorted_lat) * 0.9), len(sorted_lat) - 1)
    p90_lat = float(sorted_lat[idx_p90]) if latencies else 0.0

    summary = {
        "poll_interval_s": poll_interval_s,
        "total": len(records),
        "passed": sum(1 for r in records if r["passed"]),
        "errors": sum(1 for r in records if not r["passed"]),
        "median_latency_ms": round(median_lat, 1),
        "mean_latency_ms": round(mean_lat, 1),
        "p90_latency_ms": round(p90_lat, 1),
        "records": records,
    }

    Path(output_path).write_text(json.dumps(summary, indent=2), encoding="utf-8")
    logger.info(f"Saved hop measurements to {output_path}: Median={median_lat:.1f}ms, p90={p90_lat:.1f}ms, errors={summary['errors']}")
    return summary

if __name__ == "__main__":
    out_file = sys.argv[1] if len(sys.argv) > 1 else "data/latency_10_tickets_before.json"
    interval = float(sys.argv[2]) if len(sys.argv) > 2 else 0.2
    asyncio.run(measure_10_tickets(out_file, poll_interval_s=interval))
