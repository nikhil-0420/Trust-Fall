"""
agents/blue_band.py
BAND-native Blue defender agent and client adapter.
Enables Referee to request defender patches across BAND agent rooms with request-ID tracking,
3KB payload truncation, and automatic fallback to ScriptedBlue on timeout (>90s) or failure.
"""
import asyncio
import json
import logging
import os
import re
import secrets
import time
from pathlib import Path
from typing import Any, List, Optional

from agents.blue import DEFAULT_SAFE_PATCH, LLMBlue, ScriptedBlue
from arena.interfaces import BlueAgent
from contracts.patch_validate import validate_patch

logger = logging.getLogger(__name__)


def summarize_incident_log_for_band(
    incident_log: list[dict[str, Any]],
    previous_patch: dict[str, Any] | None = None,
    rejected_reason: str | None = None,
    max_bytes: int = 2800,
) -> str:
    """
    Summarizes incidents for BAND transmission:
    - Strictly <= 3 KB (max_bytes <= 2800)
    - Includes category, goal, outcome, layer
    - Names secret format ('CANARY-[0-9a-f]{6}-DEMO-ONLY')
    - NEVER includes raw secret values or held-out attack markers
    """
    safe_incidents = []
    for inc in incident_log:
        if inc.get("heldout") or inc.get("known") is False:
            continue
        safe_incidents.append({
            "id": inc.get("attack_id") or inc.get("id"),
            "category": inc.get("category"),
            "goal": inc.get("goal"),
            "layer": inc.get("layer"),
            "outcome": inc.get("outcome"),
        })

    summary_data = {
        "secret_format": "CANARY-[0-9a-f]{6}-DEMO-ONLY",
        "incidents": safe_incidents,
        "rejected_reason": rejected_reason,
        "previous_version": previous_patch.get("version") if previous_patch else 0,
    }

    dumped = json.dumps(summary_data)
    if len(dumped.encode("utf-8")) > max_bytes:
        summary_data["incidents"] = safe_incidents[:10]
        dumped = json.dumps(summary_data)

    return dumped


class BandBlueClient(BlueAgent):
    """
    Client adapter used by Referee when BLUE_TRANSPORT=band.
    Posts [DEFENSE_REQUEST:req-...] to BAND room, awaits [PATCH_PROPOSAL:req-...],
    and falls back to ScriptedBlue after 90s timeout or invalid JSON.
    """

    def __init__(
        self,
        room_id: Optional[str] = None,
        blue_handle: Optional[str] = None,
        blue_id: Optional[str] = None,
        rest_client: Optional[Any] = None,
        timeout_s: float = 90.0,
    ):
        self.room_id = room_id or os.getenv("BAND_ROOM_ID", "0ff67f25-e8a4-42a5-a4ac-54d0c4ed727e")
        self.blue_handle = blue_handle or os.getenv("BLUE_HANDLE", "nikhil.guddanti/agent-blue")
        self.blue_id = blue_id or os.getenv("BAND_AGENT_BLUE_ID", "")
        self.sender_key = os.getenv("BAND_AGENT_A_KEY")
        self.rest_client = rest_client
        self.timeout_s = timeout_s

        if self.rest_client is None and self.sender_key:
            try:
                from band_rest import RestClient
                self.rest_client = RestClient(api_key=self.sender_key)
            except ImportError:
                self.rest_client = None

    def _post_message(self, content: str) -> None:
        if self.rest_client is None:
            return
        try:
            from band_rest.types import ChatMessageRequest, ChatMessageRequestMentionsItem

            mentions = []
            if self.blue_handle and self.blue_id:
                mentions.append(
                    ChatMessageRequestMentionsItem(
                        handle=self.blue_handle,
                        id=self.blue_id,
                        name="Blue Defender",
                    )
                )
            msg = ChatMessageRequest(content=content, mentions=mentions)
            self.rest_client.agent_api_messages.create_agent_chat_message(self.room_id, message=msg)
        except Exception as e:
            logger.warning(f"Error posting Blue defense request to BAND: {e}")

    def _fetch_messages(self) -> List[Any]:
        if self.rest_client is None:
            return []
        try:
            resp = self.rest_client.agent_api_messages.list_agent_messages(
                self.room_id, limit=50, sort_order="desc"
            )
            return resp.data or []
        except Exception as e:
            logger.warning(f"Error listing messages for Blue response: {e}")
            return []

    async def propose_patch(
        self,
        incident_log: list[dict[str, Any]],
        previous_patch: dict[str, Any] | None = None,
        rejected_reason: str | None = None,
    ) -> dict[str, Any]:
        req_id = f"req-{secrets.token_hex(4)}"
        summary_payload = summarize_incident_log_for_band(
            incident_log, previous_patch=previous_patch, rejected_reason=rejected_reason
        )

        post_content = f"@{self.blue_handle} [DEFENSE_REQUEST:{req_id}] {summary_payload}"

        existing_msgs = self._fetch_messages()
        seen_ids = {getattr(m, "id", None) for m in existing_msgs if getattr(m, "id", None)}

        self._post_message(post_content)
        logger.info(f"Posted Blue defense request {req_id} to room {self.room_id}")

        deadline = time.time() + self.timeout_s
        matched_proposal_json = None

        while time.time() < deadline:
            messages = self._fetch_messages()
            for m in messages:
                m_id = getattr(m, "id", None)
                if m_id in seen_ids:
                    continue
                content = getattr(m, "content", "")
                if f"[PATCH_PROPOSAL:{req_id}]" in content and "PATCH_JSON:" in content:
                    raw_json = content.split("PATCH_JSON:", 1)[1].strip()
                    matched_proposal_json = raw_json
                    break
            if matched_proposal_json:
                break
            await asyncio.sleep(1.0)

        if matched_proposal_json:
            try:
                patch_dict = json.loads(matched_proposal_json)
                ok, errors, _ = validate_patch(patch_dict)
                if ok:
                    logger.info(f"Received valid BAND Blue proposal for {req_id}")
                    return patch_dict
                logger.warning(f"BAND Blue patch failed validation: {errors}")
            except Exception as e:
                logger.warning(f"Failed to parse BAND Blue proposal: {e}")

        logger.warning(f"BAND Blue proposal timed out or failed. Falling back to ScriptedBlue.")
        return await ScriptedBlue().propose_patch(incident_log, previous_patch, rejected_reason)


