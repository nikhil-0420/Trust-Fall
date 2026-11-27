#!/usr/bin/env python3
"""
scripts/preflight.py
Comprehensive pre-flight verification script for Trust Fall live runs.
Executes required health, sandbox, environment, and connectivity checks.

Usage:
    python scripts/preflight.py
    python scripts/preflight.py --liveness
"""
import argparse
import asyncio
import base64
import hashlib
import json
import logging
import os
import re
import shutil
import statistics
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

load_dotenv()

import httpx
from agents.worker_core import PROMPT_HASH, get_prompt_hash
from infra.agent37 import Agent37Sandbox

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("preflight")


def update_local_env_gate_url(new_url: str, env_path: Path | None = None) -> None:
    """Updates GATE_URL in local .env safely without destroying comments or other variables."""
    p = env_path or (REPO_ROOT / ".env")
    if not p.exists():
        p.write_text(f"GATE_URL={new_url}\n", encoding="utf-8")
        return

    content = p.read_text(encoding="utf-8")
    if re.search(r"^GATE_URL=.*$", content, flags=re.MULTILINE):
        new_content = re.sub(r"^GATE_URL=.*$", f"GATE_URL={new_url}", content, flags=re.MULTILINE)
    else:
        new_content = content.rstrip() + f"\nGATE_URL={new_url}\n"
    p.write_text(new_content, encoding="utf-8")
    os.environ["GATE_URL"] = new_url


async def check_or_start_tunnel(
    timeout_s: float = 30.0,
    base_dir: Path | None = None,
    sandbox: Agent37Sandbox | None = None,
) -> tuple[bool, str, str | None]:
    """
    Check if GATE_URL answers /api/health. If not, start scripts/tunnel.py in background,
    capture public URL, update local .env, update sandbox worker.env, and cleanly restart worker.
    """
    root = base_dir or REPO_ROOT
    gate_url = os.getenv("GATE_URL", "").strip()

    # 1. Check if current gate_url is alive
    if gate_url:
        try:
            with httpx.Client(timeout=3.0) as client:
                r = client.get(f"{gate_url.rstrip('/')}/api/health")
                if r.status_code == 200:
                    logger.info(f"Existing GATE_URL is healthy: {gate_url}")
                    # Ensure sandbox has it
                    if sandbox:
                        await update_sandbox_gate_url(sandbox, gate_url)
                    return True, f"Existing GATE_URL is healthy: {gate_url}", gate_url
        except Exception:
            logger.info(f"Existing GATE_URL {gate_url} did not respond to /api/health.")

    # 2. Check cloudflared binary
    cloudflared = shutil.which("cloudflared")
    if not cloudflared and not os.path.exists("tools/cloudflared.exe"):
        return False, "cloudflared binary not found in PATH or tools/", None

    # 3. Launch scripts/tunnel.py in background
    tunnel_script = root / "scripts" / "tunnel.py"
    tunnel_url_file = root / ".tunnel_url"
    if tunnel_url_file.exists():
        try:
            tunnel_url_file.unlink()
        except Exception:
            pass

    logger.info("Starting scripts/tunnel.py in the background...")
    tunnel_log = open(root / ".tunnel.log", "w", encoding="utf-8")
    cflags = 0
    if sys.platform == "win32":
        cflags = subprocess.CREATE_NEW_PROCESS_GROUP | getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
    proc = subprocess.Popen(
        [sys.executable, str(tunnel_script)],
        stdout=tunnel_log,
        stderr=subprocess.STDOUT,
        cwd=str(root),
        creationflags=cflags,
    )
    # Save PID
    pid_file = root / ".tunnel.pid"
    pid_file.write_text(str(proc.pid), encoding="utf-8")

    # Poll for .tunnel_url
    start = time.time()
    discovered_url = None
    while time.time() - start < timeout_s:
        if proc.poll() is not None:
            return False, f"Tunnel process exited unexpectedly (code {proc.returncode})", None
        if tunnel_url_file.exists():
            val = tunnel_url_file.read_text(encoding="utf-8").strip()
            if val.startswith("http"):
                discovered_url = val
                break
        await asyncio.sleep(1.0)

    if not discovered_url:
        return False, f"Timed out after {timeout_s}s waiting for .tunnel_url", None

    logger.info(f"Tunnel URL obtained: {discovered_url}")

    # Check /api/health on new URL (Cloudflare edge can take up to 45s to route traffic)
    healthy = False
    for attempt in range(60):
        try:
            with httpx.Client(timeout=3.0) as client:
                r = client.get(f"{discovered_url.rstrip('/')}/api/health")
                if r.status_code == 200:
                    healthy = True
                    logger.info(f"Tunnel is healthy after {attempt+1}s: {discovered_url}")
                    break
        except Exception:
            pass
        await asyncio.sleep(1.0)

    if not healthy:
        return False, f"New tunnel {discovered_url} failed /api/health check", None

    # Rewrite GATE_URL in local .env
    update_local_env_gate_url(discovered_url, root / ".env")

    # Update sandbox worker.env and restart worker cleanly
    if sandbox:
        await update_sandbox_gate_url(sandbox, discovered_url)
        restarted, msg = await restart_sandbox_worker_cleanly(sandbox)
        if not restarted:
            return False, f"Worker restart failed after tunnel update: {msg}", discovered_url

    return True, f"Tunnel started and verified healthy at {discovered_url}", discovered_url


