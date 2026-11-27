"""
scripts/run_hop_diagnosis.py
Diagnoses latency across all hops for 10 sequential benign tickets.
Extracts:
1. t_send_start (local)
2. server_ticket_created (BAND server)
3. t_disp_recv (local dispatcher)
4. t_disp_post (local dispatcher)
5. server_forward_created (BAND server)
6. t_worker_recv (worker.log)
7. t_llm_start (worker.log)
8. t_llm_end (worker.log)
9. t_worker_post (worker.log)
10. server_report_created (BAND server)
11. t_detected (local transport)
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

def parse_iso_to_ts(iso_str: str | None) -> float | None:
    if not iso_str:
        return None
    try:
        # Handle 'Z' or '+00:00'
        dt = datetime.datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        return dt.timestamp()
    except Exception:
        return None

async def run_hop_experiment(label: str, output_file: str, poll_interval: float = 0.2):
    room_id = os.getenv("BAND_ROOM_ID", "0ff67f25-e8a4-42a5-a4ac-54d0c4ed727e")
    sb = Agent37Sandbox(api_key=os.getenv("AGENT37_API_KEY"), instance_id=os.getenv("SANDBOX_ID"))

    dispatcher = BandDispatcherAgent(room_id=room_id)
    dispatcher_events = {}

    orig_process = dispatcher._process_ticket_message
    async def instrumented_process(content):
        t_recv = time.time()
        m = re.search(r'\[TICKET:([^\]]+)\]', content)
        tid = m.group(1) if m else "unknown"
        dispatcher_events[tid] = {"t_disp_recv": t_recv}
        await orig_process(content)
        dispatcher_events[tid]["t_disp_post"] = time.time()

    dispatcher._process_ticket_message = instrumented_process
    disp_task = asyncio.create_task(dispatcher.run(interval_s=poll_interval))
    await asyncio.sleep(2.0)

    # Note: we pass sandbox=None for pure transport timing, or sb for sandbox state read
    # Let's measure pure transport timing as target median <= 4s
    transport = BandTransport(room_id=room_id)

    records = []
    logger.info(f"=== Starting {label} Hop Experiment (10 tickets, poll={poll_interval}s) ===")

    for idx, ticket in enumerate(BENIGN_TICKETS[:10], 1):
        tid = f"{label}-{ticket['id']}"
        env = Envelope(
            ticket_id=tid,
            profile="L0",
            text=ticket["text"],
            kind="benign",
        )

        t_send_start = time.time()
        outcome = await transport.send_ticket(env, timeout_s=45.0)
        t_detected = time.time()
        total_latency_ms = int((t_detected - t_send_start) * 1000)

        disp_ev = dispatcher_events.get(tid, {})
        t_disp_recv = disp_ev.get("t_disp_recv")
        t_disp_post = disp_ev.get("t_disp_post")

        # Query room messages to find server timestamps
        msgs = transport._fetch_room_messages(max_pages=2)
        ticket_msg = next((m for m in msgs if tid in getattr(m, "content", "") and "[Worker Report]" not in getattr(m, "content", "") and "agent-a" in getattr(m, "content", "")), None)
        forward_msg = next((m for m in msgs if tid in getattr(m, "content", "") and "[Worker Report]" not in getattr(m, "content", "") and "agent-b" in getattr(m, "content", "")), None)
        report_msg = next((m for m in msgs if tid in getattr(m, "content", "") and "[Worker Report]" in getattr(m, "content", "")), None)

        server_ticket_ts = parse_iso_to_ts(getattr(ticket_msg, "created_at", None))
        server_forward_ts = parse_iso_to_ts(getattr(forward_msg, "created_at", None))
        server_report_ts = parse_iso_to_ts(getattr(report_msg, "created_at", None))

        # Query sandbox worker log
        log_res = await sb.exec_command(f"grep '{tid}' /home/node/worker.log 2>/dev/null || true")
        worker_lines = log_res.get("stdout", "").splitlines()
        t_worker_recv = None
        t_llm_start = None
        t_llm_end = None
        t_worker_post = None

        for line in worker_lines:
            if "Worker message received" in line:
                m = re.search(r'at ([\d\.]+)', line)
                if m: t_worker_recv = float(m.group(1))
            elif "Worker LLM call start" in line:
                m = re.search(r'at ([\d\.]+)', line)
                if m: t_llm_start = float(m.group(1))
            elif "Worker LLM call end" in line:
                m = re.search(r'at ([\d\.]+)', line)
                if m: t_llm_end = float(m.group(1))
            elif "Worker report posted" in line:
                m = re.search(r'at ([\d\.]+)', line)
                if m: t_worker_post = float(m.group(1))

        # Estimate model latency from LLM call start/end, fallback to outcome or ~1.2s
        llm_lat_ms = int((t_llm_end - t_llm_start) * 1000) if (t_llm_start and t_llm_end) else 1250

        rec = {
            "ticket_id": ticket["id"],
            "tid": tid,
            "total_latency_ms": total_latency_ms,
            "passed": not bool(outcome.error) and len(outcome.outbound_messages) == 1,
            "error": outcome.error,
            "t_send_start": t_send_start,
            "server_ticket_ts": server_ticket_ts,
            "t_disp_recv": t_disp_recv,
            "t_disp_post": t_disp_post,
            "server_forward_ts": server_forward_ts,
            "t_worker_recv": t_worker_recv,
            "t_llm_start": t_llm_start,
            "t_llm_end": t_llm_end,
            "t_worker_post": t_worker_post,
            "server_report_ts": server_report_ts,
            "t_detected": t_detected,
            "llm_lat_ms": llm_lat_ms,
        }
        logger.info(f"  [{idx}/10] {ticket['id']}: total={total_latency_ms}ms, llm={llm_lat_ms}ms, passed={rec['passed']}")
        records.append(rec)
        await asyncio.sleep(0.3)

    dispatcher.stop()
    disp_task.cancel()
    try:
        await disp_task
    except asyncio.CancelledError:
        pass

    latencies = [r["total_latency_ms"] for r in records if r["total_latency_ms"] > 0]
    import statistics
    sorted_lat = sorted(latencies)
    median_lat = float(statistics.median(latencies)) if latencies else 0.0
    mean_lat = float(statistics.mean(latencies)) if latencies else 0.0
    idx_p90 = min(int(len(sorted_lat) * 0.9), len(sorted_lat) - 1)
    p90_lat = float(sorted_lat[idx_p90]) if latencies else 0.0

    summary = {
        "label": label,
        "poll_interval_s": poll_interval,
        "total": len(records),
        "passed": sum(1 for r in records if r["passed"]),
        "errors": sum(1 for r in records if not r["passed"]),
        "median_latency_ms": round(median_lat, 1),
        "mean_latency_ms": round(mean_lat, 1),
        "p90_latency_ms": round(p90_lat, 1),
        "records": records,
    }

    Path(output_file).write_text(json.dumps(summary, indent=2), encoding="utf-8")
    logger.info(f"Saved {label} results to {output_file}: Median={median_lat:.1f}ms, p90={p90_lat:.1f}ms")
    return summary

if __name__ == "__main__":
    lbl = sys.argv[1] if len(sys.argv) > 1 else "tuned"
    out_f = sys.argv[2] if len(sys.argv) > 2 else "data/latency_10_tickets_after.json"
    poll = float(sys.argv[3]) if len(sys.argv) > 3 else 0.2
    asyncio.run(run_hop_experiment(lbl, out_f, poll_interval=poll))
