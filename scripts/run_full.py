"""scripts/run_full.py
Executes the full 3-round Trust Fall Arena run (R0 -> R1 -> R2).
Safe by default: if USE_MOCKS=1 or LIVE_APPROVED!=1, executes dry-run mode.
Owner: Nehaa (WS-B B3, WS-D)
"""

import argparse
import asyncio
import os
import sys
from pathlib import Path

# Add repo root to sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from arena.factory import (
    get_blue,
    get_gate,
    get_llm,
    get_red,
    get_sandbox,
    get_transport,
)
from arena.referee import Referee


async def main():
    parser = argparse.ArgumentParser(description="Trust Fall Full Arena Runner")
    parser.add_argument("--live", action="store_true", help="Request live run (requires LIVE_APPROVED=1)")
    parser.add_argument("--rollback-demo", action="store_true", help="Demonstrate rejected patch rollback first")
    parser.add_argument("--run-id", type=str, default=None, help="Custom run identifier")
    args = parser.parse_args()

    use_mocks = os.getenv("USE_MOCKS", "1").strip() != "0"
    live_approved = os.getenv("LIVE_APPROVED", "0").strip() == "1"

    if args.live and (use_mocks or not live_approved):
        print("[!] LIVE run requested but USE_MOCKS!=0 or LIVE_APPROVED!=1.")
        print("    Running in safe dry-run mock mode instead.")

    transport = get_transport()
    sandbox = get_sandbox()
    gate = get_gate()
    llm = get_llm()
    red = get_red()
    blue = get_blue()

    referee = Referee(
        transport=transport,
        sandbox=sandbox,
        gate=gate,
        llm=llm,
        red=red,
        blue=blue,
    )

    print("[*] Starting Arena full run...")
    results = await referee.run_full(
        run_id=args.run_id,
        rollback_demo=args.rollback_demo,
    )

    print(f"[*] Run completed successfully! Run ID: {results.run_id}")
    for rnd in results.rounds:
        print(f"    - Round {rnd.id} ({rnd.label}): ASR={rnd.asr:.2f}, Benign={rnd.benign.passed}/{rnd.benign.total}")


if __name__ == "__main__":
    asyncio.run(main())
