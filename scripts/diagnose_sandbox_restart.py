#!/usr/bin/env python3
"""
scripts/diagnose_sandbox_restart.py
Step 3 Restart Diagnosis script for Agent37 sandbox Worker.
Runs 3 restart test cycles and records process count, logs, env names, and BAND ticket roundtrip.
"""
import asyncio
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv()

from agents.dispatcher_band import BandDispatcherAgent
from arena.interfaces import Envelope
from arena.transport_band import BandTransport
from infra.agent37 import Agent37Sandbox
from infra.sandbox_deploy import deploy_worker

async def run_diagnosis():
    print("=== STEP 3: RESTART DIAGNOSIS ===")
    
    # Pre-check / deploy
    deploy_worker()
    
    sandbox = Agent37Sandbox()
    
    # 1. Initial State Recording
    print("\n--- Initial State Inspection ---")
    res_ps = await sandbox.exec_command("ps aux | grep '[p]ython3'")
    print("Initial python processes:\n", res_ps.get("stdout", ""))
    
    res_hook = await sandbox.exec_command("ls -la /home/node/.agent37/hooks/ /tmp/post-restart.log 2>/dev/null || true")
    print("Hook files:\n", res_hook.get("stdout", ""))

    history = []

    # Run 3 restart cycles
    for cycle in range(1, 4):
        print(f"\n==========================================")
        print(f"  CYCLE {cycle}/3: Testing Sandbox Restart")
        print(f"==========================================")
        
        # Call restart
        t0 = time.time()
        print(f"[{cycle}] Calling sandbox.restart()...")
        await sandbox.restart()
        restart_duration = time.time() - t0
        print(f"[{cycle}] Restart returned in {restart_duration:.1f}s")
        
        # Wait a moment for stabilization
        await asyncio.sleep(3.0)
        
        # 1. Process count
        res_count = await sandbox.exec_command("pgrep -f 'worker_band.py' | wc -l")
        pcount = res_count.get("stdout", "0").strip()
        print(f"[{cycle}] worker_band.py process count: {pcount}")
        
        # 2. Worker log tail
        res_log = await sandbox.exec_command("tail -n 25 /home/node/worker.log 2>/dev/null || echo 'NO WORKER.LOG'")
        wlog = res_log.get("stdout", "").strip()
        print(f"[{cycle}] Tail of worker.log:\n{wlog}")
        
        # 3. Environment variable NAMES (NEVER print values)
        env_cmd = (
            "python3 -c \""
            "import os; "
            "pids = [p for p in os.listdir('/proc') if p.isdigit()]; "
            "for pid in pids: "
            "    try: "
            "        cmd = open(f'/proc/{pid}/cmdline', 'rb').read().replace(b'\\x00', b' ').decode('latin1', 'ignore'); "
            "        if 'worker_band.py' in cmd: "
            "            data = open(f'/proc/{pid}/environ', 'rb').read(); "
            "            names = [entry.split('=')[0] for entry in data.decode('latin1', 'ignore').split('\\x00') if '=' in entry]; "
            "            req = ['GEMINI_API_KEY', 'BAND_AGENT_B_ID', 'BAND_AGENT_B_KEY', 'BAND_ROOM_ID', 'INTERNAL_TOKEN', 'MODEL_NAME', 'WORKER_PROMPT']; "
            "            present = [r for r in req if r in names]; "
            "            print(f'PID {pid} cmd: {cmd.strip()}'); "
            "            print(f'Required env var names present: {present} (count {len(present)}/{len(req)})'); "
            "    except Exception as e: pass"
            "\""
        )
        res_env = await sandbox.exec_command(env_cmd)
        env_out = res_env.get("stdout", "").strip()
        print(f"[{cycle}] Process Environment Audit:\n{env_out}")
        
        # 4. Check whether post-restart hook ran
        res_hook_log = await sandbox.exec_command("cat /tmp/post-restart.log 2>/dev/null || echo 'NO /tmp/post-restart.log'")
        hlog = res_hook_log.get("stdout", "").strip()
        print(f"[{cycle}] Post-restart hook log:\n{hlog}")
        
        # 5. Check if benign ticket through BAND gets reply within 30s
        transport = BandTransport(sandbox=sandbox)
        dispatcher = BandDispatcherAgent()
        disp_task = asyncio.create_task(dispatcher.run())
        await dispatcher.wait_ready()
        
        ticket_id = f"DIAG-CYCLE-{cycle}-{int(time.time())}"
        env = Envelope(
            ticket_id=ticket_id,
            profile="L0",
            text="Hello, support team! Could you check my account status for ticket " + ticket_id + "?",
            kind="benign",
            attack_id=None,
        )
        
        print(f"[{cycle}] Sending benign ping ticket {ticket_id} over BAND (timeout 30s)...")
        reply_ok = False
        reply_snippet = ""
        try:
            outcome = await transport.send_ticket(env, timeout_s=30.0)
            if outcome.error:
                print(f"[{cycle}] Ticket error: {outcome.error}")
            elif outcome.outbound_messages:
                reply_ok = True
                reply_snippet = outcome.outbound_messages[0][:100]
                print(f"[{cycle}] Ticket SUCCESS! Received reply: {reply_snippet}")
            else:
                print(f"[{cycle}] Ticket returned no outbound messages")
        except Exception as e:
            print(f"[{cycle}] Ticket exception: {e}")
        finally:
            dispatcher.stop()
            disp_task.cancel()
        
        history.append({
            "cycle": cycle,
            "restart_duration_s": restart_duration,
            "worker_process_count": pcount,
            "worker_log_tail": wlog,
            "env_audit": env_out,
            "hook_log": hlog,
            "reply_ok": reply_ok,
            "reply_snippet": reply_snippet,
        })

    return history

if __name__ == "__main__":
    asyncio.run(run_diagnosis())
