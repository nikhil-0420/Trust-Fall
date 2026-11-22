#!/usr/bin/env python3
"""
scripts/tunnel.py
Starts uvicorn API and creates a Cloudflare Tunnel for judging demo.
If cloudflared is not installed, prints manual installation instructions.
Owner: Nehaa (WS-D D9, D10)
"""
import os
import re
import shutil
import subprocess
import sys
import time


def get_cloudflared_path() -> str | None:
    """
    Locates cloudflared executable in priority order:
    1. CLOUDFLARED_PATH environment variable
    2. PATH lookup
    3. tools/cloudflared.exe (or tools/cloudflared) inside repo
    """
    env_path = os.getenv("CLOUDFLARED_PATH")
    if env_path and os.path.isfile(env_path):
        return env_path

    path_bin = shutil.which("cloudflared")
    if path_bin:
        return path_bin

    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    candidates = [
        os.path.join(repo_root, "tools", "cloudflared.exe"),
        os.path.join(repo_root, "tools", "cloudflared"),
    ]
    for candidate in candidates:
        if os.path.isfile(candidate):
            return candidate

    return None


def print_cloudflared_install_instructions():
    print("\n[!] 'cloudflared' binary is not installed or not found in PATH.")
    print("To install cloudflared manually on your system:")
    print("  - Windows (winget): winget install Cloudflare.cloudflared")
    print("  - macOS (brew):     brew install cloudflared")
    print("  - Linux (deb):       sudo apt install cloudflared (or download from https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/)")
    print("\nAfter installing, re-run: python scripts/tunnel.py\n")


def main():
    cloudflared_path = get_cloudflared_path()
    if not cloudflared_path:
        print_cloudflared_install_instructions()
        return

    port = os.getenv("PORT", "8000")
    print(f"[*] Starting Trust Fall API on port {port}...")

    api_proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "api.main:app", "--port", str(port)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    time.sleep(1.5)

    print("[*] Launching Cloudflare Tunnel...")
    tunnel_cmd = [cloudflared_path, "tunnel", "--url", f"http://localhost:{port}"]

    try:
        tunnel_proc = subprocess.Popen(
            tunnel_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )

        public_url_found = False
        url_regex = re.compile(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com")

        while True:
            line = tunnel_proc.stdout.readline()
            if not line:
                break
            match = url_regex.search(line)
            if match and not public_url_found:
                public_url = match.group(0)
                print("\n" + "=" * 60)
                print(f"  Trust Fall Public Tunnel URL: {public_url}")
                print(f"  Set GATE_URL={public_url} in sandbox .env")
                print(f"  Set VITE_API_URL={public_url} in frontend Vercel settings")
                print("=" * 60 + "\n")
                public_url_found = True

    except KeyboardInterrupt:
        print("\n[*] Shutting down tunnel and API...")
    finally:
        api_proc.terminate()
        try:
            tunnel_proc.terminate()
        except Exception:
            pass


if __name__ == "__main__":
    main()