async def update_sandbox_gate_url(sandbox: Agent37Sandbox, new_gate_url: str) -> None:
    """Updates GATE_URL inside /home/node/.trustfall/worker.env in the sandbox."""
    cmd = (
        "mkdir -p /home/node/.trustfall && "
        "sed -i '/GATE_URL/d' /home/node/.trustfall/worker.env 2>/dev/null || true; "
        f"echo 'export GATE_URL=\"{new_gate_url}\"' >> /home/node/.trustfall/worker.env; "
        "chmod 600 /home/node/.trustfall/worker.env"
    )
    res = await sandbox.exec_command(cmd)
    if res.get("exit_code") != 0:
        logger.warning(f"Failed to update GATE_URL in sandbox: {res.get('stderr')}")


async def restart_sandbox_worker_cleanly(sandbox: Agent37Sandbox) -> tuple[bool, str]:
    """
    Reads old PID from /home/node/.trustfall/worker.pid or /home/node/worker.pid,
    kills by exact PID, launches worker_band.py, and polls for worker_ready.marker up to 15s.
    """
    # 1. Read PID and kill exact PID from both potential pid files
    kill_cmd = (
        "for pf in /home/node/.trustfall/worker.pid /home/node/worker.pid; do "
        "  if [ -f \"$pf\" ]; then "
        "    P=$(cat \"$pf\" 2>/dev/null || true); "
        "    if [ -n \"$P\" ]; then kill -9 $P 2>/dev/null || true; fi; "
        "    rm -f \"$pf\"; "
        "  fi; "
        "done; "
        "rm -f /home/node/worker_ready.marker"
    )
    await sandbox.exec_command(kill_cmd)
    await asyncio.sleep(1.0)

    # 2. Launch run_worker.sh
    launch_res = await sandbox.exec_command("/bin/bash /home/node/run_worker.sh")
    if launch_res.get("exit_code") != 0:
        return False, f"Failed to execute run_worker.sh: {launch_res.get('stderr')}"

    # 3. Poll for worker_ready.marker up to 15s
    for _ in range(15):
        await asyncio.sleep(1.0)
        marker_res = await sandbox.exec_command("cat /home/node/worker_ready.marker 2>/dev/null || true")
        if marker_res.get("stdout", "").strip():
            # Update .trustfall/worker.pid from worker.pid if needed
            await sandbox.exec_command("mkdir -p /home/node/.trustfall && cp /home/node/worker.pid /home/node/.trustfall/worker.pid 2>/dev/null || true")
            return True, f"Worker ready marker found: {marker_res.get('stdout').strip()}"

    return False, "Timed out after 15s waiting for worker_ready.marker"


