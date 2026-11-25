"""
Contracts and Pydantic v2 models for Trust Fall.
Defines Event, Results, Patch, Attack, and supporting sub-models.
"""
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional, Union
from pydantic import BaseModel, ConfigDict, Field, field_validator
import re

RoundId = Literal["R0", "R1", "R2", "CH"]
EventType = Literal["message", "gate", "agent_state", "judge", "patch", "round_summary", "budget"]
GoalType = Literal["leak", "poison", "refund"]
JudgeOutcome = Literal["succeeded", "blocked_by_gate", "resisted", "error"]
GateDecision = Literal["SAFE", "INJECTION", "ERROR"]
AgentStateType = Literal["healthy", "compromised", "quarantined", "restarting"]
PatchAction = Literal["proposed", "applied", "rejected", "rolled_back"]
DecidedBy = Literal["gate", "memory_policy", "redaction", "model", "none"]


class Attack(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., description="Unique attack identifier, e.g. A01")
    title: str = Field(..., description="Short attack name")
    category: str = Field(..., description="Attack category e.g. direct, roleplay, obfuscation")
    owasp: str = Field(..., description="OWASP category e.g. LLM01")
    goal: GoalType = Field(..., description="Target objective")
    known: bool = Field(..., description="True if part of standard library, False if held-out")
    text: str = Field(..., max_length=500, description="Payload text <= 500 chars")
    steps: Optional[List[str]] = Field(default=None, description="Optional multi-step attack payload texts (up to 3)")
    archetype: Optional[str] = Field(default=None, description="Attack archetype identifier")
    l0_verified: Optional[bool] = Field(default=None, description="Whether attack was verified at L0")
    stability: Optional[str] = Field(default=None, description="Calibration stability e.g. 3/3")
    orig_text: Optional[str] = Field(default=None, description="Original text if rewritten in Stage B")


class MemoryWriteRules(BaseModel):
    model_config = ConfigDict(extra="forbid")

    deny_patterns: List[str] = Field(default_factory=list, description="Regex patterns to deny in memory writes")
    max_len: int = Field(default=120, ge=20, le=500, description="Max allowed length for note")
    note_format: Optional[str] = Field(default="fact_only", description="Format requirement for note")


class ToolPolicyRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    allowed: Optional[bool] = None
    redact_patterns: Optional[List[str]] = None
    tolerant_format: Optional[str] = Field(default=None, description="Format key (e.g. 'canary' or base pattern) to auto-generate tolerant redactions")
    redact_known_secrets: Optional[bool] = Field(default=None, description="Whether to automatically redact current secret across plain, spaced, reversed, base64, and hex forms")


class PatchGateConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    screen_tool_outputs: Optional[bool] = False
    screen_memory_reads: Optional[bool] = False
    threshold: Optional[float] = Field(default=0.3, ge=0.05, le=0.95)


class Patch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = Field(..., description="Patch version number")
    memory_write_rules: Optional[MemoryWriteRules] = None
    tool_policy: Optional[Dict[str, ToolPolicyRule]] = None
    gate: Optional[PatchGateConfig] = None
    notes: Optional[str] = Field(default="", description="One-line rationale")


class Event(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    # Common fields
    t: float = Field(..., description="Unix timestamp (seconds)")
    run_id: str = Field(..., description="Unique run identifier")
    round: RoundId = Field(..., description="Round identifier R0|R1|R2|CH")
    seq: int = Field(..., description="Monotonically increasing sequence number")
    type: EventType = Field(..., description="Event type")

    # message
    from_agent: Optional[str] = Field(default=None, alias="from")
    to: Optional[str] = None
    text: Optional[str] = None
    attack_id: Optional[str] = None

    # gate
    target: Optional[str] = None
    decision: Optional[GateDecision] = None
    confidence: Optional[float] = None
    blocked: Optional[bool] = None
    cached: Optional[bool] = None

    # agent_state
    agent: Optional[str] = None
    state: Optional[AgentStateType] = None

    # judge
    goal: Optional[GoalType] = None
    outcome: Optional[JudgeOutcome] = None
    evidence: Optional[str] = None
    decided_by: Optional[DecidedBy] = None
    controls: Optional[Dict[str, Any]] = None

    # patch
    action: Optional[PatchAction] = None
    version: Optional[int] = None
    summary: Optional[str] = None
    benign_pass_rate: Optional[float] = None

    # round_summary
    asr: Optional[float] = None
    asr_known: Optional[float] = None
    asr_heldout: Optional[float] = None
    gate_blocks: Optional[int] = None
    llm_calls: Optional[int] = None
    lyzr_calls: Optional[int] = None

    # budget
    llm_used: Optional[int] = None
    llm_cap: Optional[int] = None
    lyzr_used: Optional[int] = None
    lyzr_cap: Optional[int] = None

    # execution path
    path: Optional[str] = Field(default=None, description="Execution transport path: band+agent37 or in-process")


class RoundAttackResult(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    title: str
    category: str
    owasp: str
    goal: GoalType
    known: bool
    outcome: JudgeOutcome
    gate: Optional[Dict[str, Any]] = None
    latency_ms: int
    llm_calls: int
    controls: Optional[Dict[str, Any]] = None
    decided_by: Optional[DecidedBy] = None
    path: Optional[str] = Field(default=None, description="Execution transport path: band+agent37 or in-process")


class SubcategorySummary(BaseModel):
    model_config = ConfigDict(extra="allow")
    total: int
    passed: int


class BenignSummary(BaseModel):
    model_config = ConfigDict(extra="allow")
    total: int
    passed: int
    memory_utility: Optional[SubcategorySummary] = None
    trigger_word: Optional[SubcategorySummary] = None


class RoundResult(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: RoundId
    label: str
    gate: bool
    patch_version: int
    attacks: List[RoundAttackResult]
    asr: float
    asr_known: float
    asr_heldout: Optional[float] = None
    benign: BenignSummary
    gate_blocks: int
    llm_calls: int
    lyzr_calls: int
    errors: Optional[int] = Field(default=0, description="Count of worker execution errors excluded from ASR and retried")


class PatchEntry(BaseModel):
    model_config = ConfigDict(extra="allow")

    version: int
    status: PatchAction
    summary: str
    reason: Optional[str] = None
    patch: Optional[Patch] = None
    self_test: Optional[bool] = None


class ContagionSummary(BaseModel):
    enabled: bool
    asr_without_guard: float
    asr_with_guard: float


class BudgetSummary(BaseModel):
    llm_calls: int
    lyzr_calls: int


class Results(BaseModel):
    model_config = ConfigDict(extra="allow")

    run_id: str
    generated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    models: Dict[str, str]
    rounds: List[RoundResult]
    patches: List[PatchEntry]
    contagion: ContagionSummary
    budget: BudgetSummary
    sample: Optional[bool] = Field(default=False, description="Flag indicating if sample/mock data")
    blue_input: Optional[str] = Field(default=None, description="Incident log source for Blue: R1 or R0+R1")
    components: Optional[Dict[str, Any]] = Field(default=None, description="Execution component details (e.g. LLM/scripted)")
    transport: Optional[str] = Field(default=None, description="Transport layer used: band or loopback")
