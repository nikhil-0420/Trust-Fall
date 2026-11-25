"""
api/main.py
FastAPI application for Trust Fall arena, challenge mode, SSE streaming,
gate service, presets, and leaderboard.
Owner: Nehaa (WS-D D2, D3, D5, D6, D8)
"""
import glob
import hmac
import json
import os
import re
from pathlib import Path
from typing import Any, Literal
from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, Header, HTTPException, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, Field

from api.budget import get_budget
from api.challenge import (
    delete_leaderboard_entry,
    get_challenge_manager,
    get_leaderboard_data,
    load_presets,
)
from api.gate import LyzrGate
from api.limits import get_rate_limiter
from api.sse import stream_attempt_events
from arena.factory import get_sandbox

app = FastAPI(
    title="Trust Fall Arena API",
    version="1.0.0",
    docs_url="/docs",
    redoc_url=None,
)

# ------------------------------------------------------------------------------
# CORS Middleware
# ------------------------------------------------------------------------------
allowed_origins_env = os.getenv("ALLOWED_ORIGINS", "").strip()
if allowed_origins_env:
    origins = [orig.strip() for orig in allowed_origins_env.split(",") if orig.strip()]
else:
    origins = [
        "http://localhost:5173",
        "http://localhost:3000",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:3000",
    ]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ------------------------------------------------------------------------------
# Custom Exception Handler for uniform {error: {code, message}} responses
# ------------------------------------------------------------------------------
@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    detail = exc.detail
    if isinstance(detail, dict):
        return JSONResponse(status_code=exc.status_code, content=detail)
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": str(exc.status_code), "message": str(detail)}},
    )


# ------------------------------------------------------------------------------
# Request & Response Models
# ------------------------------------------------------------------------------
class ScreenRequest(BaseModel):
    text: str = Field(..., max_length=500)
    stage: str | None = "inbound"


class ScreenResponse(BaseModel):
    decision: str
    confidence: float
    cached: bool


class BreakRequest(BaseModel):
    level: Literal["L0", "L1", "L2"]
    goal: Literal["leak", "poison", "refund"]
    text: str
    nickname: str | None = None
    share: bool | None = False
    preset_id: str | None = None
    website: str | None = None  # Honeypot field


# ------------------------------------------------------------------------------
# Health & Status Endpoints
# ------------------------------------------------------------------------------
@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/status")
async def get_status() -> dict[str, Any]:
    use_mocks = os.getenv("USE_MOCKS", "1").strip().lower() in {"1", "true", "yes"}

    worker_healthy = True
    try:
        sandbox = get_sandbox()
        worker_healthy = await sandbox.ping()
    except Exception:
        worker_healthy = False

    budget = get_budget()
    b_status = budget.status()

    # Budget exhaustion triggers replay mode
    budget_exhausted = (
        b_status["llm_used"] >= int(b_status["llm_cap"] * 0.8)
        and b_status["lyzr_used"] >= int(b_status["lyzr_cap"] * 0.8)
    )

    if use_mocks or not worker_healthy or budget_exhausted:
        mode = "replay"
    else:
        mode = "live"

    worker_status = "up" if worker_healthy else "down"
    challenge_mgr = get_challenge_manager()
    current_path = await challenge_mgr.get_current_path()
    breaker_status = challenge_mgr.get_circuit_breaker_status()
    transport_mode = os.getenv("CHALLENGE_TRANSPORT", "auto").strip().lower()

    return {
        "mode": mode,
        "worker": worker_status,
        "transport": transport_mode,
        "path": current_path,
        "circuit_breaker": breaker_status,
        "queue_depth": challenge_mgr.get_queue_depth(),
        "levels": {
            "L0": {"name": "Baseline", "block_rate": 0.0, "latency_ms": 1200},
            "L1": {"name": "Lyzr gate", "block_rate": 0.5, "latency_ms": 1800},
            "L2": {"name": "Patched", "block_rate": 0.9, "latency_ms": 2100},
        },
        "budget": b_status,
    }


# ------------------------------------------------------------------------------
# Results & Replay Endpoints
# ------------------------------------------------------------------------------
@app.get("/api/results")
async def get_results() -> dict[str, Any]:
    results_file = Path("data/results.json")
    if not results_file.exists():
        results_file = Path("data/mock/results.json")

    if not results_file.exists():
        raise HTTPException(
            status_code=404,
            detail={"error": {"code": "not_found", "message": "results.json not found"}},
        )

    with open(results_file, "r", encoding="utf-8") as f:
        return json.load(f)


