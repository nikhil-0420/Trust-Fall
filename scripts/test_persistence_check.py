#!/usr/bin/env python3
"""
scripts/test_persistence_check.py
Step 5 Persistence Check:
Writes marker to memory.json and patch.json, calls sandbox.restart(),
verifies file persistence, worker process count == 1, and benign ticket reply.
"""
import asyncio
import base64
import json
import sys
import time
from pathlib import Path
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

load_dotenv()

from agents.dispatcher_band import BandDispatcherAgent
from arena.interfaces import Envelope
from arena.transport_band import BandTransport
from infra.agent37 import Agent37Sandbox

async def run_persistence_check():
    print("=== STEP 5: PERSISTENCE CHECK ===")
    sandbox = Agent37Sandbox()
    
    marker_str = f"PERSIST_MARKER_{int(time.time())}"
    patch_obj = {"version": 99, "rules": [f"PERSIST_RULE_{int(time.time())}"]}
    
    print(f"1. Writing marker '{marker_str}' to /home/node/memory.json...")
    m_json = json.dumps({"marker": marker_str, "records": []})
    b64_m = base64.b64encode(m_json.encode()).decode()
    res_m = await sandbox.exec_command(f"echo '{b64_m}' | base64 -d > /home/node/memory.json")
    
    print(f"2. Writing test patch to /home/node/patch.json...")
    p_json = json.dumps(patch_obj)
    b64_p = base64.b64encode(p_json.encode()).decode()
    res_p = await sandbox.exec_command(f"echo '{b64_p}' | base64 -d > /home/node/patch.json")
    
    print("3. Calling sandbox.restart()...")
    t0 = time.time()
    await sandbox.restart()
    dur = time.time() - t0
    print(f"Restart finished in {dur:.1f}s")
    
    # Verify persistence
    print("4. Verifying /home/node/memory.json persistence...")
    res_m_check = await sandbox.exec_command("cat /home/node/memory.json")
    m_content = res_m_check.get("stdout", "")
    memory_persisted = marker_str in m_content
    print(f"   Memory persisted: {memory_persisted} (marker found: {marker_str in m_content})")
    
    print("5. Verifying /home/node/patch.json persistence...")
    res_p_check = await sandbox.exec_command("cat /home/node/patch.json")
    p_content = res_p_check.get("stdout", "")
    patch_persisted = "PERSIST_RULE" in p_content
    print(f"   Patch persisted: {patch_persisted}")
    
    print("6. Verifying Worker process count...")
    count_cmd = (
        "python3 -c \""
        "import os; "
        "my_pid = str(os.getpid()); "
        "workers = [p for p in os.listdir('/proc') if p.isdigit() and p != my_pid and "
        "open(f'/proc/{p}/cmdline','rb').read().startswith(b'python') and "
        "b'worker_band.py' in open(f'/proc/{p}/cmdline','rb').read()]; "
        "print(len(workers))\""
    )
    res_wc = await sandbox.exec_command(count_cmd)
    pcount_raw = res_wc.get("stdout", "0").strip()
    try:
        pcount = int(pcount_raw)
    except Exception:
        pcount = -1
    print(f"   Active python worker_band.py processes: {pcount}")
    
    print("7. Testing benign ticket roundtrip over BAND...")
    transport = BandTransport(sandbox=sandbox)
    dispatcher = BandDispatcherAgent()
    disp_task = asyncio.create_task(dispatcher.run())
    await dispatcher.wait_ready()
    
    ticket_id = f"PERSIST-CHECK-{int(time.time())}"
    env = Envelope(
        ticket_id=ticket_id,
        profile="L0",
        text=f"Hello support! Verifying system persistence for ticket {ticket_id}.",
        kind="benign",
        attack_id=None,
    )
    
    ticket_success = False
    reply_snippet = ""
    try:
        outcome = await transport.send_ticket(env, timeout_s=30.0)
        if outcome.error:
            print(f"   Ticket error: {outcome.error}")
        elif outcome.outbound_messages:
            ticket_success = True
            reply_snippet = outcome.outbound_messages[0][:100]
            print(f"   Ticket SUCCESS! Reply: {reply_snippet}")
        else:
            print("   Ticket returned no outbound messages")
    finally:
        dispatcher.stop()
        disp_task.cancel()
        
    # Reset patch.json to default empty
    await sandbox.exec_command("echo '{}' > /home/node/patch.json && echo '{\"version\": 0}' > /home/node/patch_applied.json")
    
    overall = memory_persisted and patch_persisted and (pcount == 1) and ticket_success
    print(f"\nOVERALL PERSISTENCE CHECK: {'PASS' if overall else 'FAIL'}")
    return {
        "memory_persisted": memory_persisted,
        "patch_persisted": patch_persisted,
        "pcount": pcount,
        "ticket_success": ticket_success,
        "reply_snippet": reply_snippet,
        "duration_s": dur,
        "overall": overall,
    }

if __name__ == "__main__":
    res = asyncio.run(run_persistence_check())
