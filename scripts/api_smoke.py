#!/usr/bin/env python3
"""
scripts/api_smoke.py
Smoke test for API endpoints using FastAPI TestClient / httpx.
Checks endpoints: /api/health, /api/status, /api/results, /api/events/R0, /api/reports/R0.md, /internal/screen.
Owner: Nehaa (WS-D D2, D3)
"""
import os
import sys
from pathlib import Path

repo_root = Path(__file__).resolve().parent.parent
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

from fastapi.testclient import TestClient
from api.main import app

def run_smoke():
    client = TestClient(app)
    passed = 0
    total = 0

    def check(name: str, condition: bool):
        nonlocal passed, total
        total += 1
        status_str = "PASS" if condition else "FAIL"
        if condition:
            passed += 1
        print(f"[{status_str}] {name}")

    print("\n--- Running Trust Fall API Smoke Tests ---")

    # 1. Health
    r = client.get("/api/health")
    check("GET /api/health returns 200 and status ok", r.status_code == 200 and r.json().get("status") == "ok")

    # 2. Status
    r = client.get("/api/status")
    data = r.json()
    check("GET /api/status returns valid mode and budget", r.status_code == 200 and "mode" in data and "budget" in data)

    # 3. Results
    r = client.get("/api/results")
    check("GET /api/results returns valid results with rounds", r.status_code == 200 and "rounds" in r.json())

    # 4. Events R0
    r = client.get("/api/events/R0")
    check("GET /api/events/R0 returns non-empty event list", r.status_code == 200 and isinstance(r.json(), list) and len(r.json()) > 0)

    # 5. Reports R0.md
    r = client.get("/api/reports/R0.md")
    check("GET /api/reports/R0.md returns markdown report", r.status_code == 200 and "Trust Fall Incident Report" in r.text)

    # 6. Leaderboard
    r = client.get("/api/leaderboard")
    check("GET /api/leaderboard returns entries list", r.status_code == 200 and "entries" in r.json())

    # 7. Internal Screen (Auth check)
    token = os.getenv("INTERNAL_TOKEN", "test-internal-token")
    os.environ["INTERNAL_TOKEN"] = token

    # Missing token -> 401
    r_unauth = client.post("/internal/screen", json={"text": "Hello"})
    check("POST /internal/screen without token returns 401", r_unauth.status_code == 401)

    # Valid token -> 200
    r_auth = client.post("/internal/screen", headers={"X-Internal-Token": token}, json={"text": "Hello support"})
    check("POST /internal/screen with valid token returns 200 and decision", r_auth.status_code == 200 and "decision" in r_auth.json())

    print(f"\nSmoke Test Summary: {passed}/{total} passed.")
    if passed != total:
        sys.exit(1)

if __name__ == "__main__":
    run_smoke()
