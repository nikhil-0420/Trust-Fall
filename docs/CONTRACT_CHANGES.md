# Contract Changes (Additive-Only)

Log of all additions made to frozen contracts (`contracts/`, `arena/interfaces.py`, `arena/factory.py`).

| Date (UTC) | Task | Model / Protocol | Change Description | Backward-Compatible |
|---|---|---|---|---|
| 2026-11-22 | N0.3 | Results | Added optional field `sample: bool = False` to distinguish mock/sample runs | Yes |
| 2026-11-22 | H1.1 | RoundResult | Added optional field `errors: Optional[int] = 0` to log worker execution errors excluded from ASR | Yes |
| 2026-11-22 | N2.2 | WorkerOutcome | Added optional field `policy_denied: Optional[bool] = None` to record when policy blocks a tool | Yes |
