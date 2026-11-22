#!/usr/bin/env python3
"""
Retry git push to origin main.
"""
import subprocess
import sys

def main():
    print("[*] Attempting git push origin main...")
    cmd = ["git", "push", "-u", "origin", "main"]
    res = subprocess.run(cmd)
    if res.returncode == 0:
        print("[+] Push succeeded!")
        sys.exit(0)
    else:
        print("[-] Push failed with returncode:", res.returncode, file=sys.stderr)
        sys.exit(res.returncode)

if __name__ == "__main__":
    main()
