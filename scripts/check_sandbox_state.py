import asyncio
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

load_dotenv()

from infra.agent37 import Agent37Sandbox

async def main():
    sb = Agent37Sandbox(api_key=os.getenv("AGENT37_API_KEY"), instance_id=os.getenv("SANDBOX_ID"))
    ping_ok = await sb.ping()
    print("Sandbox ping:", ping_ok)
    
    ps_res = await sb.exec_command("ps aux | grep [p]ython")
    print("PS output:\n" + ps_res.get("stdout", ""))
    
    ready_res = await sb.exec_command("cat /home/node/worker_ready.marker 2>/dev/null || echo NO_MARKER")
    print("Ready marker:", ready_res.get("stdout", "").strip())
    
    env_res = await sb.exec_command("grep -E '(BAND_ROOM_ID|STATE_DIR|MODEL_NAME)' /home/node/.trustfall/worker.env 2>/dev/null || echo NO_ENV")
    print("Worker env non-secret fields:\n" + env_res.get("stdout", "").strip())
    
    log_res = await sb.exec_command("tail -n 25 /home/node/worker.log 2>/dev/null || echo NO_LOG")
    print("Worker log tail:\n" + log_res.get("stdout", "").strip())

if __name__ == "__main__":
    asyncio.run(main())
