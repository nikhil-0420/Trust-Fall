"""
Core interfaces and protocols for Trust Fall.
Defines Envelope, GateResult, WorkerOutcome, and asynchronous protocols.
"""
from typing import Any, Dict, List, Literal, Optional, Protocol, runtime_checkable
from pydantic import BaseModel, ConfigDict, Field
from contracts.models import Attack

ProfileType = Literal["L0", "L1", "L2"]
TicketKind = Literal["attack", "benign", "challenge"]
GateDecision = Literal["SAFE", "INJECTION", "ERROR"]
DecidedBy = Literal["gate", "memory_policy", "redaction", "model", "none"]


class Envelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ticket_id: str = Field(..., description="Unique ticket ID")
    attempt_id: Optional[str] = Field(default=None, description="Optional public break attempt ID")
    profile: ProfileType = Field(..., description="Defense profile L0|L1|L2")
    text: str = Field(..., description="Input payload/text")
    kind: TicketKind = Field(..., description="Ticket type: attack, benign, or challenge")
    attack_id: Optional[str] = Field(default=None, description="Attack ID if known attack")
    salt: Optional[str] = Field(default=None, description="Optional cache salt for stability testing")


class GateResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: GateDecision = Field(..., description="SAFE | INJECTION | ERROR")
    confidence: float = Field(..., description="Confidence score 0.0 to 1.0")
    cached: bool = Field(..., description="Whether result came from cache")
    blocked: bool = Field(..., description="Whether the payload was blocked")


class WorkerOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ticket_id: str
    outbound_messages: List[str] = Field(default_factory=list)
    blocked_by_gate: bool
    gate: Optional[GateResult] = None
    memory_after: Optional[str] = None
    refund_ledger_after: Optional[str] = None
    latency_ms: int
    llm_calls: int
    error: Optional[str] = None
    policy_denied: Optional[bool] = Field(default=None, description="True if memory write or tool was blocked by policy")
    memory_note_blocked: Optional[bool] = Field(default=None, description="True if one or more memory notes were dropped by gate screening")
    controls: Dict[str, Any] = Field(default_factory=dict, description="Detailed evidence of controls triggered: gate_blocked, redactions, memory_denials, memory_notes_blocked")
    decided_by: Optional[DecidedBy] = Field(default="none", description="Primary control that decided outcome: gate, memory_policy, redaction, model, none")
    path: Optional[str] = Field(default=None, description="Execution transport path: band+agent37 or in-process")


@runtime_checkable
class Transport(Protocol):
    async def send_ticket(self, env: Envelope, timeout_s: float = 45.0) -> WorkerOutcome:
        ...


@runtime_checkable
class Sandbox(Protocol):
    async def reset_state(self, canary: str) -> None:
        ...

    async def read_memory(self) -> str:
        ...

    async def read_refund_ledger(self) -> str:
        ...

    async def install_patch(self, patch: dict) -> None:
        ...

    async def restart(self) -> None:
        ...

    async def ping(self) -> bool:
        ...


@runtime_checkable
class Gate(Protocol):
    async def screen(self, text: str, stage: str) -> GateResult:
        ...


@runtime_checkable
class LLM(Protocol):
    async def complete(
        self,
        system: str,
        prompt: str,
        *,
        purpose: str,
        json_mode: bool = False,
        salt: Optional[str] = None,
    ) -> str:
        ...


@runtime_checkable
class RedAgent(Protocol):
    async def next_attacks(
        self,
        round_id: str,
        library: List[Attack],
        history: List[Dict[str, Any]],
    ) -> List[Attack]:
        ...


@runtime_checkable
class BlueAgent(Protocol):
    async def propose_patch(
        self,
        incident_log: List[Dict[str, Any]],
        previous_patch: Optional[Dict[str, Any]],
        rejected_reason: Optional[str],
    ) -> Dict[str, Any]:
        ...
