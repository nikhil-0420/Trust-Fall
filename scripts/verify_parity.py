import asyncio
import hashlib
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

load_dotenv()
from infra.agent37 import Agent37Sandbox
from arena.transport_band import BandTransport
from arena.interfaces import Envelope

async def verify_parity():
    sb = Agent37Sandbox()
    
    # 1. SHA256 of worker_system_victim.md
    local_sha = hashlib.sha256(Path("agents/prompts/worker_system_victim.md").read_bytes()).hexdigest()
    res1 = await sb.exec_command("sha256sum agents/prompts/worker_system_victim.md")
    remote_sha = res1.get("stdout", "").split()[0] if res1.get("stdout") else ""
    print(f"SHA256 Match: {local_sha == remote_sha} (local: {local_sha[:10]}, remote: {remote_sha[:10]})")
    
    # 2. Exactly one worker_band.py process
    res2 = await sb.exec_command("ps aux | grep '[w]orker_band.py'")
    lines = [l for l in res2.get("stdout", "").splitlines() if "worker_band.py" in l]
    print(f"Worker processes count: {len(lines)} (lines: {lines})")
    if len(lines) != 1:
        print("Normalizing to exactly 1 process...")
        await sb.exec_command("killall -9 python3 2>/dev/null || true")
        await asyncio.sleep(1)
        await sb.exec_command("cd /home/node && (nohup python3 -u worker_band.py > worker.log 2>&1 &)")
        await asyncio.sleep(3)
        res2_retry = await sb.exec_command("ps aux | grep '[w]orker_band.py'")
        lines = [l for l in res2_retry.get("stdout", "").splitlines() if "worker_band.py" in l]
        print(f"Worker processes count normalized: {len(lines)} (lines: {lines})")
    
    # 3. Worker can reach GATE_URL/api/health
    cmd = "python3 -c \"import os, httpx, dotenv; dotenv.load_dotenv(); r = httpx.get(os.getenv('GATE_URL') + '/api/health', timeout=10.0); print(r.status_code, r.text)\""
    res3 = await sb.exec_command(cmd)
    print("Worker reachability to GATE_URL/api/health:", res3.get("stdout", "").strip())
    
    # 4. Send one benign ticket through BAND and confirm a reply
    print("Testing benign ticket delivery over BAND transport...")
    from agents.dispatcher import Dispatcher
    from agents.dispatcher_band import BandDispatcherAgent
    disp_agent = BandDispatcherAgent(dispatcher=Dispatcher())
    disp_task = asyncio.create_task(disp_agent.run(interval_s=1.0))
    await asyncio.sleep(2.0)

    try:
        transport = BandTransport()
        env = Envelope(
            ticket_id="TICKET-BENIGN-PARITY-002",
            profile="L0",
            kind="benign",
            text="Hello, could you please confirm what payment methods you accept?",
        )
        resp = await transport.send_ticket(env, timeout_s=35.0)
        print("Benign reply received:", resp.outbound_messages if resp.outbound_messages else "(EMPTY)")
    finally:
        disp_agent.stop()
        disp_task.cancel()

if __name__ == "__main__":
    asyncio.run(verify_parity())
