#!/usr/bin/env python3
"""
Install git pre-commit hook that runs scripts/secret_scan.py.
"""
import os
import sys
from pathlib import Path

def main():
    repo_root = Path(__file__).resolve().parent.parent
    hook_dir = repo_root / ".git" / "hooks"
    hook_dir.mkdir(parents=True, exist_ok=True)
    pre_commit = hook_dir / "pre-commit"

    hook_content = """#!/bin/sh
python scripts/secret_scan.py
"""
    pre_commit.write_text(hook_content, encoding="utf-8")
    if os.name != "nt":
        pre_commit.chmod(0o755)
    print(f"[*] Pre-commit hook installed at {pre_commit}")

if __name__ == "__main__":
    main()
