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
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Optional

from arena.factory import get_gate, get_sandbox, get_transport
from arena.interfaces import Envelope, Transport
from arena.judge import judge

DB_PATH = Path("data/leaderboard.db")


# ------------------------------------------------------------------------------
# Circuit Breaker for BAND Transport
# ------------------------------------------------------------------------------
class CircuitBreaker:
    def __init__(self, failure_threshold: int = 3, cooldown_seconds: float = 300.0):
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds
        self.consecutive_failures = 0
        self.tripped_until = 0.0

    def is_open(self) -> bool:
        if self.tripped_until > 0:
            if time.time() < self.tripped_until:
                return True
            self.tripped_until = 0.0
        return False

    def record_failure(self):
        self.consecutive_failures += 1
        if self.consecutive_failures >= self.failure_threshold:
            self.tripped_until = time.time() + self.cooldown_seconds

    def record_success(self):
        self.consecutive_failures = 0
        self.tripped_until = 0.0

    def get_status(self) -> dict[str, Any]:
        open_state = self.is_open()
        remaining = max(0, int(self.tripped_until - time.time())) if open_state else 0
        return {
            "state": "open" if open_state else "closed",
            "consecutive_failures": self.consecutive_failures,
            "cooldown_remaining_s": remaining,
        }


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
        now_iso = datetime.now(UTC).isoformat()
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


