"""
arena/rounds.py
Execution logic for individual rounds (R0, R1, R2).
Owner: Nehaa (WS-C C2)
"""
import secrets
from typing import Any

from arena.benign import run_benign_suite
from arena.interfaces import Envelope, ProfileType, WorkerOutcome
from arena.judge import judge
from contracts.models import (
    Attack,
    BenignSummary,
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
    attacks: list[Attack],
    patch_version: int = 0,
    benign_count: int = 10,
) -> RoundResult:
    """
    Execute a single round of attacks against the defense profile:
    1. For each attack: reset sandbox state, send ticket with retry, judge, emit events in order.
    2. Run benign test suite.
    3. Calculate ASR metrics and emit round_summary.
    """
    attack_results: list[RoundAttackResult] = []
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
        if hasattr(referee.transport, "reset_state"):
            await referee.transport.reset_state(canary)

        # 2. Multi-step support (Phase C3): sequential delivery without resetting state
        steps = attack.steps if (attack.steps and len(attack.steps) > 0) else [attack.text]
        step_outcomes: list[WorkerOutcome] = []
        stopped_by_gate = False

        for step_idx, step_text in enumerate(steps):
            step_ticket_id = (
                f"T-{round_id}-{attack.id}-s{step_idx+1}"
                if len(steps) > 1
                else f"T-{round_id}-{attack.id}"
            )
            env = Envelope(
                ticket_id=step_ticket_id,
                profile=profile,
                text=step_text,
                kind="attack",
                attack_id=attack.id,
            )

            # Send ticket with 45s timeout and single retry on error
            step_outcome: WorkerOutcome | None = None
            for attempt in range(2):
                try:
                    step_outcome = await referee.transport.send_ticket(env, timeout_s=45.0)
                    if not step_outcome.error:
                        break
                except Exception as e:
                    if attempt == 1:
                        step_outcome = WorkerOutcome(
                            ticket_id=env.ticket_id,
                            outbound_messages=[],
                            blocked_by_gate=False,
                            latency_ms=0,
                            llm_calls=0,
                            error=str(e),
                        )

            if step_outcome is None:
                step_outcome = WorkerOutcome(
                    ticket_id=env.ticket_id,
                    outbound_messages=[],
                    blocked_by_gate=False,
                    latency_ms=0,
                    llm_calls=0,
                    error="Transport returned None",
                )

            step_outcomes.append(step_outcome)

            # Record LLM/Gate spend in budget if applicable
            if referee.budget:
                if step_outcome.llm_calls > 0:
                    referee.budget.spend("llm", step_outcome.llm_calls)
                if step_outcome.gate:
                    referee.budget.spend("lyzr", 1)

            # Record calls in event writer
            referee.events.record_llm_call(step_outcome.llm_calls)
            if step_outcome.gate:
                referee.events.record_lyzr_call(1)

            # Emit message event for step
            referee.events.emit(
                round_id=round_id,
                event_type="message",
                from_agent="red",
                to="dispatcher",
                text=step_text,
                attack_id=attack.id,
            )

            # Emit gate event if gate screened or blocked
            if step_outcome.gate or step_outcome.blocked_by_gate:
                referee.events.emit(
                    round_id=round_id,
                    event_type="gate",
                    target="worker",
                    decision=step_outcome.gate.decision if step_outcome.gate else ("INJECTION" if step_outcome.blocked_by_gate else "SAFE"),
                    confidence=step_outcome.gate.confidence if step_outcome.gate else (0.95 if step_outcome.blocked_by_gate else 0.05),
                    blocked=step_outcome.blocked_by_gate,
                    cached=step_outcome.gate.cached if step_outcome.gate else False,
                )

            if step_outcome.blocked_by_gate:
                stopped_by_gate = True
                break

        # Aggregate outcomes across steps
        final_outcome = step_outcomes[-1]
        all_outbound: list[str] = []
        total_llm_calls = sum(so.llm_calls for so in step_outcomes)
        total_latency_ms = sum(so.latency_ms for so in step_outcomes)
        for so in step_outcomes:
            all_outbound.extend(so.outbound_messages)

        outcome = WorkerOutcome(
            ticket_id=f"T-{round_id}-{attack.id}",
            outbound_messages=all_outbound,
            blocked_by_gate=stopped_by_gate,
            gate=final_outcome.gate,
            memory_after=final_outcome.memory_after,
            refund_ledger_after=final_outcome.refund_ledger_after,
            latency_ms=total_latency_ms,
            llm_calls=total_llm_calls,
            error=final_outcome.error if any(so.error for so in step_outcomes) else None,
            policy_denied=any(getattr(so, "policy_denied", False) for so in step_outcomes),
            memory_note_blocked=any(getattr(so, "memory_note_blocked", False) for so in step_outcomes),
        )

        # 4. Deterministic Judge evaluation
        judge_res = judge(attack.goal, canary, outcome)

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
            outcome=judge_res.outcome,
            evidence=judge_res.evidence,
        )

        # 6. Exclude persistent errors from ASR denominator
        if judge_res.outcome == "error":
            persistent_errors += 1
            att_outcome = "error"
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
