"""
Owner: Nikhil (Phase N3)
Worker BAND Agent wrapper.
Wraps WorkerCore as a BAND agent using LangGraphAdapter and band-sdk.
Verifies envelope signature, runs WorkerCore.handle, and posts report mentioning Dispatcher.
Must never @mention itself to avoid 422 cannot_mention_self.
"""
import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

from agents.sync_config import sync_band_config
from agents.worker_core import WorkerCore
from arena.factory import get_llm
from arena.interfaces import Envelope


class BandWorkerAgent:
    def __init__(
        self,
        worker_core: WorkerCore | None = None,
        config_path: Path | None = None,
        dispatcher_handle: str | None = None,
    ):
        self.config_path = config_path or Path("agent_config.yaml")
        if not self.config_path.exists():
            sync_band_config(self.config_path)

        cfg = yaml.safe_load(self.config_path.read_text(encoding="utf-8")) or {}
        b_cfg = cfg.get("agent_b", {})
        self.agent_id = b_cfg.get("agent_id") or os.getenv("BAND_AGENT_B_ID")
        self.api_key = b_cfg.get("api_key") or os.getenv("BAND_AGENT_B_KEY")
        self.dispatcher_handle = dispatcher_handle or os.getenv("DISPATCHER_HANDLE", "nikhil.guddanti/agent-a")

        self.worker_core = worker_core or WorkerCore(
            llm=get_llm(),
            state_dir=Path(os.getenv("STATE_DIR", "data/worker_state")),
        )
        self.room_id = os.getenv("BAND_ROOM_ID", "2259e40a-1833-49f4-b647-596ac09f99ea")
        self.processed_msg_ids: set[str] = set()
        self.is_running = False
        self.rest_client = None
        if self.api_key:
            try:
                from band_rest import RestClient
                self.rest_client = RestClient(api_key=self.api_key)
            except ImportError:
                self.rest_client = None

    def _post_to_room(self, content: str) -> None:
        if self.rest_client is None:
            return
        try:
            from band_rest.types import ChatMessageRequest, ChatMessageRequestMentionsItem
            dispatcher_id = os.getenv("BAND_AGENT_A_ID", "")
            mentions = []
            if self.dispatcher_handle and dispatcher_id:
                mentions.append(ChatMessageRequestMentionsItem(handle=self.dispatcher_handle, id=dispatcher_id, name="Dispatcher"))
            req = ChatMessageRequest(content=content, mentions=mentions if mentions else None)
            self.rest_client.agent_api_messages.create_agent_chat_message(self.room_id, message=req)
        except Exception as e:
            logger.warning(f"Error posting worker message to BAND: {e}")

    def _fetch_messages(self) -> list[Any]:
        if self.rest_client is None:
            return []
        try:
            resp = self.rest_client.agent_api_messages.list_agent_messages(self.room_id, limit=100)
            return resp.data or []
        except Exception as e:
            logger.warning(f"Error listing messages in room: {e}")
            return []

    async def step(self) -> list[str]:
        messages = self._fetch_messages()
        handled = []
        for msg in messages:
            msg_id = getattr(msg, "id", None)
            if not msg_id or msg_id in self.processed_msg_ids:
                continue
            content = getattr(msg, "content", "")
            is_for_worker = "agent-b" in content or (self.agent_id and self.agent_id in content)
            if "[TICKET:" in content and is_for_worker and "[Worker Report]" not in content:
                self.processed_msg_ids.add(msg_id)
                handled.append(msg_id)
                res = await self.handle_band_message(content)
                self._post_to_room(res["content"])
            else:
                self.processed_msg_ids.add(msg_id)
        return handled

    async def run_rest_loop(self, interval_s: float = 1.0) -> None:
        self.is_running = True
        existing = self._fetch_messages()
        for m in existing:
            m_id = getattr(m, "id", None)
            if m_id:
                self.processed_msg_ids.add(m_id)
        self.ready = True

        while self.is_running:
            try:
                await self.step()
            except Exception as e:
                logger.warning(f"Worker step error: {e}")
            await asyncio.sleep(interval_s)

    async def wait_ready(self, timeout_s: float = 10.0) -> None:
        deadline = time.time() + timeout_s
        while time.time() < deadline and not getattr(self, "ready", False):
            await asyncio.sleep(0.2)

    def stop(self) -> None:
        self.is_running = False

    async def handle_band_message(self, message_text: str) -> dict[str, Any]:
        """
        Parses inbound message into an Envelope or signed dict,
        executes WorkerCore, and produces the report text for the Dispatcher.
        """
        try:
            json_start = message_text.find("{")
            json_end = message_text.rfind("}")
            if json_start != -1 and json_end != -1:
                raw_data = json.loads(message_text[json_start : json_end + 1])
            else:
                raw_data = json.loads(message_text)

            if isinstance(raw_data, dict) and "ticket_id" in raw_data:
                envelope = raw_data
            else:
                envelope = Envelope(
                    ticket_id="band-ticket",
                    profile="L0",
                    text=message_text,
                    kind="benign",
                )
        except Exception:
            envelope = Envelope(
                ticket_id="band-ticket",
                profile="L0",
                text=message_text,
                kind="benign",
            )

        outcome = await self.worker_core.handle(envelope)
        report_text = "\n".join(outcome.outbound_messages) if outcome.outbound_messages else "No outbound message."

        # Format outbound message mentioning Dispatcher, NEVER mentioning self
        reply_content = f"@{self.dispatcher_handle} [Worker Report] [TICKET:{outcome.ticket_id}]: {report_text}"
        return {
            "ticket_id": outcome.ticket_id,
            "content": reply_content,
            "outcome": outcome,
        }

    async def run(self) -> None:
        """Launches live BAND listener loop."""
        logger.info(f"BandWorkerAgent starting for agent {self.agent_id}...")
        await self.run_rest_loop()


if __name__ == "__main__":
    agent = BandWorkerAgent()
    asyncio.run(agent.run())