@app.get("/api/events/{round_id}")
async def get_events(round_id: str) -> list[dict[str, Any]]:
    r = round_id.upper()
    if r not in ("R0", "R1", "R2", "CH"):
        raise HTTPException(
            status_code=400,
            detail={"error": {"code": "bad_request", "message": f"Invalid round id '{round_id}'"}},
        )

    # 1. Look in data/mock/events-<round>.json
    mock_file = Path(f"data/mock/events-{r}.json")
    if mock_file.exists():
        with open(mock_file, "r", encoding="utf-8") as f:
            return json.load(f)

    # 2. Look in data/events/<round>.json
    data_file = Path(f"data/events/{r}.json")
    if data_file.exists():
        with open(data_file, "r", encoding="utf-8") as f:
            return json.load(f)

    # 3. Look in latest run data/runs/*/events-<round>.jsonl
    runs = sorted(glob.glob("data/runs/*/events-" + r + ".jsonl"))
    if runs:
        latest = runs[-1]
        events = []
        with open(latest, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    events.append(json.loads(line))
        return events

    return []


@app.get("/api/reports/{round_id}.md")
async def get_report(round_id: str):
    r = round_id.upper()
    report_file = Path(f"data/reports/{r}.md")
    if report_file.exists():
        content = report_file.read_text(encoding="utf-8")
        return Response(content=content, media_type="text/markdown")

    # Fallback to generating report from data/mock/results.json
    mock_results = Path("data/mock/results.json")
    if mock_results.exists():
        from arena.reports import generate_reports
        from contracts.models import Results
        import tempfile
        try:
            res_obj = Results.model_validate_json(mock_results.read_text(encoding="utf-8"))
            with tempfile.TemporaryDirectory() as tmpdir:
                generate_reports(res_obj, output_dir=tmpdir)
                tmp_rep = Path(tmpdir) / f"{r}.md"
                if tmp_rep.exists():
                    return Response(content=tmp_rep.read_text(encoding="utf-8"), media_type="text/markdown")
        except Exception:
            pass

    raise HTTPException(
        status_code=404,
        detail={"error": {"code": "not_found", "message": f"Report {r}.md not found"}},
    )


# ------------------------------------------------------------------------------
# Presets & Leaderboard
# ------------------------------------------------------------------------------
@app.get("/api/attacks/presets")
async def get_presets() -> list[dict[str, Any]]:
    return load_presets()


@app.get("/api/leaderboard")
async def get_leaderboard() -> dict[str, Any]:
    return get_leaderboard_data()


@app.delete("/api/admin/leaderboard/{entry_id}")
async def admin_delete_leaderboard(
    entry_id: str,
    x_internal_token: str | None = Header(None, alias="X-Internal-Token"),
):
    expected_token = os.getenv("INTERNAL_TOKEN", "").strip()
    if not expected_token or not x_internal_token or not hmac.compare_digest(x_internal_token, expected_token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": {"code": "unauthorized", "message": "Invalid admin token"}},
        )

    deleted = delete_leaderboard_entry(entry_id)
    if not deleted:
        raise HTTPException(
            status_code=404,
            detail={"error": {"code": "not_found", "message": f"Entry {entry_id} not found"}},
        )
    return {"status": "deleted", "id": entry_id}


# ------------------------------------------------------------------------------
# Challenge Mode: Break Attempt & SSE Streaming
# ------------------------------------------------------------------------------
@app.post("/api/break", status_code=status.HTTP_202_ACCEPTED)
async def submit_break(
    req: BreakRequest,
    request: Request,
    x_session_id: str | None = Header(None, alias="X-Session-Id"),
):
    # 1. Honeypot check
    if req.website and req.website.strip():
        raise HTTPException(
            status_code=400,
            detail={"error": {"code": "bad_request", "message": "Bot detected"}},
        )

    # 2. Refund goal disabled unless ENABLE_REFUND=1
    enable_refund = os.getenv("ENABLE_REFUND", "0").strip() == "1"
    if req.goal == "refund" and not enable_refund:
        raise HTTPException(
            status_code=400,
            detail={"error": {"code": "bad_request", "message": "Refund goal is disabled (contagion is P2)"}},
        )

    # 3. Input validation
    clean_text = req.text.strip()
    if len(clean_text) < 1 or len(clean_text) > 500:
        raise HTTPException(
            status_code=400,
            detail={"error": {"code": "bad_request", "message": "Text length must be between 1 and 500 characters"}},
        )

    if re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", clean_text):
        raise HTTPException(
            status_code=400,
            detail={"error": {"code": "bad_request", "message": "Text contains forbidden control characters"}},
        )

    if req.nickname:
        clean_nick = req.nickname.strip()
        if len(clean_nick) > 24 or not re.match(r"^[a-zA-Z0-9 _-]+$", clean_nick):
            raise HTTPException(
                status_code=400,
                detail={"error": {"code": "bad_request", "message": "Nickname must be alphanumeric/space/-/_ <= 24 chars"}},
            )

    # 4. Rate Limiting & Budget
    limiter = get_rate_limiter()
    client_ip = request.client.host if request.client else "127.0.0.1"

    if req.preset_id:
        # Presets cost 0 live calls, checked only against session limit
        with limiter.lock:
            limiter._check_rollover()
            if x_session_id:
                s_count = limiter.session_counts.get(x_session_id, 0)
                if s_count >= limiter.session_limit:
                    raise HTTPException(
                        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                        detail={
                            "error": {
                                "code": "rate_limit_exceeded",
                                "message": "Daily session limit reached",
                                "reason": "rate",
                                "retry_after": 3600,
                            }
                        },
                    )
                limiter.session_counts[x_session_id] = s_count + 1
    else:
        # Live attempt: enforce session, IP, and global budget
        allowed, reason, retry_after = limiter.check_limits(x_session_id, client_ip)
        if not allowed:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={
                    "error": {
                        "code": "rate_limit_exceeded",
                        "message": f"Daily limit exceeded: {reason}",
                        "reason": reason,
                        "retry_after": retry_after,
                    }
                },
            )

    # 5. Enqueue attempt
    challenge_mgr = get_challenge_manager()
    req_dict = req.model_dump()
    req_dict["text"] = clean_text

    try:
        attempt_id = await challenge_mgr.enqueue_attempt(req_dict)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "error": {
                    "code": "rate_limit_exceeded",
                    "message": "Challenge queue is full, please retry shortly",
                    "reason": "queue",
                    "retry_after": 10,
                }
            },
        )

    return {"attempt_id": attempt_id}


