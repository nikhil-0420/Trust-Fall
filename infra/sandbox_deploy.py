"""
Owner: Nikhil (Phase N4)
Idempotent deployment script for Agent37 sandbox.
Ensures at most one instance exists, installs dependencies, uploads worker files and boot hook,
and launches worker in background.
"""
import base64
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx
from dotenv import load_dotenv

load_dotenv()

from agents.sync_config import sync_band_config


def ensure_sandbox_instance(api_key: str) -> str:
    sandbox_id = os.getenv("SANDBOX_ID")
    if sandbox_id and sandbox_id.strip():
        return sandbox_id.strip()

    # Create ONE instance
    url = "https://api.agent37.com/v1/instances"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {"template": "agent37-base"}

    with httpx.Client(timeout=30.0) as client:
        resp = client.post(url, headers=headers, json=payload)
        resp.raise_for_status()
        data = resp.json()
        new_id = data.get("id") or (data.get("instance", {}).get("id"))
        if not new_id:
            raise RuntimeError(f"Could not parse instance ID from Agent37 response: {data}")

    # Write to local .env
    env_path = Path(".env")
    if env_path.exists():
        content = env_path.read_text(encoding="utf-8")
        if "SANDBOX_ID=" in content:
            lines = [f"SANDBOX_ID={new_id}" if l.startswith("SANDBOX_ID=") else l for l in content.splitlines()]
            env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        else:
            with open(env_path, "a", encoding="utf-8") as f:
                f.write(f"\nSANDBOX_ID={new_id}\n")
    os.environ["SANDBOX_ID"] = new_id

    # Append reminder to docs/MANUAL_STEPS_NIKHIL.md
    manual_path = Path("docs/MANUAL_STEPS_NIKHIL.md")
    if manual_path.exists():
        with open(manual_path, "a", encoding="utf-8") as f:
            f.write("\n- Created Agent37 instance. Remember to delete it after submission: DELETE https://api.agent37.com/v1/instances/$SANDBOX_ID\n")

    return new_id


def upload_file_b64(client: httpx.Client, inst_id: str, key: str, local_path: Path, remote_path: str) -> None:
    data = local_path.read_bytes()
    b64 = base64.b64encode(data).decode("ascii")
    cmd = f"mkdir -p $(dirname {remote_path}) && echo '{b64}' | base64 -d > {remote_path}"
    for attempt in range(3):
        try:
            resp = client.post(
                f"https://sandbox.agent37.app/v1/instances/{inst_id}/exec",
                headers={"X-Agent37-Key": key, "Content-Type": "application/json"},
                json={"command": cmd},
                timeout=30.0,
            )
            if resp.json().get("exit_code") != 0:
                raise RuntimeError(f"Failed to upload {local_path} to {remote_path}: {resp.text}")
            return
        except Exception as e:
            if attempt == 2:
                raise e
            time.sleep(2.0 * (attempt + 1))


