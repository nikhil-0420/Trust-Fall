"""scripts/run_full.py
Executes the full 3-round Trust Fall Arena run (R0 -> R1 -> R2).
Safe by default: if USE_MOCKS=1 or LIVE_APPROVED!=1, executes dry-run mode.
Owner: Nehaa (WS-B B3, WS-D) - Extended with timeout, budget shrink, and BAND dispatcher runner.
"""

import argparse
import asyncio
from datetime import datetime, timezone
import os
from pathlib import Path
import sys

# Ensure process environment has relaxed caps and zero interval for live evaluation
os.environ["LLM_DAILY_CAP"] = "100000000"
os.environ["LYZR_DAILY_CAP"] = "100000000"
os.environ["GEMINI_MIN_INTERVAL_S"] = "0"

# Add repo root to sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from api.budget import get_budget
from arena.events import EventWriter
from arena.factory import (
    get_blue,
    get_gate,
    get_llm,
    get_red,
    get_sandbox,
    get_transport,
)
from arena.referee import Referee


def log_external_call(service: str, purpose: str, count: int = 1):
    ledger = REPO_ROOT / "docs" / "CALL_LEDGER.md"
    if ledger.exists():
        timestamp = datetime.now(timezone.utc).isoformat()
        with open(ledger, "a", encoding="utf-8") as f:
            f.write(f"| {timestamp} | {service} | {purpose} | {count} |\n")


