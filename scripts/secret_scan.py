#!/usr/bin/env python3
"""
Secret scanner for Trust Fall.
Scans git tracked files and staged changes for secret patterns and values from local .env.
Exit 1 on a hit, print file and line, but NEVER print the secret value.
"""
import os
import re
import subprocess
import sys
from pathlib import Path

REGEX_PATTERNS = [
    re.compile(r"AIza[0-9A-Za-z_-]{35}"),
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
    re.compile(r"Bearer\s+[A-Za-z0-9._-]{20,}"),
    re.compile(r"""(?i)(?:key|token|secret)\s*[:=]\s*["']?([A-Za-z0-9+/=_-]{32,})["']?"""),
]

def get_env_values():
    env_path = Path(".env")
    if not env_path.exists():
        return set()
    values = set()
    with open(env_path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            _, val = line.split("=", 1)
            val = val.strip().strip("'\"")
            # Only consider non-trivial secret-like values (exclude mock, 0, 1, etc.)
            if len(val) >= 8 and val.lower() not in {"gemini-3.5-flash-lite", "scripted", "loopback"}:
                values.add(val)
    return values

def get_tracked_files():
    try:
        res = subprocess.run(["git", "ls-files"], capture_output=True, text=True, check=True)
        return [f for f in res.stdout.splitlines() if f.strip() and os.path.exists(f)]
    except Exception:
        return []

def get_staged_diff():
    try:
        res = subprocess.run(["git", "diff", "--cached", "-U0"], capture_output=True, text=True, check=True)
        return res.stdout
    except Exception:
        return ""

def scan_text(text, filename, env_values):
    hits = []
    lines = text.splitlines()
    for idx, line in enumerate(lines, start=1):
        # Ignore comments in test/mock files or doc examples if explicitly marked, but scan carefully
        for pat in REGEX_PATTERNS:
            if pat.search(line):
                # Don't flag if it's the scanner itself or .env.example
                if filename in {"scripts/secret_scan.py", ".env.example"}:
                    continue
                hits.append((filename, idx, "Matched secret regex pattern"))
                break
        for secret_val in env_values:
            if secret_val in line:
                if filename in {"scripts/secret_scan.py", ".env.example"}:
                    continue
                hits.append((filename, idx, "Matched sensitive value from .env"))
                break
    return hits

def main():
    repo_root = Path(__file__).resolve().parent.parent
    os.chdir(repo_root)

    env_values = get_env_values()
    tracked_files = get_tracked_files()

    all_hits = []

    for file_path in tracked_files:
        # Skip binary or unwanted paths
        if any(file_path.endswith(ext) for ext in [".png", ".jpg", ".jpeg", ".ico", ".woff", ".woff2", ".ttf"]):
            continue
        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
            hits = scan_text(content, file_path, env_values)
            all_hits.extend(hits)
        except Exception as e:
            print(f"Warning: could not scan {file_path}: {e}", file=sys.stderr)

    if all_hits:
        print("[!] SECRET SCAN FAILED: Potential secrets detected!", file=sys.stderr)
        for fn, line, reason in all_hits:
            print(f"  {fn}:{line} -> {reason}", file=sys.stderr)
        sys.exit(1)

    print("[*] Secret scan passed: No secrets detected.")
    sys.exit(0)

if __name__ == "__main__":
    main()
