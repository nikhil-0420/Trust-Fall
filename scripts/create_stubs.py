#!/usr/bin/env python3
"""
Create project stubs and placeholder tests as specified in task N0.6.
"""
from pathlib import Path

stubs = {
    "agents/__init__.py": ("# Agents package", None),
    "agents/worker_core.py": ("Owner: Nikhil (Phase N1)\nVictim worker core agent logic.", "N1"),
    "agents/tools.py": ("Owner: Nikhil (Phase N1)\nWorker tools (read_memory, write_memory, send_report).", "N1"),
    "agents/policy.py": ("Owner: Nikhil (Phase N2)\nPatch enforcement and security policy hooks.", "N2"),
    "agents/envelope.py": ("Owner: Nikhil (Phase N2)\nEnvelope parser and validator.", "N2"),
    "agents/gate_client.py": ("Owner: Nikhil (Phase N2)\nClient for screening gate service.", "N2"),
    "agents/dispatcher.py": ("Owner: Nikhil (Phase N3)\nDispatcher agent managing ticket routing.", "N3"),
    "agents/worker_band.py": ("Owner: Nikhil (Phase N3)\nBAND swarm adapter for Worker.", "N3"),
    "agents/analyst.py": ("Owner: Nikhil (Phase N6)\nAnalyst agent for incident reporting.", "N6"),
    "agents/red.py": ("Owner: Nehaa (Phase H3)\nRed adversary attack generation agent.", "H3"),
    "agents/blue.py": ("Owner: Nikhil (Phase N5)\nBlue defense patch generation agent.", "N5"),

    "arena/judge.py": ("Owner: Nehaa (Phase H4)\nJudge for evaluating attack outcomes.", "H4"),
    "arena/referee.py": ("Owner: Nehaa (Phase H5)\nReferee orchestrating rounds and evaluations.", "H5"),
    "arena/rounds.py": ("Owner: Nehaa (Phase H5)\nRound execution loops (R0, R1, R2).", "H5"),
    "arena/benign.py": ("Owner: Nehaa (Phase H4)\nBenign ticket dataset and validation.", "H4"),
    "arena/rollback.py": ("Owner: Nehaa (Phase H5)\nPatch rollback and state restore.", "H5"),
    "arena/reports.py": ("Owner: Nehaa (Phase H6)\nIncident report generation.", "H6"),
    "arena/events.py": ("Owner: Nehaa (Phase H2)\nEvent logging and dispatch.", "H2"),
    "arena/transport_loopback.py": ("Owner: Nikhil (Phase N3)\nIn-process loopback transport.", "N3"),
    "arena/transport_band.py": ("Owner: Nikhil (Phase N3)\nBAND swarm transport.", "N3"),

    "api/__init__.py": ("# API package", None),
    "api/main.py": ("Owner: Nehaa (Phase H2)\nFastAPI application entry point.", "H2"),
    "api/gate.py": ("Owner: Nehaa (Phase H2)\nGate screening endpoint and Lyzr client.", "H2"),
    "api/cache.py": ("Owner: Nehaa (Phase H2)\nGate and LLM response caching.", "H2"),
    "api/budget.py": ("Owner: Nehaa (Phase H2)\nBudget governor and daily call caps.", "H2"),
    "api/limits.py": ("Owner: Nehaa (Phase H2)\nRate limiting for break endpoints.", "H2"),
    "api/challenge.py": ("Owner: Nehaa (Phase H7)\nChallenge break attempt management.", "H7"),
    "api/sse.py": ("Owner: Nehaa (Phase H2)\nServer-Sent Events streaming handler.", "H2"),

    "contracts/patch_validate.py": ("Owner: Nikhil (Phase N5)\nPatch schema and regex validator.", "N5"),

    "infra/__init__.py": ("# Infra package", None),
    "infra/agent37.py": ("Owner: Nikhil (Phase N4)\nAgent37 sandbox client implementation.", "N4"),
    "infra/sandbox_deploy.py": ("Owner: Nikhil (Phase N4)\nSandbox provisioning and deployment scripts.", "N4"),

    "scripts/run_mock_demo.py": ("Owner: Nikhil & Nehaa\nRun mock end-to-end demo.", "N0.6"),
}

def main():
    repo_root = Path(__file__).resolve().parent.parent

    for rel_path, (desc, phase) in stubs.items():
        p = repo_root / rel_path
        p.parent.mkdir(parents=True, exist_ok=True)
        if not p.exists():
            if phase is None:
                p.write_text(desc + "\n", encoding="utf-8")
            else:
                content = f'"""\n{desc}\n"""\n\nraise NotImplementedError("{rel_path} not yet implemented. Phase: {phase}")\n'
                p.write_text(content, encoding="utf-8")
            print(f"Created stub: {rel_path}")

    # agents/prompts
    prompts_dir = repo_root / "agents" / "prompts"
    prompts_dir.mkdir(parents=True, exist_ok=True)
    readme_prompt = prompts_dir / "README.md"
    if not readme_prompt.exists():
        readme_prompt.write_text("# Agent Prompts\nPrompt templates for Worker, Red, Blue, Analyst.\n", encoding="utf-8")

    # infra/hooks/post-restart.sh
    hooks_dir = repo_root / "infra" / "hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)
    hook_script = hooks_dir / "post-restart.sh"
    if not hook_script.exists():
        hook_script.write_text("#!/bin/bash\n# Hook executed on Agent37 sandbox boot/restart\necho 'Agent37 sandbox booted'\n", encoding="utf-8")

    # deploy/README.md
    deploy_dir = repo_root / "deploy"
    deploy_dir.mkdir(parents=True, exist_ok=True)
    deploy_readme = deploy_dir / "README.md"
    if not deploy_readme.exists():
        deploy_readme.write_text("# Deployment\nDeployment configs for Vercel (web), FastAPI (Arena API), Agent37 (Sandbox).\n", encoding="utf-8")

    # tests/ placeholder tests
    test_dirs = ["tests/agents", "tests/arena", "tests/api", "tests/contracts", "tests/infra", "tests/attacks"]
    for td in test_dirs:
        tdp = repo_root / td
        tdp.mkdir(parents=True, exist_ok=True)
        init_file = tdp / "__init__.py"
        if not init_file.exists():
            init_file.touch()
        tp = tdp / "test_placeholder.py"
        if not tp.exists():
            subname = td.split("/")[-1]
            content = f'"""Placeholder test for {subname}."""\n\ndef test_{subname}_placeholder():\n    assert True\n'
            tp.write_text(content, encoding="utf-8")
            print(f"Created test placeholder: {tp}")

if __name__ == "__main__":
    main()
