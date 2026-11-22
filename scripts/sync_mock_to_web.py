#!/usr/bin/env python3
"""
Sync data/mock/ files into web/public/mock/ for frontend mock mode.
"""
import shutil
from pathlib import Path

def sync():
    root = Path(__file__).resolve().parent.parent
    src_dir = root / "data" / "mock"
    dst_dir = root / "web" / "public" / "mock"

    if not src_dir.exists():
        print(f"[!] Source {src_dir} does not exist. Run scripts/make_mock_data.py first.")
        return

    dst_dir.mkdir(parents=True, exist_ok=True)
    count = 0
    for item in src_dir.glob("*.json"):
        shutil.copy2(item, dst_dir / item.name)
        count += 1
    print(f"[*] Synced {count} mock files from {src_dir} to {dst_dir}")

if __name__ == "__main__":
    sync()
