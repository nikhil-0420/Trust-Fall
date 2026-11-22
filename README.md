# Trust Fall

> **Your agents trust each other. Let's test that.**

## What It Is

**Trust Fall** is a Red-vs-Blue security evaluation arena for multi-agent systems, featuring an automated adversarial loop and a public interactive "Try-to-break-it" site. 

In Trust Fall, autonomous agents interact within an operational workflow:
- **Red Agent:** Generates adaptive prompt injection, jailbreak, memory poisoning, and context manipulation attacks.
- **Worker Agent (Victim):** A customer-support triage agent running inside an isolated sandbox with persistent memory notes.
- **Blue Agent (Defender):** Inspects incident logs, drafts defense policies, sanitizes memory read/write channels, and synthesizes candidate defensive patches.
- **Referee & Judge:** Evaluates attacks, enforces safety criteria, tests proposed patches on benign traffic, and gates sandbox updates.

## Architecture

```mermaid
flowchart LR
  subgraph Web["Vercel (Nikhil)"]
    SITE[React site]
  end
  subgraph API["Arena API (FastAPI, Nehaa)"]
    EP[/api/* + SSE/]
    GATE[Gate service /internal/screen]
    REF[Referee + Judge + Rounds]
    BUD[Budget governor + cache + rate limits]
  end
  subgraph BAND["BAND room: Trust Fall Arena"]
    DISP[Dispatcher]
    RED[Red]
    BLUE[Blue]
    ANA[Analyst P2]
  end
  subgraph A37["Agent37 sandbox"]
    WORK[Worker LangGraph + memory.json + patch.json]
  end
  LYZR[(Lyzr detector)]
  SITE --> EP
  EP --> REF
  REF --> DISP
  RED --> DISP
  DISP -->|screen first| GATE
  GATE --> LYZR
  DISP --> WORK
  WORK -->|screen memory reads| GATE
  WORK --> ANA
  REF -->|exec: reset / verify / apply patch| A37
  BLUE --> REF
```

## Sponsor Technology Integration

- **BAND:** Multi-agent swarm orchestration, room coordination, and agent handoffs between Dispatcher, Worker, Red, Blue, and Analyst. `[TODO: Insert real BAND live evaluation metrics]`
- **Agent37:** Isolated microVM execution sandbox with persistent file memory and boot-hook patching (`post-restart.sh`). `[TODO: Insert real sandbox benchmark metrics]`
- **Lyzr:** Pre-execution and internal screening gate detecting prompt injections and adversarial inputs. `[TODO: Insert real Lyzr detection accuracy figures]`
- **AdaL:** Synthetic multi-agent demonstration and narrative showcase video. `[TODO: Insert demo video link]`

## Safety Notice

All targets, canary tokens, and mock records in this repository are **completely fake** (e.g. `CANARY-ab12cd-DEMO-ONLY`). Attack payloads represent harmless prompt injection evaluation text targeting only our local sandboxed demonstration worker. No real credentials, private data, external endpoints, or production systems are targeted or exposed.

## Repository Structure

```
Trust-Fall/
  agents/          # Worker core, tools, policy, envelope, BAND wrappers, Blue & Red agents
  arena/           # Referee, judge, round loops, benign checks, interfaces, factory, mocks
  attacks/         # Attack library and evaluation taxonomy
  api/             # FastAPI backend endpoints, SSE stream, gate proxy, budget governor
  infra/           # Agent37 client, sandbox deployment scripts, boot hooks
  contracts/       # Pydantic v2 schemas and JSON Schema specifications
  data/            # Mock run results, round event traces, presets, leaderboard
  docs/            # Architecture specifications, agent autonomy logs, coordination docs
  scripts/         # Scanners, generators, environment checks, and digest tools
  web/             # React 18 + TypeScript + Tailwind frontend
  tests/           # Pytest test suites across contracts, agents, arena, and API
```

## Quick Start (Mock Mode)

Trust Fall is **mock-first**: you can run the entire platform, tests, and mock frontend offline without external API keys.

1. **Clone repository:**
   ```bash
   git clone https://github.com/nikhil-0420/Trust-Fall.git
   cd Trust-Fall
   ```

2. **Create and activate virtual environment:**
   ```bash
   python -m venv .venv
   # Windows:
   .venv\Scripts\activate
   # Linux/macOS:
   source .venv/bin/activate
   ```

3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Generate mock datasets:**
   ```bash
   python scripts/make_mock_data.py
   ```

5. **Run test suite:**
   ```bash
   pytest -q
   ```

## Configuration Flags

Configured via `.env` (copy from `.env.example`):