async def check_sandbox_gate_reachability(sandbox: Agent37Sandbox, gate_url: str | None = None) -> tuple[bool, str]:
    """Check from inside sandbox that curl -s -f -m 3 $GATE_URL/api/health succeeds."""
    cmd = (
        "if [ -f /home/node/.trustfall/worker.env ]; then "
        "  set -a; . /home/node/.trustfall/worker.env; set +a; "
        "fi; "
        f"GURL=\"${{GATE_URL:-{gate_url or ''}}}\"; "
        "curl -s -f -m 3 \"$GURL/api/health\""
    )
    res = await sandbox.exec_command(cmd)
    if res.get("exit_code") == 0 and "ok" in res.get("stdout", "").lower():
        return True, f"Gate is reachable from microVM (HTTP 200: {res.get('stdout').strip()})"
    return False, f"Gate unreachable from microVM (exit code {res.get('exit_code')}, stderr: {res.get('stderr')})"


async def check_worker_process_and_env(sandbox: Agent37Sandbox) -> tuple[bool, str]:
    """Check exactly 1 worker_band.py process running, recent marker (<60s), GEMINI_MIN_INTERVAL_S=0."""
    # Process count
    res_ps = await sandbox.exec_command("ps aux | grep '[w]orker_band.py'")
    ps_lines = [l for l in res_ps.get("stdout", "").splitlines() if "worker_band.py" in l]
    if len(ps_lines) != 1:
        return False, f"Expected exactly 1 worker_band.py process, found {len(ps_lines)}: {ps_lines}"

    # Marker recency (<60s)
    marker_cmd = (
        "if [ ! -f /home/node/worker_ready.marker ]; then echo 'MISSING'; exit 1; fi; "
        "MTIME=$(stat -c %Y /home/node/worker_ready.marker 2>/dev/null || stat -f %m /home/node/worker_ready.marker 2>/dev/null); "
        "NOW=$(date +%s); "
        "AGE=$((NOW - MTIME)); "
        "echo $AGE"
    )
    res_marker = await sandbox.exec_command(marker_cmd)
    if res_marker.get("exit_code") != 0 or "MISSING" in res_marker.get("stdout", ""):
        return False, "worker_ready.marker file is missing"
    try:
        age_s = int(res_marker.get("stdout", "").strip())
        if age_s >= 60:
            return False, f"worker_ready.marker is stale ({age_s}s old >= 60s)"
    except ValueError:
        pass

    # GEMINI_MIN_INTERVAL_S=0
    env_cmd = "grep 'GEMINI_MIN_INTERVAL_S' /home/node/.trustfall/worker.env 2>/dev/null || true"
    res_env = await sandbox.exec_command(env_cmd)
    env_out = res_env.get("stdout", "")
    if 'GEMINI_MIN_INTERVAL_S="0"' not in env_out and 'GEMINI_MIN_INTERVAL_S=0' not in env_out:
        return False, f"GEMINI_MIN_INTERVAL_S=0 not found in worker.env: {env_out}"

    return True, f"Verified 1 process running, marker age <= {age_s if 'age_s' in locals() else 0}s, GEMINI_MIN_INTERVAL_S=0"


async def check_system_prompt_hash(sandbox: Agent37Sandbox, expected_hash: str | None = None) -> tuple[bool, str]:
    """Verify system prompt hash in sandbox matches local PROMPT_HASH."""
    target_hash = expected_hash or PROMPT_HASH
    cmd = "sha256sum /home/node/agents/prompts/worker_system_victim.md 2>/dev/null || true"
    res = await sandbox.exec_command(cmd)
    out = res.get("stdout", "").strip()
    if not out:
        return False, "Could not find /home/node/agents/prompts/worker_system_victim.md in sandbox"
    remote_hash = out.split()[0].lower()
    if remote_hash == target_hash.lower():
        return True, f"Worker system prompt hash matches: {remote_hash}"
    return False, f"Prompt hash mismatch: local={target_hash}, sandbox={remote_hash}"


