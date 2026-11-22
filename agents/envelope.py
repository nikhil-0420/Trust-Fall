"""
Owner: Nikhil (Phase N2)
Envelope signing and verification using HMAC-SHA256.
Enforces fail-safe profile L2 fallback on missing or invalid signatures.
"""
import hashlib
import hmac
import json
import os
import secrets
from pathlib import Path
from typing import Any, Dict, Tuple, Union

from arena.interfaces import Envelope


def get_or_create_internal_token() -> str:
    """Reads INTERNAL_TOKEN from environment or creates and persists a random secret locally."""
    token = os.getenv("INTERNAL_TOKEN")
    if token and token.strip():
        return token.strip()

    new_token = secrets.token_hex(32)
    os.environ["INTERNAL_TOKEN"] = new_token

    env_path = Path(".env")
    try:
        content = ""
        if env_path.exists():
            content = env_path.read_text(encoding="utf-8")
        if "INTERNAL_TOKEN=" in content:
            lines = content.splitlines()
            new_lines = []
            for line in lines:
                if line.strip().startswith("INTERNAL_TOKEN="):
                    new_lines.append(f"INTERNAL_TOKEN={new_token}")
                else:
                    new_lines.append(line)
            env_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
        else:
            with open(env_path, "a", encoding="utf-8") as f:
                f.write(f"\nINTERNAL_TOKEN={new_token}\n")
    except Exception:
        pass

    return new_token


def canonical_envelope_bytes(envelope: Envelope) -> bytes:
    canonical_dict = {
        "kind": envelope.kind,
        "profile": envelope.profile,
        "text": envelope.text,
        "ticket_id": envelope.ticket_id,
    }
    return json.dumps(canonical_dict, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sign_envelope(envelope: Envelope, token: str) -> Dict[str, Any]:
    """Signs an Envelope using HMAC-SHA256 and returns envelope dictionary with signature."""
    payload_bytes = canonical_envelope_bytes(envelope)
    sig = hmac.new(token.encode("utf-8"), payload_bytes, hashlib.sha256).hexdigest()
    data = envelope.model_dump()
    data["signature"] = sig
    return data


def verify_envelope(
    raw: Union[Dict[str, Any], str, Envelope],
    token: str,
) -> Tuple[bool, Envelope, bool]:
    """
    Verifies the HMAC-SHA256 signature of an envelope.
    Returns (valid: bool, envelope: Envelope, flagged: bool).
    Rule: A message with a missing or invalid signature fails safe to profile L2 and is flagged.
    """
    if isinstance(raw, str):
        try:
            data = json.loads(raw)
        except Exception:
            fallback = Envelope(
                ticket_id="unknown",
                profile="L2",
                text=raw,
                kind="attack",
            )
            return False, fallback, True
    elif isinstance(raw, Envelope):
        # An Envelope object without signature metadata is unsigned
        fallback = Envelope(
            ticket_id=raw.ticket_id,
            attempt_id=raw.attempt_id,
            profile="L2",
            text=raw.text,
            kind=raw.kind,
            attack_id=raw.attack_id,
        )
        return False, fallback, True
    elif isinstance(raw, dict):
        data = raw
    else:
        fallback = Envelope(
            ticket_id="unknown",
            profile="L2",
            text=str(raw),
            kind="attack",
        )
        return False, fallback, True

    sig = data.get("signature")
    ticket_id = data.get("ticket_id", "unknown")
    profile = data.get("profile", "L0")
    text = data.get("text", "")
    kind = data.get("kind", "benign")
    attempt_id = data.get("attempt_id")
    attack_id = data.get("attack_id")

    if not sig:
        # Missing signature -> fallback to L2
        fallback = Envelope(
            ticket_id=ticket_id,
            attempt_id=attempt_id,
            profile="L2",
            text=text,
            kind=kind,
            attack_id=attack_id,
        )
        return False, fallback, True

    try:
        temp_env = Envelope(
            ticket_id=ticket_id,
            attempt_id=attempt_id,
            profile=profile,
            text=text,
            kind=kind,
            attack_id=attack_id,
        )
        expected_sig = hmac.new(
            token.encode("utf-8"),
            canonical_envelope_bytes(temp_env),
            hashlib.sha256,
        ).hexdigest()

        if hmac.compare_digest(sig, expected_sig):
            return True, temp_env, False
        else:
            # Invalid signature -> fail safe to L2
            fallback = Envelope(
                ticket_id=ticket_id,
                attempt_id=attempt_id,
                profile="L2",
                text=text,
                kind=kind,
                attack_id=attack_id,
            )
            return False, fallback, True
    except Exception:
        fallback = Envelope(
            ticket_id=ticket_id,
            attempt_id=attempt_id,
            profile="L2",
            text=text,
            kind=kind,
            attack_id=attack_id,
        )
        return False, fallback, True
