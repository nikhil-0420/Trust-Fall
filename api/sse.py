"""
api/sse.py
Server-Sent Events (SSE) generator for streaming break challenge progress.
Owner: Nehaa (WS-D D5)
"""
import asyncio
import json
import time
from typing import AsyncGenerator

from api.challenge import get_challenge_manager


async def stream_attempt_events(attempt_id: str, timeout_s: float = 15.0) -> AsyncGenerator[str, None]:
    """
    Stream SSE events for a challenge attempt.
    Late subscribers receive buffered events first, then real-time updates.
    """
    mgr = get_challenge_manager()
    state = mgr.get_attempt(attempt_id)
    if not state:
        yield f"event: error\ndata: {json.dumps({'reason': 'not_found'})}\n\n"
        return

    # If attempt is already done, yield all buffered events and exit immediately
    if state.done:
        for ev in state.events:
            yield f"event: {ev['event']}\ndata: {json.dumps(ev['data'])}\n\n"
        return

    subscriber_queue: asyncio.Queue = asyncio.Queue()
    state.subscribers.append(subscriber_queue)

    # Send current buffer
    for ev in list(state.events):
        yield f"event: {ev['event']}\ndata: {json.dumps(ev['data'])}\n\n"
        if ev["event"] in ("verdict", "error"):
            return

    try:
        start_t = time.time()
        while not state.done:
            try:
                ev = await asyncio.wait_for(subscriber_queue.get(), timeout=1.0)
                yield f"event: {ev['event']}\ndata: {json.dumps(ev['data'])}\n\n"
                if ev["event"] in ("verdict", "error"):
                    break
            except asyncio.TimeoutError:
                if (time.time() - start_t) > timeout_s or state.done:
                    break
    finally:
        if subscriber_queue in state.subscribers:
            state.subscribers.remove(subscriber_queue)
