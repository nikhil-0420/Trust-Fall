"""
Owner: Nikhil (Phase N3)
LoopbackTransport implementing the Transport protocol.
Runs fully in-process with Dispatcher, WorkerCore, and local state dir.
"""
import os
from pathlib import Path
from typing import Optional

from agents.dispatcher import Dispatcher
from agents.gate_client import GateClient
from agents.worker_core import WorkerCore
from arena.factory import get_gate_client, get_llm
from arena.interfaces import Envelope, Transport, WorkerOutcome


class LoopbackTransport(Transport):
    def __init__(
        self,
        dispatcher: Optional[Dispatcher] = None,
        worker: Optional[WorkerCore] = None,
        state_dir: Optional[Path] = None,
    ):
        self.state_dir = Path(state_dir or "data/loopback_state")
        self.state_dir.mkdir(parents=True, exist_ok=True)

        if worker is not None:
            self.worker = worker
        else:
            self.worker = WorkerCore(
                llm=get_llm(),
                state_dir=self.state_dir,
            )

        if dispatcher is not None:
            self.dispatcher = dispatcher
        else:
            self.dispatcher = Dispatcher(
                gate=get_gate_client(),
                worker=self.worker,
            )

    async def reset_state(self, canary: str) -> None:
        """Resets the local state directory between attacks."""
        self.state_dir.mkdir(parents=True, exist_ok=True)
        (self.state_dir / "secrets.txt").write_text(canary, encoding="utf-8")
        memory_file = self.state_dir / "memory.json"
        if memory_file.exists():
            try:
                memory_file.unlink()
            except Exception:
                pass
        refund_file = self.state_dir / "refund_ledger.json"
        if refund_file.exists():
            try:
                refund_file.unlink()
            except Exception:
                pass

    async def send_ticket(self, env: Envelope, timeout_s: float = 60.0) -> WorkerOutcome:
        """Sends an envelope through the Dispatcher and returns the WorkerOutcome with 1 retry on timeout."""
        import asyncio
        env_timeout = os.getenv("TICKET_TIMEOUT_S")
        if env_timeout:
            try:
                timeout_s = float(env_timeout)
            except ValueError:
                pass

        if getattr(env, "is_multistep", False) or "multi" in getattr(env, "ticket_id", "").lower():
            timeout_s = max(timeout_s, 90.0)

        for attempt in range(2):
            try:
                outcome = await asyncio.wait_for(self.dispatcher.handle_ticket(env), timeout=timeout_s)
                if outcome.path is None:
                    outcome.path = "in-process"
                if not outcome.error:
                    return outcome
            except asyncio.TimeoutError:
                if attempt == 1:
                    return WorkerOutcome(
                        ticket_id=env.ticket_id,
                        outbound_messages=[],
                        blocked_by_gate=False,
                        latency_ms=int(timeout_s * 1000),
                        llm_calls=0,
                        error="timeout",
                        path="in-process",
                    )
                await asyncio.sleep(0.5)
            except Exception as e:
                if attempt == 1:
                    return WorkerOutcome(
                        ticket_id=env.ticket_id,
                        outbound_messages=[],
                        blocked_by_gate=False,
                        latency_ms=0,
                        llm_calls=0,
                        error=str(e),
                        path="in-process",
                    )
                await asyncio.sleep(0.5)
        return outcome
