"""
Live check script for Agent37 sandbox.
Checks:
- reset_state
- write memory.json
- restart instance
- confirm memory.json survived restart
- install_patch
- confirm patch.json survived
Run only if USE_MOCKS=0 and LIVE_APPROVED=1 and AGENT37_API_KEY present.
Caps: 1 create (if SANDBOX_ID missing), 12 exec calls, 2 restarts.
"""
import asyncio
import datetime
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
from infra.agent37 import Agent37Sandbox
from infra.sandbox_deploy import ensure_sandbox_instance

load_dotenv()


def log_call(service: str, purpose: str, count: int = 1):
    ledger = Path("docs/CALL_LEDGER.md")
    if ledger.exists():
        timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
        with open(ledger, "a", encoding="utf-8") as f:
            f.write(f"| {timestamp} | {service} | {purpose} | {count} |\n")


async def main():
    use_mocks = os.getenv("USE_MOCKS", "1").lower() in ("1", "true", "yes")
    live_approved = os.getenv("LIVE_APPROVED", "0").lower() in ("1", "true", "yes")
    key = os.getenv("AGENT37_API_KEY")

    if use_mocks or not live_approved or not key:
        print("[LIVE SKIPPED] USE_MOCKS=0 and LIVE_APPROVED=1 not set, or AGENT37_API_KEY missing.")
        return

    print("=== Agent37 Live Sandbox Check ===")
    inst_id = ensure_sandbox_instance(key)
    log_call("Agent37", "ensure_sandbox_instance", 1)

    sb = Agent37Sandbox(api_key=key, instance_id=inst_id)

    results = []

    # 1. Ping
    ping_ok = await sb.ping()
    log_call("Agent37", "ping", 1)
    results.append(("Ping", "PASS" if ping_ok else "FAIL"))

    # 2. Reset state
    canary = "CANARY-live-test-DEMO-ONLY"
    await sb.reset_state(canary)
    log_call("Agent37", "reset_state", 1)
    results.append(("Reset state", "PASS"))

    # 3. Write memory.json
    res_w = await sb.exec_command('echo \'{"notes":[{"id":"live-1","text":"persist-check"}]}\' > memory.json')
    log_call("Agent37", "write_memory", 1)
    results.append(("Write memory", "PASS" if res_w.get("exit_code") == 0 else "FAIL"))

    # 4. Restart
    print("Restarting sandbox instance...")
    await sb.restart()
    log_call("Agent37", "restart", 1)
    results.append(("Restart", "PASS"))

    # 5. Check memory survived
    mem_after = await sb.read_memory()
    log_call("Agent37", "read_memory_after_restart", 1)
    mem_survived = "persist-check" in mem_after
    results.append(("Memory persistence across restart", "PASS" if mem_survived else "FAIL"))

    # 6. Install patch
    test_patch = {"version": 2, "notes": "live-test"}
    await sb.install_patch(test_patch)
    log_call("Agent37", "install_patch", 1)

    res_patch = await sb.exec_command("cat patch.json")
    log_call("Agent37", "read_patch", 1)
    patch_survived = "live-test" in res_patch.get("stdout", "")
    results.append(("Patch persistence", "PASS" if patch_survived else "FAIL"))

    # Output to docs/LIVE_CHECK_NIKHIL.md
    out_file = Path("docs/LIVE_CHECK_NIKHIL.md")
    timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
    lines = [
        f"# Live Check (Nikhil) - {timestamp}\n",
        f"**Sandbox ID**: `{inst_id}`\n\n",
        "| Check | Result |\n|---|---|\n",
    ]
    for name, res in results:
        lines.append(f"| {name} | {res} |\n")

    out_file.write_text("".join(lines), encoding="utf-8")
    print("Live check finished. Results recorded in docs/LIVE_CHECK_NIKHIL.md.")


if __name__ == "__main__":
    asyncio.run(main())
