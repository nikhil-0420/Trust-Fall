"""
arena/referee.py
Referee orchestrating rounds, evaluations, and patch workflow.
Owner: Nehaa (WS-C C2, C4, C6)
"""
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from arena.events import EventWriter
from arena.interfaces import BlueAgent, Gate, RedAgent, Sandbox, Transport
from arena.reports import generate_reports
from arena.rollback import apply_or_rollback
from arena.rounds import execute_round
from contracts.models import (
    Attack,
    BudgetSummary,
    ContagionSummary,
    Results,
    RoundId,
    RoundResult,
)


class Referee:
    """
    Deterministic Referee orchestrating R0 -> R1 -> Blue turn -> R2.
    Interacts with components via protocols defined in arena/interfaces.py.
    """

    def __init__(
        self,
        transport: Transport,
        sandbox: Sandbox,
        gate: Gate,
        red: RedAgent,
        blue: BlueAgent,
        events: EventWriter,
        budget: Any | None = None,
        benign_count: int = 10,
    ):
        self.transport = transport
        self.sandbox = sandbox
        self.gate = gate
        self.red = red
        self.blue = blue
        self.events = events
        self.budget = budget
        self.benign_count = benign_count

        # Ensure in-memory mock transport references same sandbox/gate instances
        if hasattr(self.transport, "sandbox"):
            self.transport.sandbox = self.sandbox
        if hasattr(self.transport, "gate"):
            self.transport.gate = self.gate

    async def run_round(
        self,
        round_id: RoundId,
        profile: str,
        attacks: list[Attack],
        patch_version: int = 0,
    ) -> RoundResult:
        """Run a single evaluation round."""
        return await execute_round(
            referee=self,
            round_id=round_id,
            profile=profile,
            attacks=attacks,
            patch_version=patch_version,
            benign_count=self.benign_count,
        )

    async def run_full(
        self,
        run_id: str | None = None,
        attacks_per_round: int = 6,
        library_path: str | Path = "attacks/library.json",
        rollback_demo: bool = False,
    ) -> Results:
        """
        Execute full R0 -> R1 -> Blue defense turn -> R2 evaluation.
        Persists results to data/runs/<run_id>/results.json and writes reports.
        """
        if not run_id:
            run_id = f"run-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}"

        self.events.run_id = run_id
        self.events.run_dir = self.events.base_dir / run_id
        self.events.run_dir.mkdir(parents=True, exist_ok=True)

        # 1. Load attack library
        lib_file = Path(library_path)
        with open(lib_file, "r", encoding="utf-8") as f:
            raw_lib = json.load(f)
        library = [Attack.model_validate(item) for item in raw_lib]

        known_attacks = [a for a in library if a.known]
        heldout_attacks = [a for a in library if not a.known]

        # Select initial known attacks for R0 using red agent
        try:
            r0_attacks = await self.red.next_attacks("R0", library, [])
        except Exception:
            r0_attacks = known_attacks[:attacks_per_round]

        # 2. R0: Baseline (L0)
        r0_res = await self.run_round("R0", "L0", r0_attacks, patch_version=0)

        # 3. R1: Screening Gate (L1) with adaptive red selection
        try:
            history_r0 = [att.model_dump() for att in r0_res.attacks]
            r1_attacks = await self.red.next_attacks("R1", library, history_r0)
        except Exception:
            r1_attacks = r0_attacks

        r1_res = await self.run_round("R1", "L1", r1_attacks, patch_version=0)

        # 4. Collect incident log of attacks that succeeded in R1 (known only!)
        incident_log = []
        for att in r1_res.attacks:
            if att.outcome == "succeeded" and att.known:
                full_att = next((a for a in known_attacks if a.id == att.id), None)
                incident_log.append(
                    {
                        "attack_id": att.id,
                        "category": att.category,
                        "goal": att.goal,
                        "text": full_att.text if full_att else "",
                        "outcome": att.outcome,
                        "failing_layer": "worker",
                    }
                )

        # Phase C9: Blue input fallback if fewer than 2 attacks succeeded in R1
        blue_input = "R1"
        if len(incident_log) < 2:
            blue_input = "R0+R1"
            added = 0
            for att in r0_res.attacks:
                if att.outcome == "succeeded" and att.known:
                    if not any(entry["attack_id"] == att.id for entry in incident_log):
                        full_att = next((a for a in known_attacks if a.id == att.id), None)
                        incident_log.append(
                            {
                                "attack_id": att.id,
                                "category": att.category,
                                "goal": att.goal,
                                "text": full_att.text if full_att else "",
                                "outcome": att.outcome,
                                "failing_layer": "worker",
                            }
                        )
                        added += 1
                        if added >= 4:
                            break

        # 5. Blue turn: propose, test, and apply/rollback patch
        r0_rate = (
            (r0_res.benign.passed / r0_res.benign.total)
            if r0_res.benign.total > 0
            else 1.0
        )
        patch_decision = await apply_or_rollback(
            referee=self,
            incident_log=incident_log,
            r0_benign_rate=r0_rate,
            rollback_demo=rollback_demo,
            previous_patch=None,
        )

        patches_recorded = list(patch_decision.history)
        patch_version = patch_decision.active_version

        # 6. R2: Patched (L2)
        # Ask Red agent for R2 attack selection (all previous successes + all held-out)
        try:
            history_all = [att.model_dump() for att in r0_res.attacks] + [
                att.model_dump() for att in r1_res.attacks
            ]
            r2_attacks = await self.red.next_attacks("R2", library, history_all)
        except Exception:
            successful_known_ids = {
                att.id for att in r0_res.attacks if att.outcome == "succeeded"
            } | {att.id for att in r1_res.attacks if att.outcome == "succeeded"}
            r2_known = [a for a in known_attacks if a.id in successful_known_ids] or r0_attacks[:3]
            r2_attacks = r2_known + heldout_attacks

        r2_res = await self.run_round("R2", "L2", r2_attacks, patch_version=patch_version)

        # 7. Compile Results model
        use_mocks = os.getenv("USE_MOCKS", "1").strip().lower() in {"1", "true", "yes"}
        models = {
            "worker": os.getenv("MODEL_NAME", "gemini-3.5-flash-lite"),
            "red": "scripted",
            "blue": "scripted",
        }
        contagion = ContagionSummary(
            enabled=False,
            asr_without_guard=0.0,
            asr_with_guard=0.0,
        )
        budget_summary = BudgetSummary(
            llm_calls=self.events.llm_calls,
            lyzr_calls=self.events.lyzr_calls,
        )

        results = Results(
            run_id=run_id,
            generated_at=datetime.now(UTC).isoformat(),
            models=models,
            rounds=[r0_res, r1_res, r2_res],
            patches=patches_recorded,
            contagion=contagion,
            budget=budget_summary,
            sample=use_mocks,
            blue_input=blue_input,
        )

        # Save to data/runs/<run_id>/results.json
        out_file = self.events.run_dir / "results.json"
        with open(out_file, "w", encoding="utf-8") as f:
            f.write(results.model_dump_json(indent=2))

        # Generate markdown reports in data/reports/
        try:
            generate_reports(
                results,
                output_dir="data/reports",
                cache_hits=self.events.cache_hits,
            )
        except Exception:
            pass

        return results
