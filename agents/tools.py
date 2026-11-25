"""
Owner: Nikhil (Phase N1, updated N2)
Worker tools: read_memory, write_memory, send_report.
Only these three tools are permitted. No HTTP, shell, or arbitrary file tools.
"""
import json
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_DEFAULT_STATE_DIR = Path(os.getenv("STATE_DIR", "data/worker_state"))


def set_default_state_dir(path: Path) -> None:
    global _DEFAULT_STATE_DIR
    _DEFAULT_STATE_DIR = path


def read_memory(
    state_dir: Path | None = None,
    policy: Any = None,
) -> list[dict[str, Any]]:
    """
    Read memory notes from memory.json in state_dir.
    Returns list of dicts: [{"id": ..., "text": ..., "created_at": ...}].
    """
    target_dir = state_dir or _DEFAULT_STATE_DIR
    memory_file = target_dir / "memory.json"
    if not memory_file.exists():
        return []
    try:
        data = json.loads(memory_file.read_text(encoding="utf-8"))
        if isinstance(data, dict) and "notes" in data and isinstance(data["notes"], list):
            return data["notes"]
        elif isinstance(data, list):
            return data
        return []
    except Exception:
        return []


def write_memory(
    text: str,
    state_dir: Path | None = None,
    policy: Any = None,
) -> dict[str, Any]:
    """
    Write a memory note to memory.json in state_dir.
    Applies policy check if policy is provided.
    """
    if policy is not None and hasattr(policy, "allow_memory_write"):
        allowed, reason = policy.allow_memory_write(text)
        if not allowed:
            return {"success": False, "reason": reason, "policy_denied": True}

    target_dir = state_dir or _DEFAULT_STATE_DIR
    target_dir.mkdir(parents=True, exist_ok=True)
    memory_file = target_dir / "memory.json"

    notes: list[dict[str, Any]] = []
    if memory_file.exists():
        try:
            data = json.loads(memory_file.read_text(encoding="utf-8"))
            if isinstance(data, dict) and "notes" in data and isinstance(data["notes"], list):
                notes = data["notes"]
            elif isinstance(data, list):
                notes = data
        except Exception:
            notes = []

    note_id = f"note-{uuid.uuid4().hex[:8]}"
    created_at = datetime.now(UTC).isoformat()
    new_note = {"id": note_id, "text": text, "created_at": created_at}
    notes.append(new_note)

    memory_file.write_text(json.dumps({"notes": notes}, indent=2), encoding="utf-8")
    try:
        if target_dir != Path("."):
            Path("memory.json").write_text(json.dumps({"notes": notes}, indent=2), encoding="utf-8")
    except Exception:
        pass
    return {"success": True, "note": new_note}


def send_report(
    ticket_id: str,
    status: str,
    summary: str,
    policy: Any = None,
    secret: str | None = None,
) -> dict[str, Any]:
    """
    Sends customer support report. Applies redaction policy if configured.
    """
    redactions_count = 0
    if policy is not None and hasattr(policy, "redact_report"):
        try:
            res = policy.redact_report(summary, return_count=True, secret=secret)
            if isinstance(res, tuple):
                summary, redactions_count = res
            else:
                summary = res
                redactions_count = getattr(policy, "last_redactions_count", 0)
        except TypeError:
            try:
                summary = policy.redact_report(summary, return_count=True)
                if isinstance(res, tuple):
                    summary, redactions_count = res
            except TypeError:
                summary = policy.redact_report(summary)
                redactions_count = getattr(policy, "last_redactions_count", 0)

    report_text = f"Ticket {ticket_id} [{status}]: {summary}"
    return {
        "ticket_id": ticket_id,
        "status": status,
        "summary": summary,
        "report_text": report_text,
        "redactions_count": redactions_count,
    }


# Canonical alias
save_note = write_memory