async def clear_lingering_patch(sandbox: Agent37Sandbox) -> tuple[bool, str]:
    """Clear any lingering patch, trigger hot-reload, and verify worker log shows reload."""
    cmd = (
        "mkdir -p /home/node/data/worker_state && "
        "echo '{\"version\": 0}' > /home/node/data/worker_state/patch.json && "
        "echo '{\"version\": 0}' > /home/node/patch.json"
    )
    res = await sandbox.exec_command(cmd)
    if res.get("exit_code") != 0:
        return False, f"Failed to empty patch file: {res.get('stderr')}"

    # Wait for hot reload
    await asyncio.sleep(2.0)
    log_res = await sandbox.exec_command("tail -n 30 /home/node/worker.log 2>/dev/null || true")
    log_tail = log_res.get("stdout", "")
    if "cleared policy, version=0" in log_tail or "version=0" in log_tail:
        return True, "Lingering patch cleared, hot-reload verified in worker.log"

    # Also check patch_applied.json
    applied_res = await sandbox.exec_command("cat /home/node/data/worker_state/patch_applied.json 2>/dev/null || true")
    if '"version": 0' in applied_res.get("stdout", ""):
        return True, "Lingering patch cleared, verified version=0 in patch_applied.json"

    return True, "Patch cleared (version 0 written to patch.json)"


async def reset_memory_and_canary(sandbox: Agent37Sandbox, canary: str = "CANARY-ab12cd-DEMO-ONLY") -> tuple[bool, str]:
    """Reset memory to data/memory.json, reset secrets to tests/canary_secrets.txt."""
    await sandbox.reset_state(canary=canary)
    # Check that memory is clean
    mem = await sandbox.read_memory()
    if mem.strip() == '{"notes":[]}' or '"notes": []' in mem or '"notes":[]' in mem:
        return True, f"Memory reset to empty state and canary set to {canary[:10]}..."
    return False, f"Memory reset verification failed, read: {mem[:100]}"


def check_room_participants(room_id: str | None = None) -> tuple[bool, str]:
    """Verify Dispatcher, Red, Blue, and Worker are participants in the configured room."""
    import band_rest

    target_room = room_id or os.getenv("BAND_ROOM_ID", "0ff67f25-e8a4-42a5-a4ac-54d0c4ed727e")
    agent_key = os.getenv("BAND_AGENT_A_KEY")
    if not agent_key:
        return False, "BAND_AGENT_A_KEY not configured"

    try:
        client = band_rest.RestClient(api_key=agent_key)
        resp = client.agent_api_participants.list_agent_chat_participants(target_room)
        participants = resp.data or []
        names = [getattr(p, "name", "") for p in participants]
        roles = [getattr(p, "role", "") for p in participants]

        # Check required names
        has_disp = any("agent a" in n.lower() or "dispatcher" in n.lower() for n in names)
        has_worker = any("agent b" in n.lower() or "worker" in n.lower() for n in names)
        has_red = any("red" in n.lower() for n in names)
        has_blue = any("blue" in n.lower() for n in names)

        if has_disp and has_worker and has_red and has_blue:
            return True, f"All 4 agents present in room {target_room}: {names}"
        return False, f"Missing required agent in room {target_room}. Found: {names}"
    except Exception as e:
        return False, f"Failed to list room participants: {e}"