class BandBlueAgent:
    """
    Standalone background listener agent that monitors BAND room for [DEFENSE_REQUEST:req-...],
    invokes LLMBlue to synthesize patch, and posts [PATCH_PROPOSAL:req-...] PATCH_JSON: <json>.
    """

    def __init__(
        self,
        room_id: Optional[str] = None,
        blue_agent: Optional[BlueAgent] = None,
        rest_client: Optional[Any] = None,
    ):
        self.room_id = room_id or os.getenv("BAND_ROOM_ID", "0ff67f25-e8a4-42a5-a4ac-54d0c4ed727e")
        self.blue_agent = blue_agent or LLMBlue()
        self.blue_key = os.getenv("BAND_AGENT_BLUE_KEY")
        self.blue_id = os.getenv("BAND_AGENT_BLUE_ID", "")
        self.blue_handle = os.getenv("BLUE_HANDLE", "nikhil.guddanti/agent-blue")
        self.rest_client = rest_client
        self.is_running = False
        self.processed_ids: set[str] = set()

        if self.rest_client is None and self.blue_key:
            try:
                from band_rest import RestClient
                self.rest_client = RestClient(api_key=self.blue_key)
            except ImportError:
                self.rest_client = None

    def _fetch_messages(self) -> List[Any]:
        if self.rest_client is None:
            return []
        try:
            resp = self.rest_client.agent_api_messages.list_agent_messages(
                self.room_id, limit=50, sort_order="desc"
            )
            return resp.data or []
        except Exception:
            return []

    def _post_proposal(self, content: str) -> None:
        if self.rest_client is None:
            return
        try:
            from band_rest.types import ChatMessageRequest
            msg = ChatMessageRequest(content=content, mentions=[])
            self.rest_client.agent_api_messages.create_agent_chat_message(self.room_id, message=msg)
        except Exception as e:
            logger.warning(f"Error posting Blue patch proposal: {e}")

    async def handle_message(self, message: Any) -> bool:
        content = getattr(message, "content", "")
        if "[DEFENSE_REQUEST:" in content:
            await self._handle_request(content)
            return True
        return False

    async def step(self) -> list[str]:
        messages = self._fetch_messages()
        handled = []
        for m in messages:
            m_id = getattr(m, "id", None)
            if not m_id or m_id in self.processed_ids:
                continue
            content = getattr(m, "content", "")
            if "[DEFENSE_REQUEST:" in content and "agent-blue" in content.lower():
                self.processed_ids.add(m_id)
                handled.append(m_id)
                await self._handle_request(content)
            else:
                self.processed_ids.add(m_id)
        return handled

    async def _handle_request(self, content: str) -> None:
        match = re.search(r"\[DEFENSE_REQUEST:(req-[0-9a-fA-F]+)\]\s*(\{.*\})", content, re.DOTALL)
        if not match:
            return
        req_id = match.group(1)
        raw_json = match.group(2)
        try:
            payload = json.loads(raw_json)
            incidents = payload.get("incidents", [])
            prev_version = payload.get("previous_version", 0)
            rejected_reason = payload.get("rejected_reason")
            prev_patch = {"version": prev_version} if prev_version else None

            patch = await self.blue_agent.propose_patch(
                incidents, previous_patch=prev_patch, rejected_reason=rejected_reason
            )
            reply = f"[PATCH_PROPOSAL:{req_id}] PATCH_JSON: {json.dumps(patch)}"
            self._post_proposal(reply)
            logger.info(f"Handled defense request {req_id} and posted proposal.")
        except Exception as e:
            logger.warning(f"Error processing defense request {req_id}: {e}")

    async def run(self, interval_s: float = 1.0) -> None:
        self.is_running = True
        existing = self._fetch_messages()
        for m in existing:
            m_id = getattr(m, "id", None)
            if m_id:
                self.processed_ids.add(m_id)

        while self.is_running:
            try:
                await self.step()
            except Exception as e:
                logger.warning(f"Blue agent loop error: {e}")
            await asyncio.sleep(interval_s)

    def stop(self) -> None:
        self.is_running = False
