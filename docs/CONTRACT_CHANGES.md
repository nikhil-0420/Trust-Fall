# Contract Changes (Additive-Only)

Log of all additions made to frozen contracts (`contracts/`, `arena/interfaces.py`, `arena/factory.py`).

| Date (UTC) | Task | Model / Protocol | Change Description | Backward-Compatible |
|---|---|---|---|---|
| 2026-11-22 | N0.3 | Results | Added optional field `sample: bool = False` to distinguish mock/sample runs | Yes |
| 2026-11-22 | H1.1 | RoundResult | Added optional field `errors: Optional[int] = 0` to log worker execution errors excluded from ASR | Yes |
| 2026-11-22 | N2.2 | WorkerOutcome | Added optional field `policy_denied: Optional[bool] = None` to record when policy blocks a tool | Yes |
| 2026-11-22 | N6.1 | WorkerOutcome | Added optional field `memory_note_blocked: Optional[bool] = None` to record when gate screening drops a note | Yes |
| 2026-11-22 | H2.4 | RoundResult | Added optional field `skipped_budget: Optional[int] = 0` to log attacks skipped due to budget caps | Yes |
| 2026-11-22 | H2.4 | RoundAttackResult | Added optional field `skipped_budget: Optional[bool] = False` to identify individual attacks skipped by budget | Yes |
| 2026-11-22 | H3.2 | PatchEntry | Added optional field `demo: Optional[bool] = False` to identify deliberately over-strict safety test patches in UI | Yes |
| 2026-11-22 | H5.1 | ErrorResponse | Added additive reason `"queue"` to 429 rate limit responses when challenge queue depth exceeds 10 | Yes |
| 2026-11-23 | C3 | Attack | Added optional fields `steps: Optional[List[str]] = None`, `archetype: Optional[str] = None`, `l0_verified: Optional[bool] = None`, `stability: Optional[str] = None`, `orig_text: Optional[str] = None` | Yes |
| 2026-11-23 | C9 | Results | Added optional field `blue_input: Optional[str] = None` ("R1" or "R0+R1") | Yes |
| 2026-11-23 | C10 | Results | Added optional field `components: Optional[Dict[str, Any]] = None` | Yes |
