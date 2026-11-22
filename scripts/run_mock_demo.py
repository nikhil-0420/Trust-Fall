#!/usr/bin/env python3
"""
scripts/run_mock_demo.py
CLI runner executing Trust Fall arena in full mock mode.
Owner: Nehaa (WS-C C2, C7)
"""
import argparse
import asyncio
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

repo_root = Path(__file__).resolve().parent.parent
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

from agents.red import AdaptiveRed
from arena.budget_hooks import LocalBudget
from arena.events import EventWriter
from arena.mocks import (
    FakeSandbox,
    MockGate,
    MockTransport,
    ScriptedBlue,
)
from arena.referee import Referee
from contracts.models import Results


def build_presets_from_results(results: Results, library_path: Path) -> list:
    """Build presets from known attacks in library and cached outcomes per level."""
    with open(library_path, "r", encoding="utf-8") as f:
        raw_lib = json.load(f)

    # Map attack outcomes per round
    # R0 -> L0, R1 -> L1, R2 -> L2
    outcomes_by_id = {}
    for round_res in results.rounds:
        lvl = "L0" if round_res.id == "R0" else ("L1" if round_res.id == "R1" else "L2")
        for att in round_res.attacks:
            if att.id not in outcomes_by_id:
                outcomes_by_id[att.id] = {}
            outcomes_by_id[att.id][lvl] = att.outcome

    presets = []
    preset_idx = 1
    for item in raw_lib:
        if not item.get("known", True):
            continue  # NEVER expose held-out attacks
        att_id = item["id"]
        cached = outcomes_by_id.get(att_id, {})
        preset_entry = {
            "id": f"preset-{preset_idx}",
            "title": item["title"],
            "category": item["category"],
            "owasp": item.get("owasp", "LLM01"),
            "goal": item["goal"],
            "text": item["text"],
            "cached_outcomes": {
                "L0": cached.get("L0", "succeeded"),
                "L1": cached.get("L1", "blocked_by_gate"),
                "L2": cached.get("L2", "resisted"),
            },
            "outcomes": {
                "L0": cached.get("L0", "succeeded"),
                "L1": cached.get("L1", "blocked_by_gate"),
                "L2": cached.get("L2", "resisted"),
            },
        }
        presets.append(preset_entry)
        preset_idx += 1
        if preset_idx > 10:
            break

    return presets


async def main():
    parser = argparse.ArgumentParser(description="Run Trust Fall demo in mock mode")
    parser.add_argument("--attacks-per-round", type=int, default=6, help="Attacks per round (default 6)")
    parser.add_argument("--copy-to-mock", action="store_true", help="Refresh data/mock/ files")
    parser.add_argument("--rollback-demo", action="store_true", help="Demonstrate patch rejection and rollback")
    args = parser.parse_args()

    os.environ["USE_MOCKS"] = "1"
    os.environ["LIVE_APPROVED"] = "0"

    timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    run_id = f"mock-{timestamp}"

    # Initialize components
    sandbox = FakeSandbox()
    gate = MockGate()
    transport = MockTransport(sandbox=sandbox, gate=gate)
    red = AdaptiveRed(attacks_per_round=args.attacks_per_round)
    blue = ScriptedBlue()
    budget = LocalBudget()
    events = EventWriter(run_id=run_id, base_dir="data/runs", cache_dir="data/cache")

    referee = Referee(
        transport=transport,
        sandbox=sandbox,
        gate=gate,
        red=red,
        blue=blue,
        events=events,
        budget=budget,
        benign_count=10,
    )

    print("\n=======================================================")
    print(f"  Trust Fall — Mock Demo Run ({run_id})")
    print("=======================================================\n")

    results = await referee.run_full(
        run_id=run_id,
        attacks_per_round=args.attacks_per_round,
        library_path=repo_root / "attacks" / "library.json",
        rollback_demo=args.rollback_demo,
    )

    print(f"{'Round':<6} | {'Label':<12} | {'ASR':<7} | {'ASR(known)':<10} | {'ASR(heldout)':<12} | {'Benign':<8} | {'Gate Blocks':<12}")
    print("-" * 80)
    for r in results.rounds:
        heldout_str = f"{r.asr_heldout:.1%}" if r.asr_heldout is not None else "N/A"
        benign_str = f"{r.benign.passed}/{r.benign.total}"
        print(f"{r.id:<6} | {r.label:<12} | {r.asr:<7.1%} | {r.asr_known:<10.1%} | {heldout_str:<12} | {benign_str:<8} | {r.gate_blocks:<12}")

    print("\nAttack Categories Per Round (Adaptive Red):")
    for r in results.rounds:
        cats = [att.category for att in r.attacks]
        print(f"  {r.id} ({len(cats)} attacks): {', '.join(cats)}")

    print("\nCalls Summary:")
    print(f"  LLM calls:  {results.budget.llm_calls}")
    print(f"  Lyzr calls: {results.budget.lyzr_calls}")
    print(f"  Events written to: data/runs/{run_id}/")

    if args.copy_to_mock:
        mock_dir = repo_root / "data" / "mock"
        mock_dir.mkdir(parents=True, exist_ok=True)

        # 1. results.json
        res_dict = results.model_dump()
        res_dict["sample"] = True
        with open(mock_dir / "results.json", "w", encoding="utf-8") as f:
            json.dump(res_dict, f, indent=2)

        # 2. events-R0/R1/R2.json as JSON arrays
        for r_id in ["R0", "R1", "R2"]:
            ev_list = events.get_events_for_round(r_id)
            with open(mock_dir / f"events-{r_id}.json", "w", encoding="utf-8") as f:
                json.dump(ev_list, f, indent=2)

        # 3. presets.json
        presets = build_presets_from_results(results, repo_root / "attacks" / "library.json")
        with open(mock_dir / "presets.json", "w", encoding="utf-8") as f:
            json.dump(presets, f, indent=2)

        # 4. leaderboard.json
        lb_file = mock_dir / "leaderboard.json"
        if not lb_file.exists():
            lb_data = {
                "total_attempts": 20,
                "successful_breaks": 3,
                "break_rate": 0.15,
                "entries": [],
            }
            with open(lb_file, "w", encoding="utf-8") as f:
                json.dump(lb_data, f, indent=2)

        print(f"[*] Successfully refreshed data/mock/ files from run {run_id}")


if __name__ == "__main__":
    asyncio.run(main())
