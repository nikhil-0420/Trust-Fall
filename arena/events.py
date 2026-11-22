"""
arena/events.py
Event logging, sequence assignment, subscriber dispatch, counters, and text-hash caching.
Owner: Nehaa (WS-C C2, C7)
"""
import asyncio
import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Union

from contracts.models import Event, EventType, RoundId


class TextCache:
    """
    On-disk text-hash cache for LLM completions and Gate decisions.
    Key is sha256(f"{purpose}:{text}").
    """

    def __init__(self, cache_dir: Union[str, Path] = "data/cache"):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _hash(self, purpose: str, text: str) -> str:
        content = f"{purpose.strip()}:{text.strip()}"
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    def get(self, purpose: str, text: str) -> Optional[Dict[str, Any]]:
        h = self._hash(purpose, text)
        cache_file = self.cache_dir / f"{h}.json"
        if cache_file.exists():
            try:
                with open(cache_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                return None
        return None

    def set(self, purpose: str, text: str, data: Dict[str, Any]) -> None:
        h = self._hash(purpose, text)
        cache_file = self.cache_dir / f"{h}.json"
        try:
            with open(cache_file, "w", encoding="utf-8") as f:
                json.dump(data, f)
        except Exception:
            pass


class EventWriter:
    """
    Appends validated Event objects to data/runs/<run_id>/events-<round>.jsonl.
    Assigns sequential numbers, dispatches to in-process subscribers (for SSE),
    and maintains call counters.
    """

    def __init__(
        self,
        run_id: str,
        base_dir: Union[str, Path] = "data/runs",
        cache_dir: Union[str, Path] = "data/cache",
    ):
        self.run_id = run_id
        self.base_dir = Path(base_dir)
        self.run_dir = self.base_dir / self.run_id
        self.run_dir.mkdir(parents=True, exist_ok=True)

        self.cache = TextCache(cache_dir)
        self.seq = 0
        self.subscribers: List[Callable[[Event], Any]] = []

        # Real and mock counters
        self.llm_calls = 0
        self.lyzr_calls = 0
        self.gate_blocks = 0
        self.cache_hits = 0

    def add_subscriber(self, callback: Callable[[Event], Any]) -> None:
        if callback not in self.subscribers:
            self.subscribers.append(callback)

    def remove_subscriber(self, callback: Callable[[Event], Any]) -> None:
        if callback in self.subscribers:
            self.subscribers.remove(callback)

    def record_llm_call(self, count: int = 1) -> None:
        self.llm_calls += count

    def record_lyzr_call(self, count: int = 1) -> None:
        self.lyzr_calls += count

    def record_gate_block(self, count: int = 1) -> None:
        self.gate_blocks += count

    def record_cache_hit(self, count: int = 1) -> None:
        self.cache_hits += count

    def emit(
        self,
        round_id: RoundId,
        event_type: EventType,
        **kwargs: Any,
    ) -> Event:
        """
        Create, validate, persist, and dispatch an Event.
        """
        self.seq += 1
        now = time.time()

        payload = {
            "t": now,
            "run_id": self.run_id,
            "round": round_id,
            "seq": self.seq,
            "type": event_type,
            **kwargs,
        }

        # Validate with contract schema
        event = Event.model_validate(payload)

        # Track counters based on event content
        if event_type == "gate" and kwargs.get("blocked"):
            self.gate_blocks += 1
        if kwargs.get("cached"):
            self.cache_hits += 1

        # Append to jsonl
        file_path = self.run_dir / f"events-{round_id}.jsonl"
        with open(file_path, "a", encoding="utf-8") as f:
            f.write(event.model_dump_json(by_alias=True) + "\n")

        # Notify in-process subscribers
        for sub in list(self.subscribers):
            try:
                res = sub(event)
                if asyncio.iscoroutine(res):
                    asyncio.create_task(res)
            except Exception:
                pass

        return event

    def get_events_for_round(self, round_id: RoundId) -> List[Dict[str, Any]]:
        file_path = self.run_dir / f"events-{round_id}.jsonl"
        if not file_path.exists():
            return []
        events = []
        with open(file_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    events.append(json.loads(line))
        return events