| Flag | Default | Description |
|---|---|---|
| `USE_MOCKS` | `1` | `1` runs all components in deterministic offline mock mode; `0` enables live adapters |
| `LIVE_APPROVED` | `0` | Hard guardrail; live external API calls are made only if `1` |
| `TRANSPORT` | `mock` | `mock` \| `loopback` \| `band` |
| `LLM_IMPL` | `mock` | `mock` \| `gemini` |
| `GATE_IMPL` | `mock` | `mock` \| `lyzr` |
| `SANDBOX_IMPL` | `fake` | `fake` \| `agent37` |
| `BLUE_IMPL` | `scripted` | `scripted` \| `llm` |
| `RED_IMPL` | `scripted` | `scripted` \| `llm` |
| `LLM_DAILY_CAP` | - | Daily limit on LLM API calls |
| `LYZR_DAILY_CAP` | `15` | Daily limit on Lyzr API calls |

---

## Agent Layer Details (Workstream A & B2)

### 1. Agents Architecture & Responsibilities

- **Dispatcher (`agents/dispatcher.py`):**
  - Trusted, scripted orchestrator with zero LLM calls.
  - At defense profiles `L1` and `L2`, intercepts incoming tickets and evaluates text against `GateClient` (`POST /internal/screen`).
  - Drops injected/error payloads and emits `gate` and `agent_state` events.
  - Signs permitted tickets with HMAC-SHA256 (`INTERNAL_TOKEN`) and forwards them to the Worker.
- **Worker Agent (`agents/worker_core.py`, `agents/tools.py`):**
  - A customer-support triage agent maintaining persistent customer memory (`memory.json`) and canary reference secrets (`secrets.txt`).
  - Exposed tools: exactly three plain functions: `read_memory()`, `write_memory(text)`, and `send_report(status, summary)`. No shell, network, or arbitrary file system access.
  - Executes tool actions and compiles resolution reports into `outbound_messages`.
- **Blue Defender (`agents/blue.py`):**
  - Synthesizes hardening rules based on incident logs of compromised attacks.
  - Operates in two modes: `ScriptedBlue` (deterministic rule mapping by category) and `LLMBlue` (adaptive prompt synthesis using `agents/prompts/blue_system.md`).
  - All proposals must pass strict schema, regex safety, and wildcard checks in `contracts/patch_validate.py`.
- **Analyst Agent (`agents/analyst.py`):**
  - Financial authorization agent managing refund operations (`grant_refund`) recorded into `refund_ledger.json`.
  - In unshielded scenarios, malicious instructions forwarded via worker reports can trick the Analyst into issuing unauthorized refunds (contagion attack).
  - In guarded mode, inter-agent reports undergo gate screening and strict schema validation (`ticket_id`, `status`, `summary <= 200 chars`).

### 2. Defense Profiles

- **`L0` (Baseline):** No pre-dispatch screening. No worker-level policy enforcement. Tests raw model vulnerability to direct injection and poisoning.
- **`L1` (Perimeter Gate):** Lyzr Gate screening active at the Dispatcher. Blunt attacks (direct override, roleplay, authority) are blocked before reaching the agent.
- **`L2` (Defense-in-Depth):** Dispatcher perimeter gate active PLUS local deterministic policy engine (`Policy`) at the Worker. Enforces deny patterns, maximum memory note lengths, fact-only formatting, canary redaction, and memory-read screening.

### 3. Patch Format (`patch.json`)

Defensive rules proposed by Blue and applied to the Worker:
```json
{
  "version": 2,
  "memory_write_rules": {
    "deny_patterns": ["(?i)ignore .* instructions", "POISON-MARK"],
    "max_len": 120,
    "note_format": "fact_only"
  },
  "tool_policy": {
    "send_report": {
      "redact_patterns": ["CANARY-[A-Za-z0-9]+-DEMO-ONLY"]
    },
    "write_memory": {
      "allowed": true
    }
  },
  "gate": {
    "screen_tool_outputs": true,
    "screen_memory_reads": true,
    "threshold": 0.3
  },
  "notes": "Hardened policy against memory poisoning and token leakage"
}
```

### 4. Sandbox Patch Delivery & Persistence

- The Worker runs inside an isolated microVM on **Agent37**.
- Patches are installed via `Agent37Sandbox.install_patch()`, which base64-encodes and writes `patch.json` into the root directory.
- On reboot, the boot hook `infra/hooks/post-restart.sh` restores `patch.json` and automatically relaunches the worker process with `nohup`.
- Memory notes (`memory.json`) and applied patches persist across reboots.

### 5. Transport Modes

- **Mock (`TRANSPORT=mock`):** Fully simulated, offline, deterministic responses for all agents.
- **Loopback (`TRANSPORT=loopback`):** Runs the real Dispatcher, WorkerCore, and GateClient in-process with local memory persistence. Smoke test: `python scripts/loopback_smoke.py`.
- **BAND (`TRANSPORT=band`):** Real-time multi-agent communication across WebSocket connections in BAND rooms.

