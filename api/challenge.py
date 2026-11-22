"""
api/challenge.py
Challenge mode execution engine, single-worker queue, SSE event buffering,
presets, and SQLite leaderboard.
Owner: Nehaa (WS-D D5, D6, D8)
"""
import asyncio
import html
import json
import os
import re
import secrets
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from api.budget import get_budget
from api.limits import get_rate_limiter
from arena.factory import get_gate, get_sandbox, get_transport
from arena.interfaces import Envelope, WorkerOutcome
from arena.judge import judge

DB_PATH = Path("data/leaderboard.db")


# ------------------------------------------------------------------------------
# Leaderboard Database Initialization & Helpers
# ------------------------------------------------------------------------------
def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS leaderboard (
                id TEXT PRIMARY KEY,
                nickname TEXT,
                level TEXT,
                goal TEXT,
                created_at TEXT,
                attack_text TEXT
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS stats (
                level TEXT PRIMARY KEY,
                attempts INTEGER DEFAULT 0,
                breaks INTEGER DEFAULT 0
            )
            """
        )
        for lvl in ("L0", "L1", "L2"):
            cursor.execute(
                "INSERT OR IGNORE INTO stats (level, attempts, breaks) VALUES (?, 0, 0)",
                (lvl,),
            )
        conn.commit()


def record_attempt_stats(level: str, succeeded: bool):
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE stats SET attempts = attempts + 1 WHERE level = ?",
                (level,),
            )
            if succeeded:
                cursor.execute(
                    "UPDATE stats SET breaks = breaks + 1 WHERE level = ?",
                    (level,),
                )
            conn.commit()
    except Exception:
        pass


def add_leaderboard_entry(
    attempt_id: str,
    nickname: str,
    level: str,
    goal: str,
    attack_text: str,
):
    try:
        now_iso = datetime.now(timezone.utc).isoformat()
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT OR REPLACE INTO leaderboard (id, nickname, level, goal, created_at, attack_text)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (attempt_id, nickname, level, goal, now_iso, attack_text),
            )
            conn.commit()
    except Exception:
        pass


def get_leaderboard_data() -> Dict[str, Any]:
    init_db()
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT level, attempts, breaks FROM stats")
            rows = cursor.fetchall()

            total_attempts = sum(r[1] for r in rows)
            total_breaks = sum(r[2] for r in rows)
            break_rate = (
                round(total_breaks / total_attempts, 3) if total_attempts > 0 else 0.0
            )

            by_level = {
                r[0]: {
                    "attempts": r[1],
                    "breaks": r[2],
                    "break_rate": round(r[2] / r[1], 3) if r[1] > 0 else 0.0,
                }
                for r in rows
            }

            cursor.execute(
                "SELECT id, nickname, level, goal, created_at, attack_text FROM leaderboard ORDER BY created_at DESC LIMIT 50"
            )
            entry_rows = cursor.fetchall()
            entries = []
            for er in entry_rows:
                raw_text = er[5] or ""
                # Strip control characters and cap at 200 chars
                sanitized = re.sub(r"[\x00-\x1f\x7f-\x9f]", "", raw_text)[:200]
                text_preview = html.escape(sanitized)
                entries.append(
                    {
                        "id": er[0],
                        "nickname": html.escape(er[1] or "anonymous"),
                        "level": er[2],
                        "goal": er[3],
                        "created_at": er[4],
                        "text_preview": text_preview,
                    }
                )

            return {
                "counters": {
                    "attempts": total_attempts,
                    "breaks": total_breaks,
                    "break_rate": break_rate,
                    "by_level": by_level,
                },
                "entries": entries,
            }
    except Exception:
        return {
            "counters": {"attempts": 0, "breaks": 0, "break_rate": 0.0, "by_level": {}},
            "entries": [],
        }


def delete_leaderboard_entry(entry_id: str) -> bool:
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM leaderboard WHERE id = ?", (entry_id,))
            conn.commit()
            return cursor.rowcount > 0
    except Exception:
        return False


# ------------------------------------------------------------------------------
# Presets Helper
# ------------------------------------------------------------------------------
def load_presets() -> List[Dict[str, Any]]:
    lib_path = Path("attacks/library.json")
    if not lib_path.exists():
        return []

    with open(lib_path, "r", encoding="utf-8") as f:
        raw_lib = json.load(f)

    # Load outcomes from results.json
    results_file = Path("data/results.json")
    if not results_file.exists():
        results_file = Path("data/mock/results.json")

    outcomes_map = {}
    if results_file.exists():
        try:
            with open(results_file, "r", encoding="utf-8") as f:
                res_data = json.load(f)
            for rnd in res_data.get("rounds", []):
                lvl = "L0" if rnd["id"] == "R0" else ("L1" if rnd["id"] == "R1" else "L2")
                for att in rnd.get("attacks", []):
                    if att["id"] not in outcomes_map:
                        outcomes_map[att["id"]] = {}
                    outcomes_map[att["id"]][lvl] = att["outcome"]
        except Exception:
            pass

    presets = []
    preset_idx = 1
    for att in raw_lib:
        if not att.get("known", True):
            continue  # NEVER expose held-out attack texts

        att_id = att["id"]
        cached = outcomes_map.get(att_id, {})
        preset_entry = {
            "id": f"preset-{preset_idx}",
            "title": att["title"],
            "category": att["category"],
            "owasp": att.get("owasp", "LLM01"),
            "goal": att["goal"],
            "text": att["text"],
            "outcomes": {
                "L0": cached.get("L0", "succeeded"),
                "L1": cached.get("L1", "blocked_by_gate" if att["category"] in ("direct", "roleplay", "authority") else "succeeded"),
                "L2": cached.get("L2", "resisted"),
            },
        }
        presets.append(preset_entry)
        preset_idx += 1

    return presets


# ------------------------------------------------------------------------------
# Challenge Attempt State & Queue Management
# ------------------------------------------------------------------------------
class AttemptState:
    def __init__(self, attempt_id: str, req_data: Dict[str, Any]):
        self.attempt_id = attempt_id
        self.req_data = req_data
        self.events: List[Dict[str, Any]] = []
        self.verdict: Optional[Dict[str, Any]] = None
        self.created_at = time.time()
        self.subscribers: List[asyncio.Queue] = []
        self.done = False

    def emit_event(self, event_type: str, data: Dict[str, Any]):
        payload = {"event": event_type, "data": data}
        self.events.append(payload)
        for q in list(self.subscribers):
            try:
                q.put_nowait(payload)
            except Exception:
                pass

    def set_verdict(self, verdict: Dict[str, Any]):
        self.verdict = verdict
        self.emit_event("verdict", verdict)
        self.done = True

    def set_error(self, reason: str):
        err = {"reason": reason}
        self.emit_event("error", err)
        self.done = True


class ChallengeManager:
    """
    Manages single-worker queue, active attempts, and SSE subscriber feeds.
    """

    def __init__(self):
        self.queue: asyncio.Queue = asyncio.Queue(maxsize=10)
        self.attempts: Dict[str, AttemptState] = {}
        self._worker_running = False

    def get_queue_depth(self) -> int:
        return self.queue.qsize()

    def get_attempt(self, attempt_id: str) -> Optional[AttemptState]:
        self._prune_old_attempts()
        return self.attempts.get(attempt_id)

    def _prune_old_attempts(self):
        now = time.time()
        expired = [
            k for k, v in self.attempts.items() if (now - v.created_at) > 3600
        ]
        for k in expired:
            self.attempts.pop(k, None)

    async def enqueue_attempt(self, req_data: Dict[str, Any]) -> str:
        if self.queue.qsize() >= 10:
            raise ValueError("queue_full")

        attempt_id = f"att-{secrets.token_hex(6)}"
        state = AttemptState(attempt_id, req_data)
        self.attempts[attempt_id] = state

        try:
            self.queue.put_nowait(state)
        except asyncio.QueueFull:
            self.attempts.pop(attempt_id, None)
            raise ValueError("queue_full")

        if not self._worker_running:
            asyncio.create_task(self._process_queue())

        return attempt_id

    async def _process_queue(self):
        if self._worker_running:
            return
        self._worker_running = True
        try:
            while not self.queue.empty():
                state = await self.queue.get()
                try:
                    await self._process_attempt(state)
                except Exception:
                    state.set_error(reason="worker_down")
                finally:
                    self.queue.task_done()
        finally:
            self._worker_running = False

    async def _process_attempt(self, state: AttemptState):
        req = state.req_data
        level = req["level"]
        goal = req["goal"]
        text = req["text"]
        preset_id = req.get("preset_id")
        share = bool(req.get("share", False))
        nickname = req.get("nickname") or "anonymous"

        # 1. Preset replay path (0 live calls)
        if preset_id:
            presets = load_presets()
            matching_preset = next((p for p in presets if p["id"] == preset_id), None)
            if matching_preset and level in matching_preset["outcomes"]:
                outcome = matching_preset["outcomes"][level]
                stopped_by = (
                    "gate"
                    if outcome == "blocked_by_gate"
                    else ("patch" if level == "L2" and outcome == "resisted" else ("worker" if outcome == "resisted" else "none"))
                )

                # Synthetic step progression
                state.emit_event("step", {"name": "gate", "status": "running", "ms": 50})
                await asyncio.sleep(0.05)
                state.emit_event(
                    "step",
                    {
                        "name": "gate",
                        "status": "blocked" if stopped_by == "gate" else "done",
                        "ms": 120,
                    },
                )

                if stopped_by != "gate":
                    state.emit_event("step", {"name": "dispatcher", "status": "running", "ms": 50})
                    await asyncio.sleep(0.05)
                    state.emit_event("step", {"name": "dispatcher", "status": "done", "ms": 90})

                    state.emit_event("step", {"name": "worker", "status": "running", "ms": 150})
                    await asyncio.sleep(0.1)
                    state.emit_event(
                        "step",
                        {
                            "name": "worker",
                            "status": "blocked" if stopped_by in ("patch", "worker") else "done",
                            "ms": 350,
                        },
                    )

                state.emit_event("step", {"name": "referee", "status": "done", "ms": 50})

                verdict = {
                    "outcome": outcome,
                    "stopped_by": stopped_by,
                    "goal": goal,
                    "gate": {
                        "decision": "INJECTION" if stopped_by == "gate" else "SAFE",
                        "confidence": 0.98 if stopped_by == "gate" else 0.04,
                    },
                    "latency_ms": 610,
                }
                state.set_verdict(verdict)
                record_attempt_stats(level, outcome == "succeeded")
                if share and outcome == "succeeded":
                    add_leaderboard_entry(state.attempt_id, nickname, level, goal, text)
                return

        # 2. Live challenge execution path
        sandbox = get_sandbox()
        transport = get_transport()
        gate = get_gate()

        # Wire in-memory mock instances together
        if hasattr(transport, "sandbox"):
            transport.sandbox = sandbox
        if hasattr(transport, "gate"):
            transport.gate = gate

        # Check worker health
        try:
            is_alive = await sandbox.ping()
            if not is_alive:
                state.set_error(reason="worker_down")
                return
        except Exception:
            state.set_error(reason="worker_down")
            return

        # Fresh canary & clean sandbox state
        canary = f"CANARY-{secrets.token_hex(3)}-DEMO-ONLY"
        await sandbox.reset_state(canary)

        # Step: Gate screening
        start_t = time.perf_counter()
        gate_ms = 0
        gate_res = None
        if level != "L0":
            state.emit_event("step", {"name": "gate", "status": "running", "ms": 0})
            t0 = time.perf_counter()
            gate_res = await gate.screen(text, stage="inbound")
            gate_ms = int((time.perf_counter() - t0) * 1000)
            if gate_res.blocked:
                state.emit_event("step", {"name": "gate", "status": "blocked", "ms": gate_ms})
            else:
                state.emit_event("step", {"name": "gate", "status": "done", "ms": gate_ms})

        if gate_res and gate_res.blocked:
            latency = int((time.perf_counter() - start_t) * 1000)
            verdict = {
                "outcome": "blocked_by_gate",
                "stopped_by": "gate",
                "goal": goal,
                "gate": {
                    "decision": gate_res.decision,
                    "confidence": gate_res.confidence,
                },
                "latency_ms": latency,
            }
            state.set_verdict(verdict)
            record_attempt_stats(level, False)
            return

        # Step: Dispatcher forward
        state.emit_event("step", {"name": "dispatcher", "status": "running", "ms": 0})
        await asyncio.sleep(0.02)
        state.emit_event("step", {"name": "dispatcher", "status": "done", "ms": 40})

        # Step: Worker execution
        state.emit_event("step", {"name": "worker", "status": "running", "ms": 0})
        env = Envelope(
            ticket_id=f"T-CH-{state.attempt_id}",
            attempt_id=state.attempt_id,
            profile=level,
            text=text,
            kind="challenge",
            attack_id=None,
        )

        try:
            outcome = await asyncio.wait_for(transport.send_ticket(env, timeout_s=45.0), timeout=45.0)
        except asyncio.TimeoutError:
            state.set_error(reason="timeout")
            return
        except Exception:
            state.set_error(reason="worker_down")
            return

        state.emit_event(
            "step",
            {
                "name": "worker",
                "status": "blocked" if (outcome.blocked_by_gate or (level == "L2" and not outcome.outbound_messages)) else "done",
                "ms": outcome.latency_ms,
            },
        )

        # Step: Referee evaluation
        state.emit_event("step", {"name": "referee", "status": "running", "ms": 0})
        judge_res = judge(goal, canary, outcome)
        state.emit_event("step", {"name": "referee", "status": "done", "ms": 30})

        # stopped_by attribution logic
        if judge_res.outcome == "blocked_by_gate":
            stopped_by = "gate"
        elif judge_res.outcome == "resisted":
            stopped_by = "patch" if level == "L2" else "worker"
        else:
            stopped_by = "none"

        total_latency = int((time.perf_counter() - start_t) * 1000)
        verdict = {
            "outcome": judge_res.outcome,
            "stopped_by": stopped_by,
            "goal": goal,
            "gate": {
                "decision": outcome.gate.decision if outcome.gate else ("SAFE" if level == "L0" else "SAFE"),
                "confidence": outcome.gate.confidence if outcome.gate else 0.05,
            },
            "latency_ms": total_latency,
        }
        state.set_verdict(verdict)
        record_attempt_stats(level, judge_res.outcome == "succeeded")

        if share and judge_res.outcome == "succeeded":
            add_leaderboard_entry(state.attempt_id, nickname, level, goal, text)


_challenge_manager: Optional[ChallengeManager] = None


def get_challenge_manager() -> ChallengeManager:
    global _challenge_manager
    if _challenge_manager is None:
        _challenge_manager = ChallengeManager()
    return _challenge_manager
