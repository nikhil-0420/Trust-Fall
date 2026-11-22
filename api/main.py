"""
api/main.py
FastAPI application for Trust Fall arena, internal gate service, and reporting.
Owner: Nehaa (WS-D D2, D3)
"""
import glob
import hmac
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional
from fastapi import FastAPI, Header, HTTPException, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel, Field

from api.budget import get_budget
from api.gate import LyzrGate
from arena.factory import get_sandbox, get_transport

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
# Schemas
# ------------------------------------------------------------------------------
class ScreenRequest(BaseModel):
    text: str = Field(..., max_length=500)
    stage: Optional[str] = "inbound"


class ScreenResponse(BaseModel):
    decision: str
    confidence: float
    cached: bool


# ------------------------------------------------------------------------------
# Health & Status Endpoints
# ------------------------------------------------------------------------------
@app.get("/api/health")
async def health() -> Dict[str, str]:
    return {"status": "ok"}


@app.get("/api/status")
async def get_status() -> Dict[str, Any]:
    use_mocks = os.getenv("USE_MOCKS", "1").strip().lower() in {"1", "true", "yes"}

    worker_healthy = True
    try:
        sandbox = get_sandbox()
        worker_healthy = await sandbox.ping()
    except Exception:
        worker_healthy = False

    mode = "live" if (not use_mocks and worker_healthy) else "replay"
    worker_status = "up" if worker_healthy else "down"

    budget = get_budget()
    b_status = budget.status()

    return {
        "mode": mode,
        "worker": worker_status,
        "queue_depth": 0,
        "levels": {
            "L0": "Baseline",
            "L1": "Lyzr gate",
            "L2": "Patched",
        },
        "budget": b_status,
    }


# ------------------------------------------------------------------------------
# Results & Replay Endpoints
# ------------------------------------------------------------------------------
@app.get("/api/results")
async def get_results() -> Dict[str, Any]:
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
async def get_events(round_id: str) -> List[Dict[str, Any]]:
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
    if not report_file.exists():
        raise HTTPException(
            status_code=404,
            detail={"error": {"code": "not_found", "message": f"Report {r}.md not found"}},
        )

    content = report_file.read_text(encoding="utf-8")
    return Response(content=content, media_type="text/markdown")


@app.get("/api/leaderboard")
async def get_leaderboard() -> Dict[str, Any]:
    lb_file = Path("data/mock/leaderboard.json")
    if lb_file.exists():
        with open(lb_file, "r", encoding="utf-8") as f:
            return json.load(f)

    return {
        "total_attempts": 0,
        "successful_breaks": 0,
        "break_rate": 0.0,
        "entries": [],
    }


# ------------------------------------------------------------------------------
# Internal Gate Screening Endpoint
# ------------------------------------------------------------------------------
_gate_instance = LyzrGate()


@app.post("/internal/screen", response_model=ScreenResponse)
async def internal_screen(
    req: ScreenRequest,
    x_internal_token: Optional[str] = Header(None, alias="X-Internal-Token"),
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
