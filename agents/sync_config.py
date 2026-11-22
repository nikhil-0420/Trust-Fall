"""
Owner: Nikhil (Phase N3)
Sync configuration script for BAND agents.
Reads keys from .env and writes agent_config.yaml (gitignored).
Never prints secrets.
"""
import os
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv

load_dotenv()


def sync_band_config(output_path: Optional[Path] = None) -> Path:
    target = output_path or Path("agent_config.yaml")

    agent_a_id = os.getenv("BAND_AGENT_A_ID", "")
    agent_a_key = os.getenv("BAND_AGENT_A_KEY", "")
    agent_b_id = os.getenv("BAND_AGENT_B_ID", "")
    agent_b_key = os.getenv("BAND_AGENT_B_KEY", "")
    agent_red_id = os.getenv("BAND_AGENT_RED_ID", "")
    agent_red_key = os.getenv("BAND_AGENT_RED_KEY", "")
    agent_blue_id = os.getenv("BAND_AGENT_BLUE_ID", "")
    agent_blue_key = os.getenv("BAND_AGENT_BLUE_KEY", "")
    agent_analyst_id = os.getenv("BAND_AGENT_ANALYST_ID", "")
    agent_analyst_key = os.getenv("BAND_AGENT_ANALYST_KEY", "")

    config_content = (
        f"agent_a:\n"
        f"  agent_id: \"{agent_a_id}\"\n"
        f"  api_key: \"{agent_a_key}\"\n"
        f"agent_b:\n"
        f"  agent_id: \"{agent_b_id}\"\n"
        f"  api_key: \"{agent_b_key}\"\n"
        f"agent_red:\n"
        f"  agent_id: \"{agent_red_id}\"\n"
        f"  api_key: \"{agent_red_key}\"\n"
        f"agent_blue:\n"
        f"  agent_id: \"{agent_blue_id}\"\n"
        f"  api_key: \"{agent_blue_key}\"\n"
        f"agent_analyst:\n"
        f"  agent_id: \"{agent_analyst_id}\"\n"
        f"  api_key: \"{agent_analyst_key}\"\n"
    )

    target.write_text(config_content, encoding="utf-8")
    return target


if __name__ == "__main__":
    out = sync_band_config()
    print(f"BAND configuration generated at: {out}")
