"""
scripts/redeploy_sandbox_worker.py
Uploads updated worker code to Agent37 sandbox, sets tuning env,
and restarts the worker by exact PID through the unified launcher.
"""
import asyncio
import base64
import os
import sys
import time
from pathlib import Path
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

load_dotenv()
from infra.agent37 import Agent37Sandbox
import httpx

def upload_file(client: httpx.Client, inst_id: str, key: str, local_p: Path, remote_p: str):
    data = local_p.read_bytes()
    b64 = base64.b64encode(data).decode("ascii")
    cmd = f"mkdir -p $(dirname {remote_p}) && echo '{b64}' | base64 -d > {remote_p}"
    resp = client.post(
        f"https://sandbox.agent37.app/v1/instances/{inst_id}/exec",
        headers={"X-Agent37-Key": key, "Content-Type": "application/json"},
        json={"command": cmd},
        timeout=30.0,
    )
    if resp.json().get("exit_code") != 0:
        raise RuntimeError(f"Failed to upload {local_p}: {resp.text}")

async def main():
    key = os.getenv("AGENT37_API_KEY")
    inst_id = os.getenv("SANDBOX_ID")
    sb = Agent37Sandbox(api_key=key, instance_id=inst_id)

    print(f"Deploying updates to sandbox {inst_id}...")
    with httpx.Client(timeout=60.0) as client:
        # Upload core files
        for f in [
            "agents/worker_band.py",
            "agents/worker_core.py",
            "agents/policy.py",
            "agents/gate_client.py",
            "agents/tools.py",
            "agents/llm_gemini.py",
            "arena/interfaces.py",
            "contracts/models.py",
        ]:
            local_path = REPO_ROOT / f
            remote_path = f"/home/node/{f}"
            upload_file(client, inst_id, key, local_path, remote_path)
            print(f"Uploaded {f} -> {remote_path}")
        # Also upload worker_band.py directly to /home/node/worker_band.py
        upload_file(client, inst_id, key, REPO_ROOT / "agents/worker_band.py", "/home/node/worker_band.py")
        print("Uploaded agents/worker_band.py -> /home/node/worker_band.py")

    # Ensure worker.env tuning variables
    update_env_cmd = (
        "sed -i '/GEMINI_MIN_INTERVAL_S/d' /home/node/.trustfall/worker.env 2>/dev/null || true; "
        "echo 'export GEMINI_MIN_INTERVAL_S=\"0\"' >> /home/node/.trustfall/worker.env; "
        "sed -i '/BAND_POLL_INTERVAL_S/d' /home/node/.trustfall/worker.env 2>/dev/null || true; "
        "echo 'export BAND_POLL_INTERVAL_S=\"0.2\"' >> /home/node/.trustfall/worker.env; "
        "chmod 600 /home/node/.trustfall/worker.env"
    )
    res_env = await sb.exec_command(update_env_cmd)
    print("Env updated:", res_env.get("exit_code"))

    # Relaunch worker by exact PID
    restart_cmd = (
        "if [ -f /home/node/worker.pid ]; then "
        "  PID=$(cat /home/node/worker.pid); "
        "  if [ -n \"$PID\" ]; then kill -9 $PID 2>/dev/null || true; fi; "
        "fi; "
        "rm -f /home/node/worker_ready.marker; "
        "sleep 1; "
        "/bin/bash /home/node/run_worker.sh"
    )
    res_restart = await sb.exec_command(restart_cmd)
    print("Restart result:", res_restart.get("stdout", ""))

    # Wait for ready marker
    print("Waiting for worker_ready.marker...")
    ready = False
    for _ in range(15):
        await asyncio.sleep(1.0)
        res_m = await sb.exec_command("cat /home/node/worker_ready.marker 2>/dev/null")
        if res_m.get("stdout", "").strip():
            print(f"Ready marker found: {res_m.get('stdout').strip()}")
            ready = True
            break

    # Verify single process
    res_ps = await sb.exec_command("ps aux | grep '[w]orker_band.py'")
    ps_lines = [l for l in res_ps.get("stdout", "").splitlines() if "worker_band.py" in l]
    print(f"Worker processes running ({len(ps_lines)}):")
    for l in ps_lines:
        print(" ", l)

    if ready and len(ps_lines) == 1:
        print("SUCCESS: Worker restarted cleanly by exact PID, single process running and ready.")
    else:
        print(f"WARNING: ready={ready}, process_count={len(ps_lines)}")

if __name__ == "__main__":
    asyncio.run(main())
