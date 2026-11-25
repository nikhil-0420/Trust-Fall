import asyncio
import os
import sys
from pathlib import Path

# Add project root
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from dotenv import load_dotenv
load_dotenv()

from infra.agent37 import Agent37Sandbox

async def main():
    sb = Agent37Sandbox(api_key=os.getenv("AGENT37_API_KEY"), instance_id=os.getenv("SANDBOX_ID"))
    res = await sb.exec_command("cat /home/node/.trustfall/worker.env")
    lines = res.get("stdout", "").splitlines()
    print("=== WORKER.ENV VARIABLE NAMES & NUMERIC TUNING VALUES ===")
    for l in lines:
        l = l.strip()
        if not l or l.startswith("#"):
            continue
        if l.startswith("export "):
            l = l[7:]
        if "=" in l:
            k, v = l.split("=", 1)
            v_clean = v.strip("'\"")
            is_numeric = v_clean.replace(".", "", 1).isdigit()
            if is_numeric:
                print(f"  {k} = {v_clean}")
            else:
                print(f"  {k} = [REDACTED_OR_NON_NUMERIC]")

if __name__ == "__main__":
    asyncio.run(main())
