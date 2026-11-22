# Codebase Ownership

| Nikhil owns | Nehaa owns | Frozen contract (additive-only for her) |
|---|---|---|
| `agents/worker_core.py`, `tools.py`, `policy.py`, `envelope.py`, `gate_client.py`, `dispatcher.py`, `worker_band.py`, `analyst.py`, `blue.py`, `agents/prompts/` | `arena/` (except below), `attacks/`, `api/`, `data/`, `deploy/`, `agents/red.py`, `arena/mocks.py` (after N0) | `contracts/`, `arena/interfaces.py`, `arena/factory.py` |
| `arena/transport_loopback.py`, `arena/transport_band.py`, `infra/`, `contracts/patch_validate.py`, `web/`, `tests/agents/`, `tests/infra/` | `tests/arena/`, `tests/api/`, `tests/attacks/` | |

Nehaa also owns scripts/run_mock_demo.py, scripts/run_full.py, scripts/measure_limits.py.