async def main():
    parser = argparse.ArgumentParser(description="Trust Fall Full Arena Runner")
    parser.add_argument("--live", action="store_true", help="Request live run (requires LIVE_APPROVED=1)")
    parser.add_argument("--rollback-demo", action="store_true", help="Demonstrate rejected patch rollback first")
    parser.add_argument("--run-id", type=str, default=None, help="Custom run identifier")
    parser.add_argument("--timeout", type=float, default=35.0, help="Per-ticket referee timeout in seconds")
    parser.add_argument("--attacks-per-round", type=int, default=12, help="Number of attacks per round")
    parser.add_argument("--benign-count", type=int, default=5, help="Number of benign tickets per round")
    args = parser.parse_args()

    use_mocks = os.getenv("USE_MOCKS", "1").strip() != "0"
    live_approved = os.getenv("LIVE_APPROVED", "0").strip() == "1"

    if args.live and (use_mocks or not live_approved):
        print("[!] LIVE run requested but USE_MOCKS!=0 or LIVE_APPROVED!=1.")
        print("    Running in safe dry-run mock mode instead.")

    # Set ticket timeout in environment so all transports / referees respect it
    os.environ["TICKET_TIMEOUT_S"] = str(args.timeout)
    os.environ["ATTACKS_PER_ROUND"] = str(args.attacks_per_round)
    os.environ["BENIGN_COUNT"] = str(args.benign_count)

    run_id = args.run_id or f"run-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"

    # Initialize EventWriter and Budget
    events = EventWriter(
        run_id=run_id,
        base_dir=REPO_ROOT / "data" / "runs",
        cache_dir=REPO_ROOT / "data" / "cache",
    )
    budget = get_budget()

    # Hook subscriber to log live calls to CALL_LEDGER.md
    def on_event(ev):
        if not use_mocks and live_approved:
            if ev.type == "gate" and not ev.cached:
                log_external_call("Lyzr", "gate_screen", 1)
            elif ev.type == "message" and ev.from_agent == "worker":
                log_external_call("Gemini", "worker_llm", 1)
            elif ev.type == "patch":
                log_external_call("Gemini", "blue_llm_patch", 1)

    events.add_subscriber(on_event)

    transport_type = os.getenv("TRANSPORT", "mock").strip().lower()
    disp_agent = None
    disp_task = None

    if transport_type == "band" and not use_mocks and live_approved:
        from agents.dispatcher import Dispatcher
        from agents.dispatcher_band import BandDispatcherAgent
        from arena.factory import get_gate_client
        disp_agent = BandDispatcherAgent(dispatcher=Dispatcher(gate=get_gate_client()))
        disp_task = asyncio.create_task(disp_agent.run(interval_s=1.0))
        await disp_agent.wait_ready()

    try:
        transport = get_transport()
        sandbox = get_sandbox()
        gate = get_gate()
        red = get_red()
        blue = get_blue()

        referee = Referee(
            transport=transport,
            sandbox=sandbox,
            gate=gate,
            red=red,
            blue=blue,
            events=events,
            budget=budget,
            benign_count=args.benign_count,
        )

        print(f"[*] Starting Arena full run ({run_id})...")
        try:
            results = await referee.run_full(
                run_id=run_id,
                attacks_per_round=args.attacks_per_round,
                rollback_demo=args.rollback_demo,
            )
        except Exception as e:
            if "INVALID-GATE" in str(e):
                print(f"[!] RUN ABORTED: {e}")
                run_summary_path = REPO_ROOT / "docs" / "RUN_SUMMARY.md"
                run_summary_path.write_text(
                    f"# Run Summary (INVALID-GATE)\n\n**Run ID:** `{run_id}`\n\nRun aborted immediately: {e}\nPartial data preserved under `data/runs/{run_id}/`.\n",
                    encoding="utf-8",
                )
                return None
            raise e

        print(f"[*] Run completed successfully! Run ID: {results.run_id}")
        for rnd in results.rounds:
            print(f"    - Round {rnd.id} ({rnd.label}): ASR={rnd.asr:.2f}, Benign={rnd.benign.passed}/{rnd.benign.total}")

        # Phase C10 (b): Run validity safeguards
        invalid_reasons = []
        for rnd in results.rounds:
            total_tickets = len(rnd.attacks)
            errors = rnd.errors or 0
            if total_tickets > 0 and (errors / total_tickets) > 0.10:
                invalid_reasons.append(
                    f"Round {rnd.id}: error rate {errors}/{total_tickets} ({errors/total_tickets:.1%}) exceeded 10% threshold"
                )
            if rnd.id == "R2" and rnd.benign.passed < rnd.benign.total:
                invalid_reasons.append(
                    f"Round R2 benign tests failed: {rnd.benign.passed}/{rnd.benign.total} passed"
                )

        if invalid_reasons:
            print(f"[!] RUN MARKED INVALID: {invalid_reasons}")
            run_summary_path = REPO_ROOT / "docs" / "RUN_SUMMARY.md"
            summary_lines = [
                "# Run Summary (INVALID)",
                "",
                f"**Run ID:** `{results.run_id}`",
                "",
                "### Invalidation Reasons",
            ]
            for reason in invalid_reasons:
                summary_lines.append(f"- {reason}")
            summary_lines.append("")
            summary_lines.append("This run is quarantined under `data/runs/` and was NOT copied to `data/results.json`.")
            run_summary_path.write_text("\n".join(summary_lines), encoding="utf-8")
        else:
            # Valid run: copy results.json, events, and regenerate reports
            import shutil
            run_results_file = events.run_dir / "results.json"
            if run_results_file.exists():
                data_results_file = REPO_ROOT / "data" / "results.json"
                shutil.copyfile(run_results_file, data_results_file)
                print(f"[*] Valid run copied to {data_results_file}")

            # Copy events to data/events/
            data_events_dir = REPO_ROOT / "data" / "events"
            data_events_dir.mkdir(parents=True, exist_ok=True)
            for rname in ("R0.json", "R1.json", "R2.json"):
                src_ev = events.run_dir / rname
                if src_ev.exists():
                    shutil.copyfile(src_ev, data_events_dir / rname)

            # Regenerate reports in data/reports/
            from arena.reports import generate_reports
            generate_reports(results, output_dir=REPO_ROOT / "data" / "reports", cache_hits=events.cache_hits)

        return results

    finally:
        if disp_agent:
            disp_agent.stop()
        if disp_task:
            disp_task.cancel()


if __name__ == "__main__":
    asyncio.run(main())
