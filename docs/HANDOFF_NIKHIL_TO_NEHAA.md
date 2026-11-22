# Handoff: Nikhil to Nehaa

Welcome Nehaa! The core project scaffold is complete, tested, and pushed to `main`. You can clone or pull immediately.

---

## 1. What Exists

- **Contracts & Schemas (`contracts/`):**
  - `contracts/models.py`: Pydantic v2 models for `Event`, `Results`, `Patch`, `Attack`, `Envelope`, `GateResult`, `WorkerOutcome`.
  - `contracts/schemas/*.schema.json`: Exported JSON schemas for all contracts.
  - Frozen contract rule: contracts are additive-only. Any addition must be documented in `docs/CONTRACT_CHANGES.md`.
- **Interfaces & Protocols (`arena/interfaces.py`):**
  - Async protocols: `Transport`, `Sandbox`, `Gate`, `LLM`, `RedAgent`, `BlueAgent`.
- **Factory & Lazy Fallback (`arena/factory.py`):**
  - Resolves `get_transport()`, `get_sandbox()`, `get_gate()`, `get_llm()`, `get_red()`, `get_blue()`.
  - Configured with clearly designated sections for Nikhil and Nehaa.
- **Mock Implementations & Datasets (`arena/mocks.py`, `data/mock/`):**
  - `MockLLM`, `MockGate`, `FakeSandbox`, `MockTransport`, `ScriptedBlue`, `ScriptedRed`.
  - Pre-generated sample datasets: `results.json`, `events-R0.json`, `events-R1.json`, `events-R2.json`, `presets.json`, `leaderboard.json`, `attacks/library.json`.
  - **Ownership notice:** As agreed, `arena/mocks.py` is handed off to Nehaa after N0.
- **Frontend Skeleton (`web/`):**
  - Vite + React 18 + TypeScript + Tailwind.
  - Routes: `/`, `/arena`, `/break`, `/results`, `/about`.
  - Reads from `/mock/*.json` when `VITE_USE_MOCK=true`.
  - Synced using `python scripts/sync_mock_to_web.py`.
- **Tooling & Safety:**
  - `scripts/secret_scan.py` (pre-commit hook installed)
  - `scripts/check_env.py`
  - `scripts/digest.py`
  - `scripts/make_mock_data.py`
  - `scripts/export_schemas.py`

---

## 2. How to Run Mock Mode

1. Setup environment:
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # Or .venv\Scripts\activate on Windows
   pip install -r requirements.txt
   ```
2. Run mock generator:
   ```bash
   python scripts/make_mock_data.py
   ```
3. Run tests:
   ```bash
   pytest -q
   ```
4. Run web app:
   ```bash
   cd web
   npm install
   npm run dev
   ```

---

## 3. Ownership & Workstreams

Refer to `docs/OWNERSHIP.md`:
- **Nikhil owns:**
  - `agents/worker_core.py`, `tools.py`, `policy.py`, `envelope.py`, `gate_client.py`, `dispatcher.py`, `worker_band.py`, `analyst.py`, `blue.py`, `agents/prompts/`
  - `arena/transport_loopback.py`, `arena/transport_band.py`, `infra/`, `contracts/patch_validate.py`, `web/`, `tests/agents/`, `tests/infra/`
- **Nehaa owns:**
  - `arena/` (judge, referee, rounds, benign, rollback, reports, events, mocks)
  - `attacks/`
  - `api/` (main, gate, cache, budget, limits, challenge, sse)
  - `data/`
  - `deploy/`
  - `agents/red.py`
  - `tests/arena/`, `tests/api/`, `tests/attacks/`

---

## 4. Factory Flags Guide

- Default `.env` settings: `USE_MOCKS=1`, `LIVE_APPROVED=0`.
- In mock mode (`USE_MOCKS=1`), all getters return deterministic mocks immediately.
- When `USE_MOCKS=0`:
  - `TRANSPORT`: `mock` | `loopback` | `band`
  - `SANDBOX_IMPL`: `fake` | `agent37`
  - `GATE_IMPL`: `mock` | `lyzr`
  - `LLM_IMPL`: `mock` | `gemini`
  - `BLUE_IMPL`: `scripted` | `llm`
  - `RED_IMPL`: `scripted` | `llm`
- If an implementation or its API key is missing, the factory logs a single warning and safely falls back to the corresponding mock.