def deploy_worker() -> str:
    key = os.getenv("AGENT37_API_KEY")
    if not key:
        raise ValueError("AGENT37_API_KEY missing from environment")

    inst_id = ensure_sandbox_instance(key)
    print(f"Deploying Worker to Agent37 sandbox: {inst_id}...")

    with httpx.Client(timeout=120.0) as client:
        # 1. Install dependencies if not already present
        chk_resp = client.post(
            f"https://sandbox.agent37.app/v1/instances/{inst_id}/exec",
            headers={"X-Agent37-Key": key, "Content-Type": "application/json"},
            json={"command": "python3 -c 'import band_rest, google.genai, dotenv' 2>/dev/null"},
            timeout=15.0,
        )
        if chk_resp.json().get("exit_code") != 0:
            print("Installing python dependencies inside sandbox...")
            deps_cmd = "pip3 install --quiet 'band-sdk[langgraph]' pydantic pyyaml python-dotenv google-genai httpx"
            r_deps = client.post(
                f"https://sandbox.agent37.app/v1/instances/{inst_id}/exec",
                headers={"X-Agent37-Key": key, "Content-Type": "application/json"},
                json={"command": deps_cmd},
                timeout=120.0,
            )
            print("Dependencies install exit code:", r_deps.json().get("exit_code"))
        else:
            print("Dependencies already installed inside sandbox.")

        # 2. Upload worker package files
        root = Path(__file__).resolve().parent.parent
        files_to_upload = [
            (root / "agents" / "worker_core.py", "agents/worker_core.py"),
            (root / "agents" / "tools.py", "agents/tools.py"),
            (root / "agents" / "policy.py", "agents/policy.py"),
            (root / "agents" / "envelope.py", "agents/envelope.py"),
            (root / "agents" / "llm_gemini.py", "agents/llm_gemini.py"),
            (root / "agents" / "worker_band.py", "agents/worker_band.py"),
            (root / "agents" / "worker_band.py", "worker_band.py"),
            (root / "agents" / "sync_config.py", "agents/sync_config.py"),
            (root / "agents" / "__init__.py", "agents/__init__.py"),
            (root / "agents" / "prompts" / "worker_system.md", "agents/prompts/worker_system.md"),
            (root / "agents" / "prompts" / "worker_system_victim.md", "agents/prompts/worker_system_victim.md"),
            (root / "agents" / "prompts" / "worker_task.md", "agents/prompts/worker_task.md"),
            (root / "contracts" / "models.py", "contracts/models.py"),
            (root / "contracts" / "patch_validate.py", "contracts/patch_validate.py"),
            (root / "contracts" / "__init__.py", "contracts/__init__.py"),
            (root / "arena" / "interfaces.py", "arena/interfaces.py"),
            (root / "arena" / "factory.py", "arena/factory.py"),
            (root / "arena" / "mocks.py", "arena/mocks.py"),
            (root / "arena" / "__init__.py", "arena/__init__.py"),
            (root / ".env", ".env"),
        ]

        # Generate config
        config_path = sync_band_config()
        files_to_upload.append((config_path, "agent_config.yaml"))

        # Upload unified launcher and boot hook
        launcher_path = root / "infra" / "scripts" / "run_worker.sh"
        files_to_upload.append((launcher_path, "/home/node/run_worker.sh"))

        hook_path = root / "infra" / "hooks" / "post-restart.sh"
        files_to_upload.append((hook_path, "/home/node/.agent37/hooks/post-restart.sh"))

        for local_p, remote_p in files_to_upload:
            if local_p.exists():
                upload_file_b64(client, inst_id, key, local_p, remote_p)

        # 3. Create persistent, chmod 600 worker.env without printing values
        env_vars = [
            ("GEMINI_API_KEY", os.getenv("GEMINI_API_KEY", "")),
            ("BAND_AGENT_B_ID", os.getenv("BAND_AGENT_B_ID", "")),
            ("BAND_AGENT_B_KEY", os.getenv("BAND_AGENT_B_KEY", "")),
            ("BAND_ROOM_ID", os.getenv("BAND_ROOM_ID", "0ff67f25-e8a4-42a5-a4ac-54d0c4ed727e")),
            ("INTERNAL_TOKEN", os.getenv("INTERNAL_TOKEN", "")),
            ("MODEL_NAME", os.getenv("MODEL_NAME", "gemini-3.5-flash-lite")),
            ("WORKER_PROMPT", os.getenv("WORKER_PROMPT", "victim")),
            ("STATE_DIR", "data/worker_state"),
            ("GATE_URL", os.getenv("GATE_URL", "")),
            ("USE_MOCKS", "0"),
            ("LIVE_APPROVED", "1"),
            ("LLM_IMPL", "gemini"),
            ("GEMINI_MIN_INTERVAL_S", os.getenv("GEMINI_MIN_INTERVAL_S", "0")),
        ]
        env_content = "\n".join(f"export {k}='{v}'" for k, v in env_vars if v) + "\n"
        b64_env = base64.b64encode(env_content.encode("utf-8")).decode("ascii")
        cmd_env = f"mkdir -p /home/node/.trustfall && echo '{b64_env}' | base64 -d > /home/node/.trustfall/worker.env && chmod 600 /home/node/.trustfall/worker.env"
        client.post(
            f"https://sandbox.agent37.app/v1/instances/{inst_id}/exec",
            headers={"X-Agent37-Key": key, "Content-Type": "application/json"},
            json={"command": cmd_env},
            timeout=30.0,
        )

        # Make scripts executable
        client.post(
            f"https://sandbox.agent37.app/v1/instances/{inst_id}/exec",
            headers={"X-Agent37-Key": key, "Content-Type": "application/json"},
            json={"command": "chmod +x /home/node/run_worker.sh /home/node/.agent37/hooks/post-restart.sh 2>/dev/null || true"},
            timeout=30.0,
        )

        # 4. Start worker process using unified launcher
        safe_kill_cmd = (
            "if [ -f /home/node/worker.pid ]; then kill -9 $(cat /home/node/worker.pid) 2>/dev/null || true; fi; "
            "for pid in $(ps aux | grep '[w]orker_band.py' | awk '{print $2}'); do kill -9 $pid 2>/dev/null || true; done; "
            "sleep 1"
        )
        client.post(
            f"https://sandbox.agent37.app/v1/instances/{inst_id}/exec",
            headers={"X-Agent37-Key": key, "Content-Type": "application/json"},
            json={"command": safe_kill_cmd},
            timeout=30.0,
        )
        start_cmd = "/bin/bash /home/node/run_worker.sh && sleep 2; ps aux | grep python"
        r_start = client.post(
            f"https://sandbox.agent37.app/v1/instances/{inst_id}/exec",
            headers={"X-Agent37-Key": key, "Content-Type": "application/json"},
            json={"command": start_cmd},
            timeout=30.0,
        )
        print("Start result:\n", r_start.json().get("stdout", ""))

    print(f"Worker deployed successfully to sandbox {inst_id}.")
    return inst_id


if __name__ == "__main__":
    deploy_worker()