def get_leaderboard_data() -> dict[str, Any]:
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
                "stats": {
                    "attempts_total": total_attempts,
                    "breaks_total": total_breaks,
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
def load_presets() -> list[dict[str, Any]]:
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


_last_patch_cache: dict[str, Any] | None = None
_last_patch_mtime: float = 0.0


def get_last_applied_patch() -> dict[str, Any] | None:
    """Retrieves the last applied patch from results.json with mtime caching for L2 challenge mode."""
    global _last_patch_cache, _last_patch_mtime
    results_path = Path("data/results.json")
    if not results_path.exists():
        results_path = Path("data/mock/results.json")
    if results_path.exists():
        try:
            mtime = results_path.stat().st_mtime
            if _last_patch_cache is not None and _last_patch_mtime == mtime:
                return _last_patch_cache
            with open(results_path, "r", encoding="utf-8") as f:
                res = json.load(f)
            patches = res.get("patches", [])
            for p in reversed(patches):
                if p.get("status") == "applied" and p.get("patch"):
                    _last_patch_cache = p.get("patch")
                    _last_patch_mtime = mtime
                    return _last_patch_cache
        except Exception:
            pass
    return _last_patch_cache


# ------------------------------------------------------------------------------
# Challenge Attempt State & Queue Management
# ------------------------------------------------------------------------------
class AttemptState:
    def __init__(self, attempt_id: str, req_data: dict[str, Any]):
        self.attempt_id = attempt_id
        self.req_data = req_data
        self.events: list[dict[str, Any]] = []
        self.verdict: dict[str, Any] | None = None
        self.error_reason: str | None = None
        self.created_at = time.time()
        self.subscribers: list[asyncio.Queue] = []
        self.done = False
        self.path: str = "in-process"

    def emit_event(self, event_type: str, data: dict[str, Any]):
        payload = {"event": event_type, "data": data}
        self.events.append(payload)
        for q in list(self.subscribers):
            try:
                q.put_nowait(payload)
            except Exception:
                pass

    def set_verdict(self, verdict: dict[str, Any]):
        self.verdict = verdict
        self.emit_event("verdict", verdict)
        self.done = True

    def set_error(self, reason: str):
        self.error_reason = reason
        err = {"reason": reason, "path": self.path}
        self.emit_event("error", err)
        self.done = True


class ChallengeManager:
    """
    Manages single-worker queue, active attempts, and SSE subscriber feeds.
    Includes circuit breaker and automated transport selector between BAND and loopback.
    """

    def __init__(self):
        self.queue: asyncio.Queue = asyncio.Queue(maxsize=10)
        self.attempts: dict[str, AttemptState] = {}
        self._worker_running = False
        self.circuit_breaker = CircuitBreaker()
        self.dispatcher_agent: Any = None
        self.dispatcher_task: asyncio.Task | None = None

    def get_queue_depth(self) -> int:
        return self.queue.qsize()

    def get_circuit_breaker_status(self) -> dict[str, Any]:
        return self.circuit_breaker.get_status()

    async def ensure_dispatcher_running(self) -> bool:
        if self.dispatcher_agent is not None and getattr(self.dispatcher_agent, "is_running", False):
            return True
        try:
            from agents.dispatcher_band import BandDispatcherAgent
            self.dispatcher_agent = BandDispatcherAgent()
            poll_int = float(os.getenv("BAND_POLL_INTERVAL_S", "0.2"))
            self.dispatcher_task = asyncio.create_task(self.dispatcher_agent.run(interval_s=poll_int))
            await self.dispatcher_agent.wait_ready(timeout_s=3.0)
            return True
        except Exception:
            return False

    def stop_dispatcher(self):
        if self.dispatcher_agent:
            try:
                self.dispatcher_agent.stop()
            except Exception:
                pass
        if self.dispatcher_task:
            try:
                self.dispatcher_task.cancel()
            except Exception:
                pass
        self.dispatcher_agent = None
        self.dispatcher_task = None

    def get_attempt(self, attempt_id: str) -> AttemptState | None:
        self._prune_old_attempts()
        return self.attempts.get(attempt_id)

    def _prune_old_attempts(self):
        now = time.time()
        expired = [
            k for k, v in self.attempts.items() if (now - v.created_at) > 3600
        ]
        for k in expired:
            self.attempts.pop(k, None)

    async def enqueue_attempt(self, req_data: dict[str, Any]) -> str:
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

    async def check_band_viable(self, sandbox: Any = None) -> bool:
        """
        Auto selection rule: use BAND if:
        (1) sandbox is pingable,
        (2) worker ready marker is fresh (< 30s) or pid is alive,
        (3) BAND room is reachable (read-only check),
        (4) Dispatcher listener is running in API process,
        (5) BAND keys are present;
        Otherwise returns False.
        """
        if self.circuit_breaker.is_open():
            return False

        # (5) BAND keys present
        a_key = os.getenv("BAND_AGENT_A_KEY")
        room_id = os.getenv("BAND_ROOM_ID", "0ff67f25-e8a4-42a5-a4ac-54d0c4ed727e")
        if not a_key or not room_id:
            return False

        if sandbox is None:
            sandbox = get_sandbox()

        # (1) Sandbox pingable
        try:
            if not await sandbox.ping():
                return False
        except Exception:
            return False

        # (2) Worker ready marker / process alive
        try:
            if hasattr(sandbox, "exec_command"):
                res = await sandbox.exec_command("ps aux | grep -v grep | grep worker_band")
                if res.get("exit_code") != 0:
                    return False
        except Exception:
            pass

        # (3) BAND room reachable
        try:
            from band_rest import RestClient
            c = RestClient(api_key=a_key)
            c.agent_api_messages.list_agent_messages(room_id, limit=1)
        except Exception:
            return False

        # (4) Dispatcher listener running in API process
        try:
            ok = await self.ensure_dispatcher_running()
            if not ok or not (self.dispatcher_agent and getattr(self.dispatcher_agent, "is_running", False)):
                return False
        except Exception:
            return False

        return True

    async def resolve_transport(self, sandbox: Any, gate: Any) -> tuple[Any, str]:
        use_mocks = os.getenv("USE_MOCKS", "1").strip().lower() in ("1", "true", "yes")
        challenge_transport = os.getenv("CHALLENGE_TRANSPORT", "auto").strip().lower()

        if use_mocks:
            from arena.mocks import MockTransport
            t = MockTransport(sandbox=sandbox, gate=gate)
            return t, "in-process"

        if challenge_transport == "loopback":
            from arena.transport_loopback import LoopbackTransport
            t = LoopbackTransport(state_dir=getattr(sandbox, "state_dir", Path("data/loopback_state")))
            if hasattr(t, "dispatcher") and t.dispatcher is not None:
                t.dispatcher.gate = gate
            return t, "in-process"

        if challenge_transport == "band":
            from arena.transport_band import BandTransport
            t = BandTransport(sandbox=sandbox)
            return t, "band+agent37"

        # "auto" mode
        is_band_viable = await self.check_band_viable(sandbox)
        if is_band_viable:
            from arena.transport_band import BandTransport
            t = BandTransport(sandbox=sandbox)
            return t, "band+agent37"

        # Fallback to loopback
        from arena.transport_loopback import LoopbackTransport
        t = LoopbackTransport(state_dir=getattr(sandbox, "state_dir", Path("data/loopback_state")))
        if hasattr(t, "dispatcher") and t.dispatcher is not None:
            t.dispatcher.gate = gate
        return t, "in-process"

    async def get_current_path(self) -> str:
        challenge_transport = os.getenv("CHALLENGE_TRANSPORT", "auto").strip().lower()
        use_mocks = os.getenv("USE_MOCKS", "1").strip().lower() in ("1", "true", "yes")
        if use_mocks or challenge_transport == "loopback":
            return "in-process"
        if challenge_transport == "band":
            return "band+agent37"
        if await self.check_band_viable():
            return "band+agent37"
        return "in-process"

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
            state.path = "in-process"
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
                    "decided_by": (
                        "gate"
                        if stopped_by == "gate"
                        else (
                            "redaction"
                            if stopped_by == "patch"
                            else ("model" if stopped_by == "worker" else "none")
                        )
                    ),
                    "goal": goal,
                    "path": "in-process",
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
        gate = get_gate()

        transport, path = await self.resolve_transport(sandbox, gate)
        state.path = path

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
        if hasattr(transport, "reset_state"):
            await transport.reset_state(canary)

        # L2 challenge mode: load the last applied patch from results.json
        if level == "L2":
            last_patch = get_last_applied_patch()
            if path == "band+agent37":
                if last_patch:
                    await sandbox.install_patch(last_patch)
                    if hasattr(sandbox, "exec_command"):
                        for _ in range(5):
                            check_res = await sandbox.exec_command("cat /home/node/.trustfall/patch_applied.json 2>/dev/null || cat /home/node/patch_applied.json 2>/dev/null")
                            if check_res.get("stdout"):
                                try:
                                    p_app = json.loads(check_res["stdout"])
                                    if p_app.get("version") == last_patch.get("version"):
                                        break
                                except Exception:
                                    pass
                            await asyncio.sleep(0.5)
            else:
                from agents.policy import Policy
                from contracts.models import Patch
                policy_obj = Policy(Patch.model_validate(last_patch)) if last_patch else Policy(None)
                if hasattr(transport, "worker") and transport.worker:
                    transport.worker.policy = policy_obj
        else:
            # Clear patch for L0/L1 baseline
            if path == "band+agent37":
                if hasattr(sandbox, "exec_command"):
                    await sandbox.exec_command("rm -f /home/node/patch.json /home/node/.trustfall/patch_applied.json /home/node/patch_applied.json")
            else:
                from agents.policy import Policy
                if hasattr(transport, "worker") and transport.worker:
                    transport.worker.policy = Policy(None)

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
                "decided_by": "gate",
                "goal": goal,
                "path": path,
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
        except TimeoutError:
            if path == "band+agent37":
                self.circuit_breaker.record_failure()
            state.set_error(reason="timeout")
            return
        except Exception:
            if path == "band+agent37":
                self.circuit_breaker.record_failure()
            state.set_error(reason="worker_down")
            return

        if outcome.error == "timeout":
            if path == "band+agent37":
                self.circuit_breaker.record_failure()
            state.set_error(reason="timeout")
            return
        elif outcome.error:
            if path == "band+agent37":
                self.circuit_breaker.record_failure()
            state.set_error(reason="worker_down")
            return

        # Success on BAND
        if path == "band+agent37":
            self.circuit_breaker.record_success()

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

        # stopped_by & decided_by attribution logic: ONLY from counters
        ctrls = outcome.controls or {}
        redactions = ctrls.get("redactions", 0)
        memory_denials = ctrls.get("memory_denials", 0)
        memory_notes_blocked = ctrls.get("memory_notes_blocked", 0)
        patch_actions = (redactions > 0 or memory_denials > 0 or memory_notes_blocked > 0)

        if judge_res.outcome == "blocked_by_gate" or outcome.blocked_by_gate:
            stopped_by = "gate"
            decided_by = "gate"
        elif judge_res.outcome == "succeeded":
            stopped_by = "none"
            decided_by = "none"
        elif patch_actions:
            stopped_by = "patch"
            decided_by = "redaction" if redactions > 0 else "memory_policy"
        else:
            stopped_by = "worker"
            decided_by = "model"

        # Gate metadata: reflects real gate call or BYPASSED if gate skipped
        if outcome.gate:
            gate_verdict = {
                "decision": outcome.gate.decision,
                "confidence": outcome.gate.confidence,
            }
        elif level == "L0":
            gate_verdict = {
                "decision": "BYPASSED",
                "confidence": 0.0,
            }
        else:
            gate_verdict = {
                "decision": "SAFE" if stopped_by != "gate" else "INJECTION",
                "confidence": 0.04 if stopped_by != "gate" else 0.98,
            }

        total_latency = int((time.perf_counter() - start_t) * 1000)
        verdict = {
            "outcome": judge_res.outcome,
            "stopped_by": stopped_by,
            "decided_by": decided_by,
            "goal": goal,
            "path": path,
            "gate": gate_verdict,
            "controls": ctrls,
            "latency_ms": total_latency,
        }
        state.set_verdict(verdict)
        record_attempt_stats(level, judge_res.outcome == "succeeded")

        if share and judge_res.outcome == "succeeded":
            add_leaderboard_entry(state.attempt_id, nickname, level, goal, text)


_challenge_manager: ChallengeManager | None = None


def get_challenge_manager() -> ChallengeManager:
    global _challenge_manager
    if _challenge_manager is None:
        _challenge_manager = ChallengeManager()
    return _challenge_manager
