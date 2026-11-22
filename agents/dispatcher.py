"""
Owner: Nikhil (Phase N3)
Dispatcher agent logic (trusted, scripted: NO LLM calls).
Coordinates pre-dispatch gate screening and forwards signed envelopes to Worker.
Emits Event objects (gate, message, agent_state) to an injectable event sink.
"""
import os
import time
from collections.abc import Callable
from typing import Any

from agents.envelope import get_or_create_internal_token, sign_envelope
from arena.interfaces import Envelope, Gate, GateResult, WorkerOutcome
from contracts.models import Event


class Dispatcher:
    def __init__(
        self,
        gate: Gate | None = None,
        worker: Any | None = None,
        event_sink: Callable[[Event], Any] | None = None,
        internal_token: str | None = None,
        run_id: str = "run-001",
        round_id: str = "R0",
    ):
        self.gate = gate
        self.worker = worker
        self.event_sink = event_sink
        self.internal_token = internal_token or os.getenv("INTERNAL_TOKEN") or get_or_create_internal_token()
        self.run_id = run_id
        self.round_id = round_id
        self._seq = 0

    def _next_seq(self) -> int:
        self._seq += 1
        return self._seq

    def _emit(self, event: Event) -> None:
        if self.event_sink is not None:
            try:
                self.event_sink(event)
            except Exception:
                pass

    async def handle_ticket(self, envelope: Envelope) -> WorkerOutcome:
        start_time = time.perf_counter()

        # Pre-dispatch gate check at L1 and L2
        gate_res: GateResult | None = None
        if envelope.profile in ("L1", "L2") and self.gate is not None:
            gate_res = await self.gate.screen(envelope.text, stage="pre_dispatch")

            self._emit(
                Event(
                    t=time.time(),
                    run_id=self.run_id,
                    round=self.round_id,  # type: ignore
                    seq=self._next_seq(),
                    type="gate",
                    target="worker",
                    decision=gate_res.decision,
                    confidence=gate_res.confidence,
                    blocked=gate_res.blocked,
                    cached=gate_res.cached,
                )
            )

            # Drop ticket if gate reports INJECTION or ERROR (fail closed)
            if gate_res.blocked or gate_res.decision in ("INJECTION", "ERROR"):
                self._emit(
                    Event(
                        t=time.time(),
                        run_id=self.run_id,
                        round=self.round_id,  # type: ignore
                        seq=self._next_seq(),
                        type="agent_state",
                        agent="worker",
                        state="healthy",
                    )
                )
                latency_ms = int((time.perf_counter() - start_time) * 1000)
                return WorkerOutcome(
                    ticket_id=envelope.ticket_id,
                    outbound_messages=[],
                    blocked_by_gate=True,
                    gate=gate_res,
                    memory_after=None,
                    refund_ledger_after=None,
                    latency_ms=latency_ms,
                    llm_calls=0,
                    error=None,
                    policy_denied=False,
                )

        # Ticket is safe or L0: Sign envelope and forward
        signed_dict = sign_envelope(envelope, self.internal_token)

        self._emit(
            Event(
                t=time.time(),
                run_id=self.run_id,
                round=self.round_id,  # type: ignore
                seq=self._next_seq(),
                type="message",
                from_agent="dispatcher",
                to="worker",
                text=envelope.text,
                attack_id=envelope.attack_id,
            )
        )

        if self.worker is not None:
            outcome: WorkerOutcome = await self.worker.handle(signed_dict)
            if gate_res is not None and outcome.gate is None:
                # Attach gate result if worker outcome did not have one
                return WorkerOutcome(
                    ticket_id=outcome.ticket_id,
                    outbound_messages=outcome.outbound_messages,
                    blocked_by_gate=False,
                    gate=gate_res,
                    memory_after=outcome.memory_after,
                    refund_ledger_after=outcome.refund_ledger_after,
                    latency_ms=outcome.latency_ms,
                    llm_calls=outcome.llm_calls,
                    error=outcome.error,
                    policy_denied=outcome.policy_denied,
                )
            return outcome

        # If worker is not directly attached (e.g. in standalone mode)
        latency_ms = int((time.perf_counter() - start_time) * 1000)
        return WorkerOutcome(
            ticket_id=envelope.ticket_id,
            outbound_messages=[],
            blocked_by_gate=False,
            gate=gate_res,
            memory_after=None,
            refund_ledger_after=None,
            latency_ms=latency_ms,
            llm_calls=0,
            error=None,
            policy_denied=False,
        )
