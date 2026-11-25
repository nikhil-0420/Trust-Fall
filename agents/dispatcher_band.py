"""
Owner: Nikhil (Phase N3/N7)
BandDispatcherAgent: Scripted BAND adapter for Dispatcher.
Listens to inbound tickets in a BAND room, applies pre-dispatch Gate screening,
signs envelopes with INTERNAL_TOKEN, and forwards to Worker via BAND room message.
Makes 0 LLM calls.
"""
import asyncio
import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Optional

import yaml
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

from agents.dispatcher import Dispatcher
from agents.envelope import get_or_create_internal_token, sign_envelope
from agents.sync_config import sync_band_config
from arena.factory import get_gate_client
from arena.interfaces import Envelope


class BandDispatcherAgent:
    def __init__(
        self,
        dispatcher: Optional[Dispatcher] = None,
        config_path: Optional[Path] = None,
        room_id: Optional[str] = None,
        worker_handle: Optional[str] = None,
        worker_id: Optional[str] = None,
    ):
        self.config_path = config_path or Path("agent_config.yaml")
        if not self.config_path.exists():
            sync_band_config(self.config_path)

        cfg = yaml.safe_load(self.config_path.read_text(encoding="utf-8")) or {}
        a_cfg = cfg.get("agent_a", {})
        self.agent_id = a_cfg.get("agent_id") or os.getenv("BAND_AGENT_A_ID", "")
        self.api_key = a_cfg.get("api_key") or os.getenv("BAND_AGENT_A_KEY", "")

        self.room_id = room_id or os.getenv("BAND_ROOM_ID", "0ff67f25-e8a4-42a5-a4ac-54d0c4ed727e")
        self.worker_handle = worker_handle or os.getenv("WORKER_HANDLE", "nikhil.guddanti/agent-b")
        b_cfg = cfg.get("agent_b", {})
        self.worker_id = worker_id or b_cfg.get("agent_id") or os.getenv("BAND_AGENT_B_ID", "")

        self.dispatcher = dispatcher or Dispatcher(gate=get_gate_client())
        self.internal_token = os.getenv("INTERNAL_TOKEN") or get_or_create_internal_token()

        self.rest_client = None
        if self.api_key:
            try:
                from band_rest import RestClient
                self.rest_client = RestClient(api_key=self.api_key)
            except ImportError:
                self.rest_client = None

        self.processed_msg_ids: set[str] = set()
        self.is_running = False

    def _post_to_room(self, content: str, mentions: list[Any] | None = None) -> None:
        if self.rest_client is None:
            return
        try:
            from band_rest.types import ChatMessageRequest, ChatMessageRequestMentionsItem
            if not mentions:
                mentions = [{"handle": self.worker_handle, "id": self.worker_id, "name": "Worker"}]
            mention_items = []
            for m in mentions:
                mention_items.append(ChatMessageRequestMentionsItem(**m))
            req = ChatMessageRequest(content=content, mentions=mention_items)
            self.rest_client.agent_api_messages.create_agent_chat_message(self.room_id, message=req)
        except Exception as e:
            logger.warning(f"Error posting dispatcher message to BAND: {e}")

    def _fetch_messages(self, max_pages: int = 1) -> list[Any]:
        if self.rest_client is None:
            return []
        messages: list[Any] = []
        cursor: Optional[str] = None
        pages = 0
        while pages < max_pages:
            try:
                if cursor:
                    resp = self.rest_client.agent_api_messages.list_agent_messages(
                        self.room_id, limit=100, cursor=cursor, sort_order="desc"
                    )
                else:
                    resp = self.rest_client.agent_api_messages.list_agent_messages(
                        self.room_id, limit=100, sort_order="desc"
                    )
                batch = resp.data or []
                messages.extend(batch)
                pages += 1
                if not resp.metadata or not resp.metadata.has_more or not batch:
                    break
                cursor = resp.metadata.next_cursor
            except Exception as e:
                logger.warning(f"Error listing messages in room: {e}")
                break
        return messages

    async def step(self) -> list[str]:
        """Polls for new tickets and forwards them to worker or blocks them."""
        messages = self._fetch_messages()
        handled = []
        for msg in messages:
            msg_id = getattr(msg, "id", None)
            if not msg_id or msg_id in self.processed_msg_ids:
                continue
            content = getattr(msg, "content", "")
            # Only process messages intended for Dispatcher containing [TICKET:
            is_for_dispatcher = "agent-a" in content or (self.agent_id and self.agent_id in content)
            if "[TICKET:" in content and is_for_dispatcher and "[Worker Report]" not in content:
                logger.info(f"[TIMELINE] Dispatcher message received: msg_id={msg_id} at {time.time():.4f}")
                self.processed_msg_ids.add(msg_id)
                handled.append(msg_id)
                await self._process_ticket_message(content)
            else:
                self.processed_msg_ids.add(msg_id)
        return handled

    async def _process_ticket_message(self, content: str) -> None:
        # Extract JSON envelope
        json_start = content.find("{")
        json_end = content.rfind("}")
        if json_start == -1 or json_end == -1:
            return

        try:
            raw_data = json.loads(content[json_start : json_end + 1])
            env = Envelope(**raw_data)
        except Exception as e:
            logger.warning(f"Failed to parse ticket envelope: {e}")
            return

        # Check gate at L1/L2
        if env.profile in ("L1", "L2") and self.dispatcher.gate is not None:
            logger.info(f"[TIMELINE] Dispatcher gate start ticket={env.ticket_id} at {time.time():.4f}")
            gate_res = await self.dispatcher.gate.screen(env.text, stage="pre_dispatch")
            logger.info(f"[TIMELINE] Dispatcher gate end ticket={env.ticket_id} at {time.time():.4f}")
            if gate_res.blocked or gate_res.decision in ("INJECTION", "ERROR"):
                reply = f"[Worker Report] [TICKET:{env.ticket_id}]: BLOCKED BY GATE - {gate_res.decision}"
                red_id = os.getenv("BAND_AGENT_RED_ID", "")
                mentions = []
                if red_id:
                    mentions.append({"handle": "nikhil.guddanti/red-agent", "id": red_id, "name": "Red Agent"})
                # Never mention self (Dispatcher / agent-a) to avoid BAND 422 cannot_mention_self
                self._post_to_room(reply, mentions=mentions if mentions else None)
                return

        # Sign envelope and forward to Worker
        signed_dict = sign_envelope(env, self.internal_token)
        payload_str = json.dumps(signed_dict)
        forward_msg = f"@{self.worker_handle} [TICKET:{env.ticket_id}] {payload_str}"
        mentions = [
            {"handle": self.worker_handle, "id": self.worker_id, "name": "Worker"}
        ]
        self._post_to_room(forward_msg, mentions=mentions)
        logger.info(f"[TIMELINE] Dispatcher forward posted ticket={env.ticket_id} at {time.time():.4f}")

    async def run(self, interval_s: float = 1.0) -> None:
        self.is_running = True
        # Pre-seed existing messages so we do not reprocess old history
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
                logger.warning(f"Dispatcher step error: {e}")
            await asyncio.sleep(interval_s)

    async def wait_ready(self, timeout_s: float = 10.0) -> None:
        deadline = time.time() + timeout_s
        while time.time() < deadline and not getattr(self, "ready", False):
            await asyncio.sleep(0.2)

    def stop(self) -> None:
        self.is_running = False