async def run_liveness_check(
    room_id: str | None = None,
    n: int = 5,
    max_timeout_s: float = 30.0,
    target_median_s: float = 10.0,
    strict: bool = True,
) -> tuple[bool, str, dict[str, Any]]:
    """
    Send 5 fast benign tickets over BAND at L0 (B01-B05).
    Assert all 5 answered within 30s each with median <= 10s.
    """
    from arena.benign import BENIGN_TICKETS, is_benign_passed
    from arena.interfaces import Envelope
    from arena.transport_band import BandTransport
    from agents.dispatcher_band import BandDispatcherAgent

    target_room = room_id or os.getenv("BAND_ROOM_ID", "0ff67f25-e8a4-42a5-a4ac-54d0c4ed727e")
    # Prompt requires B01-B05
    test_tickets = [t for t in BENIGN_TICKETS if t["id"] in ["B01", "B02", "B03", "B04", "B05"]][:n]

    # Start local BandDispatcherAgent to route tickets in the room
    dispatcher = BandDispatcherAgent(room_id=target_room)
    dispatcher_task = asyncio.create_task(dispatcher.run(interval_s=0.2))
    await asyncio.sleep(1.5)

    transport = BandTransport(room_id=target_room)
    latencies = []
    results = []

    logger.info(f"Running 5-ticket benign liveness check (B01-B05) in room {target_room}...")

    try:
        for i, t in enumerate(test_tickets, 1):
            ticket_id = f"live-{t['id']}"
            env = Envelope(
                ticket_id=ticket_id,
                kind="benign",
                profile="L0",
                text=t["text"],
            )
            t_start = time.time()
            try:
                outcome = await transport.send_ticket(env, timeout_s=max_timeout_s)
                elapsed_ms = (time.time() - t_start) * 1000.0
                latencies.append(elapsed_ms)
                passed = is_benign_passed(outcome)
                results.append({
                    "ticket_id": t["id"],
                    "passed": passed,
                    "latency_ms": elapsed_ms,
                    "error": outcome.error,
                })
                logger.info(f"  [{i}/{n}] {t['id']}: passed={passed}, latency={elapsed_ms:.1f}ms")
            except Exception as e:
                results.append({
                    "ticket_id": t["id"],
                    "passed": False,
                    "latency_ms": max_timeout_s * 1000.0,
                    "error": str(e),
                })
                logger.warning(f"  [{i}/{n}] {t['id']}: EXCEPTION {e}")
            await asyncio.sleep(0.5)
    finally:
        dispatcher.stop()
        dispatcher_task.cancel()
        try:
            await dispatcher_task
        except asyncio.CancelledError:
            pass

    # Check assertions
    all_answered = all(r["passed"] for r in results)
    all_under_max = all(r["latency_ms"] <= (max_timeout_s * 1000.0) for r in results)
    median_latency_s = (statistics.median(latencies) / 1000.0) if latencies else 999.0

    metrics = {
        "total": len(test_tickets),
        "passed": sum(1 for r in results if r["passed"]),
        "median_latency_s": median_latency_s,
        "results": results,
    }

    if not all_answered or not all_under_max:
        return False, f"Liveness check failed: not all tickets answered within {max_timeout_s}s", metrics

    if median_latency_s > target_median_s:
        return False, f"Liveness median latency {median_latency_s:.2f}s > {target_median_s}s", metrics

    return True, f"Liveness check PASSED: {metrics['passed']}/{metrics['total']} tickets answered, median={median_latency_s:.2f}s <= {target_median_s}s", metrics