@app.get("/api/break/{attempt_id}/stream")
async def stream_break_events(attempt_id: str):
    challenge_mgr = get_challenge_manager()
    state = challenge_mgr.get_attempt(attempt_id)
    if not state:
        raise HTTPException(
            status_code=404,
            detail={"error": {"code": "not_found", "message": f"Attempt {attempt_id} not found"}},
        )

    return StreamingResponse(
        stream_attempt_events(attempt_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/api/break/{attempt_id}")
async def get_break_verdict(attempt_id: str) -> dict[str, Any]:
    challenge_mgr = get_challenge_manager()
    state = challenge_mgr.get_attempt(attempt_id)
    if not state:
        raise HTTPException(
            status_code=404,
            detail={"error": {"code": "not_found", "message": f"Attempt {attempt_id} not found"}},
        )

    if state.done and not state.verdict:
        err_ev = next((e["data"] for e in state.events if e.get("event") == "error"), {})
        return {
            "status": "error",
            "attempt_id": attempt_id,
            "error": err_ev.get("reason", "unknown_error"),
            "level": state.req_data.get("level"),
            "goal": state.req_data.get("goal"),
            "path": getattr(state, "path", "in-process"),
        }

    if not state.done:
        return {
            "status": "running",
            "attempt_id": attempt_id,
            "level": state.req_data.get("level"),
            "goal": state.req_data.get("goal"),
        }

    res = dict(state.verdict)
    res["attempt_id"] = attempt_id
    res["status"] = "done"
    res["level"] = state.req_data.get("level")
    res["goal"] = state.req_data.get("goal")
    if state.req_data.get("share"):
        res["text"] = state.req_data.get("text")
    return res


# ------------------------------------------------------------------------------
# Internal Gate Screening Endpoint
# ------------------------------------------------------------------------------
_gate_instance = LyzrGate()


@app.post("/internal/screen", response_model=ScreenResponse)
async def internal_screen(
    req: ScreenRequest,
    x_internal_token: str | None = Header(None, alias="X-Internal-Token"),
) -> ScreenResponse:
    expected_token = os.getenv("INTERNAL_TOKEN", "").strip()

    if not expected_token or not x_internal_token or not hmac.compare_digest(x_internal_token, expected_token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": {"code": "unauthorized", "message": "Invalid or missing X-Internal-Token"}},
        )

    res = await _gate_instance.screen(req.text, stage=req.stage or "inbound")
    return ScreenResponse(
        decision=res.decision,
        confidence=res.confidence,
        cached=res.cached,
    )
