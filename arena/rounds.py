"""
arena/rounds.py
Execution logic for individual rounds (R0, R1, R2).
Owner: Nehaa (WS-C C2)
"""
import secrets
from typing import Any, Dict, List, Optional, Tuple

from arena.benign import run_benign_suite
from arena.interfaces import Envelope, ProfileType, Transport, WorkerOutcome
from arena.judge import judge
from contracts.models import (
    Attack,
    BenignSummary,
    Event,
    RoundAttackResult,
    RoundId,
    RoundResult,
)


def generate_canary() -> str:
    """Generate a random canary secret like CANARY-<6 hex>-DEMO-ONLY."""
    token = secrets.token_hex(3)
    return f"CANARY-{token}-DEMO-ONLY"


async def execute_round(
    referee: Any,
    round_id: RoundId,
    profile: ProfileType,
    attacks: List[Attack],
    patch_version: int = 0,
    benign_count: int = 10,
) -> RoundResult:
    """
    Execute a single round of attacks against the defense profile:
    1. For each attack: reset sandbox state, send ticket with retry, judge, emit events in order.
    2. Run benign test suite.
    3. Calculate ASR metrics and emit round_summary.
    """
    attack_results: List[RoundAttackResult] = []
    succeeded_known = 0
    known_valid = 0
    succeeded_heldout = 0
    heldout_valid = 0
    persistent_errors = 0
    skipped_budget_count = 0

    round_labels = {
        "R0": "Baseline",
        "R1": "Lyzr gate",
        "R2": "Patched",
        "CH": "Challenge",
    }
    label = round_labels.get(round_id, f"Round {round_id}")
    gate_active = (profile != "L0")

    for attack in attacks:
        # Check local budget governor
        if referee.budget and not referee.budget.can_spend("llm", 1):
            skipped_budget_count += 1
            att_res = RoundAttackResult(
                id=attack.id,
                title=attack.title,
                category=attack.category,
                owasp=attack.owasp,
                goal=attack.goal,
                known=attack.known,
                outcome="resisted",
                gate=None,
                latency_ms=0,
                llm_calls=0,
                skipped_budget=True,
            )
            attack_results.append(att_res)
            continue

        # 1. Reset state with fresh random canary
        canary = generate_canary()
        await referee.sandbox.reset_state(canary)

        # 2. Build Envelope
        env = Envelope(
            ticket_id=f"T-{round_id}-{attack.id}",
            profile=profile,
            text=attack.text,
            kind="attack",
            attack_id=attack.id,
        )

        # 3. Send ticket with 45s timeout and single retry on error
        outcome: Optional[WorkerOutcome] = None
        for attempt in range(2):
            try:
                outcome = await referee.transport.send_ticket(env, timeout_s=45.0)
                if not outcome.error:
                    break
            except Exception as e:
                if attempt == 1:
                    outcome = WorkerOutcome(
                        ticket_id=env.ticket_id,
                        outbound_messages=[],
                        blocked_by_gate=False,
                        latency_ms=0,
                        llm_calls=0,
                        error=str(e),
                    )

        if outcome is None:
            outcome = WorkerOutcome(
                ticket_id=env.ticket_id,
                outbound_messages=[],
                blocked_by_gate=False,
                latency_ms=0,
                llm_calls=0,
                error="Transport returned None",
            )

        # Record LLM/Gate spend in budget if applicable
        if referee.budget:
            if outcome.llm_calls > 0:
                referee.budget.spend("llm", outcome.llm_calls)
            if outcome.gate:
                referee.budget.spend("lyzr", 1)

        # Record calls in event writer
        referee.events.record_llm_call(outcome.llm_calls)
        if outcome.gate:
            referee.events.record_lyzr_call(1)

        # 4. Deterministic Judge evaluation
        judge_res = judge(attack.goal, canary, outcome)

        # 5. Emit events in strict order:
        # (a) message event
        referee.events.emit(
            round_id=round_id,
            event_type="message",
            from_agent="red",
            to="dispatcher",
            text=attack.text,
            attack_id=attack.id,
        )

        # (b) gate event if gate screened or blocked
        if outcome.gate or outcome.blocked_by_gate:
            referee.events.emit(
                round_id=round_id,
                event_type="gate",
                target="worker",
                decision=outcome.gate.decision if outcome.gate else ("INJECTION" if outcome.blocked_by_gate else "SAFE"),
                confidence=outcome.gate.confidence if outcome.gate else (0.95 if outcome.blocked_by_gate else 0.05),
                blocked=outcome.blocked_by_gate,
                cached=outcome.gate.cached if outcome.gate else False,
            )

        # (c) agent_state event (healthy -> compromised on success)
        if judge_res.outcome == "succeeded":
            referee.events.emit(
                round_id=round_id,
                event_type="agent_state",
                agent="worker",
                state="compromised",
            )
        else:
            referee.events.emit(
                round_id=round_id,
                event_type="agent_state",
                agent="worker",
                state="healthy",
            )

        # (d) judge event
        referee.events.emit(
            round_id=round_id,
            event_type="judge",
            attack_id=attack.id,
            goal=attack.goal,
            outcome=judge_res.outcome if judge_res.outcome != "error" else "resisted",
            evidence=judge_res.evidence,
        )

        # 6. Exclude persistent errors from ASR denominator
        if judge_res.outcome == "error":
            persistent_errors += 1
            att_outcome = "resisted"
        else:
            att_outcome = judge_res.outcome
            if attack.known:
                known_valid += 1
                if att_outcome == "succeeded":
                    succeeded_known += 1
            else:
                heldout_valid += 1
                if att_outcome == "succeeded":
                    succeeded_heldout += 1

        attack_results.append(
            RoundAttackResult(
                id=attack.id,
                title=attack.title,
                category=attack.category,
                owasp=attack.owasp,
                goal=attack.goal,
                known=attack.known,
                outcome=att_outcome,
                gate=outcome.gate.model_dump() if outcome.gate else None,
                latency_ms=outcome.latency_ms,
                llm_calls=outcome.llm_calls,
            )
        )

    # 7. Benign suite
    benign_raw = await run_benign_suite(referee.transport, profile, n=benign_count)
    benign_summary = BenignSummary(total=benign_raw["total"], passed=benign_raw["passed"])
    benign_rate = (
        round(benign_summary.passed / benign_summary.total, 3)
        if benign_summary.total > 0
        else 1.0
    )

    # 8. Compute ASR metrics
    total_valid = known_valid + heldout_valid
    total_succeeded = succeeded_known + succeeded_heldout

    asr = round(total_succeeded / total_valid, 3) if total_valid > 0 else 0.0
    asr_known = round(succeeded_known / known_valid, 3) if known_valid > 0 else 0.0
    asr_heldout = (
        round(succeeded_heldout / heldout_valid, 3) if heldout_valid > 0 else None
    )

    # Emit round_summary event
    referee.events.emit(
        round_id=round_id,
        event_type="round_summary",
        asr=asr,
        asr_known=asr_known,
        asr_heldout=asr_heldout,
        benign_pass_rate=benign_rate,
        gate_blocks=referee.events.gate_blocks,
        llm_calls=referee.events.llm_calls,
        lyzr_calls=referee.events.lyzr_calls,
    )

    return RoundResult(
        id=round_id,
        label=label,
        gate=gate_active,
        patch_version=patch_version,
        attacks=attack_results,
        asr=asr,
        asr_known=asr_known,
        asr_heldout=asr_heldout,
        benign=benign_summary,
        gate_blocks=referee.events.gate_blocks,
        llm_calls=referee.events.llm_calls,
        lyzr_calls=referee.events.lyzr_calls,
        errors=persistent_errors,
        skipped_budget=skipped_budget_count,
    )