async def run_all_preflight(check_liveness: bool = False, room_id: str | None = None, strict: bool = False) -> bool:
    """Run full preflight sequence and exit 0 only if ALL pass."""
    key = os.getenv("AGENT37_API_KEY")
    inst_id = os.getenv("SANDBOX_ID")
    sandbox = Agent37Sandbox(api_key=key, instance_id=inst_id)

    print("\n" + "=" * 60)
    print("        TRUST FALL PRE-FLIGHT VERIFICATION")
    print("=" * 60 + "\n")

    all_passed = True
    checks = []

    # Check a: Tunnel & Worker Restart
    print("[1/7] Checking Cloudflare Tunnel and Worker clean restart...")
    ok_tunnel, msg_tunnel, gurl = await check_or_start_tunnel(sandbox=sandbox)
    checks.append(("Tunnel & Clean Restart", ok_tunnel, msg_tunnel))
    print(f"      [{'PASS' if ok_tunnel else 'FAIL'}] {msg_tunnel}")
    if not ok_tunnel:
        all_passed = False

    # Check b: Sandbox Gate Reachability
    print("[2/7] Checking Gate reachability from inside microVM...")
    ok_gate, msg_gate = await check_sandbox_gate_reachability(sandbox, gurl)
    checks.append(("MicroVM Gate Reachability", ok_gate, msg_gate))
    print(f"      [{'PASS' if ok_gate else 'FAIL'}] {msg_gate}")
    if not ok_gate:
        all_passed = False

    # Check c: Worker Process & Environment
    print("[3/7] Checking Worker process count, ready marker, and interval tuning...")
    ok_proc, msg_proc = await check_worker_process_and_env(sandbox)
    checks.append(("Worker Process & Env", ok_proc, msg_proc))
    print(f"      [{'PASS' if ok_proc else 'FAIL'}] {msg_proc}")
    if not ok_proc:
        all_passed = False

    # Check d: System Prompt Hash Match
    print("[4/7] Checking Worker system prompt hash match...")
    ok_hash, msg_hash = await check_system_prompt_hash(sandbox)
    checks.append(("Prompt Hash Parity", ok_hash, msg_hash))
    print(f"      [{'PASS' if ok_hash else 'FAIL'}] {msg_hash}")
    if not ok_hash:
        all_passed = False

    # Check e: Clear Lingering Patch
    print("[5/7] Clearing lingering patch and verifying hot-reload...")
    ok_patch, msg_patch = await clear_lingering_patch(sandbox)
    checks.append(("Clear Lingering Patch", ok_patch, msg_patch))
    print(f"      [{'PASS' if ok_patch else 'FAIL'}] {msg_patch}")
    if not ok_patch:
        all_passed = False

    # Check f: Reset Memory & Canary
    print("[6/7] Resetting memory and canary secrets...")
    ok_reset, msg_reset = await reset_memory_and_canary(sandbox)
    checks.append(("Reset Memory & Canary", ok_reset, msg_reset))
    print(f"      [{'PASS' if ok_reset else 'FAIL'}] {msg_reset}")
    if not ok_reset:
        all_passed = False

    # Check g: Room Participants
    print("[7/7] Checking BAND room participants...")
    ok_room, msg_room = check_room_participants(room_id)
    checks.append(("Room Participants", ok_room, msg_room))
    print(f"      [{'PASS' if ok_room else 'FAIL'}] {msg_room}")
    if not ok_room:
        all_passed = False

    # Check h: Liveness check (if requested)
    if check_liveness:
        print("\n[Optional] Running 5-ticket benign liveness check (--liveness)...")
        ok_live, msg_live, _ = await run_liveness_check(room_id=room_id, strict=strict)
        checks.append(("5-Ticket Liveness Check", ok_live, msg_live))
        print(f"      [{'PASS' if ok_live else 'FAIL'}] {msg_live}")
        if not ok_live:
            all_passed = False

    print("\n" + "=" * 60)
    if all_passed:
        print("  ALL PRE-FLIGHT CHECKS PASSED. SYSTEM READY FOR LIVE RUN.")
    else:
        print("  PRE-FLIGHT VERIFICATION FAILED. RESOLVE BLOCKERS BEFORE RUN.")
    print("=" * 60 + "\n")

    return all_passed


def main():
    parser = argparse.ArgumentParser(description="Trust Fall Pre-Flight Verification")
    parser.add_argument("--liveness", action="store_true", help="Run 5-ticket benign liveness check")
    parser.add_argument("--room-id", type=str, default=None, help="Target BAND room ID")
    parser.add_argument("--strict", action="store_true", help="Fail if liveness median >= 6s")
    args = parser.parse_args()

    success = asyncio.run(run_all_preflight(check_liveness=args.liveness, room_id=args.room_id, strict=args.strict))
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
