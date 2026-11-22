"""
Owner: Nikhil (Phase N3)
BandTransport implementing Transport.
Communicates via BAND rooms using RestClient and agent messaging.
"""
import asyncio
import json
import logging
import os
import time
from typing import Any, Dict, List, Optional

from arena.factory import get_sandbox
from arena.interfaces import Envelope, Sandbox, Transport, WorkerOutcome

logger = logging.getLogger(__name__)


class BandTransport(Transport):
    def __init__(
        self,
        room_id: Optional[str] = None,
        sandbox: Optional[Sandbox] = None,
        dispatcher_handle: Optional[str] = None,
        rest_client: Optional[Any] = None,
    ):
        self.room_id = room_id or os.getenv("BAND_ROOM_ID", "2259e40a-1833-49f4-b647-596ac09f99ea")
        self.sandbox = sandbox or get_sandbox()
        self.dispatcher_handle = dispatcher_handle or os.getenv("DISPATCHER_HANDLE", "nikhil.guddanti/agent-a")
        self.dispatcher_id = os.getenv("BAND_AGENT_A_ID", "")

        self.sender_key = os.getenv("BAND_AGENT_RED_KEY") or os.getenv("BAND_AGENT_A_KEY")
        self.reader_key = os.getenv("BAND_AGENT_A_KEY") or self.sender_key
        self.rest_client = rest_client
        self.reader_client = None

        if self.rest_client is None and self.sender_key:
            try:
                from band_rest import RestClient
                self.rest_client = RestClient(api_key=self.sender_key)
                self.reader_client = RestClient(api_key=self.reader_key)
            except ImportError:
                self.rest_client = None
                self.reader_client = None

    def _post_message(self, content: str) -> None:
        if self.rest_client is None:
            return

        try:
            from band_rest.types import ChatMessageRequest, ChatMessageRequestMentionsItem

            mentions = []
            if self.dispatcher_handle and self.dispatcher_id:
                mentions.append(
                    ChatMessageRequestMentionsItem(
                        handle=self.dispatcher_handle,
                        id=self.dispatcher_id,
                        name="Dispatcher",
                    )
                )

            msg = ChatMessageRequest(content=content, mentions=mentions if mentions else None)
            self.rest_client.agent_api_messages.create_agent_chat_message(self.room_id, message=msg)
        except Exception as e:
            logger.warning(f"Error posting message to BAND room {self.room_id}: {e}")

    def _fetch_room_messages(self) -> List[Any]:
        client = self.reader_client or self.rest_client
        if client is None:
            return []

        try:
            resp = client.agent_api_messages.list_agent_messages(self.room_id, limit=100)
            return resp.data or []
        except Exception as e:
            logger.warning(f"Error listing messages from BAND room: {e}")
            return []

    async def send_ticket(self, env: Envelope, timeout_s: float = 45.0) -> WorkerOutcome:
        start_time = time.perf_counter()

        # Format ticket content mentioning Dispatcher
        payload_text = json.dumps(env.model_dump())
        post_content = f"@{self.dispatcher_handle} [TICKET:{env.ticket_id}] {payload_text}"

        self._post_message(post_content)

        # Poll room messages every 1 second until timeout
        deadline = time.time() + timeout_s
        matched_report = None

        while time.time() < deadline:
            messages = self._fetch_room_messages()
            for m in messages:
                content = getattr(m, "content", "")
                if env.ticket_id in content and ("[Worker Report]" in content or "Report" in content):
                    matched_report = content
                    break
            if matched_report:
                break
            await asyncio.sleep(1.0)

        latency_ms = int((time.perf_counter() - start_time) * 1000)

        if not matched_report:
            return WorkerOutcome(
                ticket_id=env.ticket_id,
                outbound_messages=[],
                blocked_by_gate=False,
                latency_ms=latency_ms,
                llm_calls=0,
                error="timeout",
            )

        # Read sandbox state
        memory_after = None
        refund_after = None
        if self.sandbox is not None:
            try:
                memory_after = await self.sandbox.read_memory()
            except Exception:
                pass
            try:
                refund_after = await self.sandbox.read_refund_ledger()
            except Exception:
                pass

        return WorkerOutcome(
            ticket_id=env.ticket_id,
            outbound_messages=[matched_report],
            blocked_by_gate=False,
            memory_after=memory_after,
            refund_ledger_after=refund_after,
            latency_ms=latency_ms,
            llm_calls=1,
            error=None,
        )
