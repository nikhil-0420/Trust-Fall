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
        self.room_id = room_id or os.getenv("BAND_ROOM_ID", "0ff67f25-e8a4-42a5-a4ac-54d0c4ed727e")
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

            msg = ChatMessageRequest(content=content, mentions=mentions)
            self.rest_client.agent_api_messages.create_agent_chat_message(self.room_id, message=msg)
        except Exception as e:
            logger.warning(f"Error posting message to BAND room {self.room_id}: {e}")

    def _fetch_room_messages(self, max_pages: int = 1) -> List[Any]:
        client = self.reader_client or self.rest_client
        if client is None:
            return []

        messages: List[Any] = []
        cursor: Optional[str] = None
        pages = 0

        while pages < max_pages:
            try:
                if cursor:
                    resp = client.agent_api_messages.list_agent_messages(
                        self.room_id, limit=100, cursor=cursor, sort_order="desc"
                    )
                else:
                    resp = client.agent_api_messages.list_agent_messages(
                        self.room_id, limit=100, sort_order="desc"
                    )
                batch = resp.data or []
                messages.extend(batch)
                pages += 1
                if not resp.metadata or not resp.metadata.has_more or not batch:
                    break
                cursor = resp.metadata.next_cursor
            except Exception as e:
                logger.warning(f"Error listing messages from BAND room: {e}")
                break

        return messages

    async def send_ticket(self, env: Envelope, timeout_s: float = 60.0) -> WorkerOutcome:
        env_timeout = os.getenv("TICKET_TIMEOUT_S")
        if env_timeout:
            try:
                timeout_s = float(env_timeout)
            except ValueError:
                pass

        # Multi-step tickets get 90s timeout
        if getattr(env, "is_multistep", False) or "multi" in getattr(env, "ticket_id", "").lower():
            timeout_s = max(timeout_s, 90.0)

        start_time = time.perf_counter()
        matched_report = None

        # 1 retry on timeout (2 attempts total)
        for attempt in range(2):
            # Snapshot existing message IDs before sending so we never match stale history
            existing_msgs = self._fetch_room_messages()
            seen_ids = {getattr(m, "id", None) for m in existing_msgs if getattr(m, "id", None)}

            # Format ticket content mentioning Dispatcher
            payload_text = json.dumps(env.model_dump())
            post_content = f"@{self.dispatcher_handle} [TICKET:{env.ticket_id}] {payload_text}"

            self._post_message(post_content)

            # Poll room messages until deadline
            deadline = time.time() + timeout_s

            while time.time() < deadline:
                messages = self._fetch_room_messages()
                for m in messages:
                    m_id = getattr(m, "id", None)
                    if m_id in seen_ids:
                        continue
                    content = getattr(m, "content", "")
                    if env.ticket_id in content and ("[Worker Report]" in content or "Report" in content):
                        matched_report = content
                        break
                if matched_report:
                    break
                poll_interval = float(os.getenv("BAND_POLL_INTERVAL_S", "0.2"))
                await asyncio.sleep(poll_interval)

            if matched_report:
                break
            if attempt == 0:
                logger.warning(f"BandTransport: ticket {env.ticket_id} timed out after {timeout_s}s, retrying once...")
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
                path="band+agent37",
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

        is_gate_blocked = "BLOCKED BY GATE" in matched_report
        gate_res = None
        if is_gate_blocked:
            from arena.interfaces import GateResult
            gate_res = GateResult(decision="INJECTION", confidence=0.96, blocked=True)

        redactions = matched_report.count("[REDACTED]") if matched_report else 0
        controls = {
            "gate_blocked": is_gate_blocked,
            "redactions": redactions,
            "memory_denials": 0,
            "memory_notes_blocked": 0,
        }
        decided_by = "gate" if is_gate_blocked else ("redaction" if redactions > 0 else "none")

        await asyncio.sleep(1.0)
        return WorkerOutcome(
            ticket_id=env.ticket_id,
            outbound_messages=[matched_report],
            blocked_by_gate=is_gate_blocked,
            gate=gate_res,
            memory_after=memory_after,
            refund_ledger_after=refund_after,
            latency_ms=latency_ms,
            llm_calls=0 if is_gate_blocked else 1,
            error=None,
            controls=controls,
            decided_by=decided_by,
            path="band+agent37",
        )
