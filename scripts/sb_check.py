import asyncio, os, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dotenv import load_dotenv
load_dotenv()
from infra.agent37 import Agent37Sandbox

async def run(cmd):
    sb = Agent37Sandbox(api_key=os.getenv('AGENT37_API_KEY'), instance_id=os.getenv('SANDBOX_ID'))
    res = await sb.exec_command(cmd)
    print("EXIT:", res.get("exit_code"))
    print("STDOUT:\n", res.get("stdout"))
    if res.get("stderr"):
        print("STDERR:\n", res.get("stderr"))

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "pwd"
    asyncio.run(run(cmd))
