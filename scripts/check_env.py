#!/usr/bin/env python3
"""
Environment variable checker for Trust Fall.
Prints whether required and optional environment variables are present or missing.
NEVER prints or logs any values.
"""
import os
from pathlib import Path
from dotenv import load_dotenv

EXPECTED_VARS = [
    # Model & AI providers
    "MODEL_NAME",
    "GEMINI_API_KEY",
    "LYZR_API_KEY",
    "AGENT37_API_KEY",
    "SANDBOX_ID",
    # BAND swarm agents
    "BAND_AGENT_A_ID",
    "BAND_AGENT_A_KEY",
    "BAND_AGENT_B_ID",
    "BAND_AGENT_B_KEY",
    "BAND_AGENT_RED_ID",
    "BAND_AGENT_RED_KEY",
    "BAND_AGENT_BLUE_ID",
    "BAND_AGENT_BLUE_KEY",
    "BAND_AGENT_ANALYST_ID",
    "BAND_AGENT_ANALYST_KEY",
    # Internal & Network
    "INTERNAL_TOKEN",
    "GATE_URL",
    "ALLOWED_ORIGINS",
    # Budget caps
    "LLM_DAILY_CAP",
    "LYZR_DAILY_CAP",
    # Flags & mock modes
    "USE_MOCKS",
    "LIVE_APPROVED",
    "TRANSPORT",
    "LLM_IMPL",
    "GATE_IMPL",
    "SANDBOX_IMPL",
    "BLUE_IMPL",
    "RED_IMPL",
]

def main():
    root = Path(__file__).resolve().parent.parent
    env_file = root / ".env"
    if env_file.exists():
        load_dotenv(env_file)
        print(f"Loaded environment from: {env_file.name}")
    else:
        print("Notice: .env file does not exist. Checking system environment.")

    print("\n" + "=" * 50)
    print(" TRUST FALL - ENVIRONMENT VARIABLE AUDIT")
    print("=" * 50)

    present_count = 0
    missing_count = 0

    for var in EXPECTED_VARS:
        val = os.environ.get(var)
        if val is not None and len(val.strip()) > 0:
            print(f"  [OK]      {var:25} PRESENT")
            present_count += 1
        else:
            print(f"  [MISSING] {var:25} NOT SET")
            missing_count += 1

    print("-" * 50)
    print(f"Summary: {present_count} present, {missing_count} missing (Values hidden)")
    print("=" * 50 + "\n")

if __name__ == "__main__":
    main()
