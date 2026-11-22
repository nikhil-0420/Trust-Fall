"""
Owner: Nikhil (Phase N3)
LoopbackTransport implementing the Transport protocol.
Runs fully in-process with Dispatcher, WorkerCore, and local state dir.
"""
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

    async def send_ticket(self, env: Envelope, timeout_s: float = 45.0) -> WorkerOutcome:
        """Sends an envelope through the Dispatcher and returns the WorkerOutcome."""
        return await self.dispatcher.handle_ticket(env)
