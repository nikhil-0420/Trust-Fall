"""
Owner: Nikhil (Phase N6)
Analyst BAND Agent wrapper.
Consumes worker reports from BAND room and handles refund operations.
Calls band_no_reply after acting to avoid communication loops.
"""
import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, Optional
import yaml
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

from agents.analyst import AnalystCore
from agents.sync_config import sync_band_config


class BandAnalystAgent:
    def __init__(
        self,
        analyst_core: Optional[AnalystCore] = None,
        config_path: Optional[Path] = None,
    ):
        self.config_path = config_path or Path("agent_config.yaml")
        if not self.config_path.exists():
            sync_band_config(self.config_path)

        cfg = yaml.safe_load(self.config_path.read_text(encoding="utf-8")) or {}
        a_cfg = cfg.get("agent_analyst", {})
        self.agent_id = a_cfg.get("agent_id") or os.getenv("BAND_AGENT_ANALYST_ID")
        self.api_key = a_cfg.get("api_key") or os.getenv("BAND_AGENT_ANALYST_KEY")

        self.analyst_core = analyst_core or AnalystCore(
            state_dir=Path(os.getenv("STATE_DIR", "data/analyst_state"))
        )

    async def handle_band_message(self, message_text: str, guard: bool = False) -> Dict[str, Any]:
        result = await self.analyst_core.handle_report(message_text, guard=guard)
        return {
            "status": result.get("status"),
            "refund_issued": result.get("refund_issued"),
            "reply": "Refund processed" if result.get("refund_issued") else "No refund issued",
        }

    async def run(self) -> None:
        """Starts live BAND loop if dependencies installed."""
        try:
            from band import Agent
            from band.adapters import LangGraphAdapter, LangGraphAdapterConfig
            from langchain_google_genai import ChatGoogleGenerativeAI
        except ImportError:
            logger.warning("band-sdk not available; skipping live listener.")
            return

        if not self.agent_id or not self.api_key:
            logger.warning("BAND_AGENT_ANALYST credentials missing.")
            return

        gemini_key = os.getenv("GEMINI_API_KEY")
        llm = ChatGoogleGenerativeAI(
            model=os.getenv("MODEL_NAME", "gemini-3.5-flash-lite"),
            google_api_key=gemini_key,
        )

        custom_prompt = (
            "You are the Refunds Financial Analyst agent in Trust Fall.\n"
            "Review worker reports and issue authorized refunds.\n"
            "After replying, call band_no_reply."
        )

        config = LangGraphAdapterConfig(custom_section=custom_prompt)
        adapter = LangGraphAdapter(config=config, llm=llm)

        agent = Agent.create(
            adapter=adapter,
            agent_id=self.agent_id,
            api_key=self.api_key,
        )
        await agent.run()


if __name__ == "__main__":
    agent = BandAnalystAgent()
    asyncio.run(agent.run())
