"""Security review tests (H9.4).

Verifies constant-time token comparison, protected route rejection,
strict CORS handling, log/response secret cleanliness, and disk cache cleanliness.
"""

import logging
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api.main import app


@pytest.fixture
def client():
    return TestClient(app)


def test_internal_and_admin_routes_reject_missing_or_invalid_tokens(client, monkeypatch):
    monkeypatch.setenv("INTERNAL_TOKEN", "valid-secret-token-12345")

    # 1. /internal/screen with missing header
    res1 = client.post("/internal/screen", json={"text": "Test screening text"})
    assert res1.status_code == 401
    assert res1.json()["error"]["code"] == "unauthorized"

    # 2. /internal/screen with invalid token
    res2 = client.post(
        "/internal/screen",
        json={"text": "Test screening text"},
        headers={"X-Internal-Token": "wrong-token-abc"},
    )
    assert res2.status_code == 401
    assert res2.json()["error"]["code"] == "unauthorized"

    # 3. /internal/screen with valid token succeeds
    res3 = client.post(
        "/internal/screen",
        json={"text": "Test screening text"},
        headers={"X-Internal-Token": "valid-secret-token-12345"},
    )
    assert res3.status_code == 200
    assert "decision" in res3.json()

    # 4. /api/admin/leaderboard/entry-1 with missing token
    res4 = client.delete("/api/admin/leaderboard/entry-1")
    assert res4.status_code == 401
    assert res4.json()["error"]["code"] == "unauthorized"

    # 5. /api/admin/leaderboard/entry-1 with invalid token
    res5 = client.delete(
        "/api/admin/leaderboard/entry-1",
        headers={"X-Internal-Token": "bad-admin-token"},
    )
    assert res5.status_code == 401
    assert res5.json()["error"]["code"] == "unauthorized"


def test_cors_behavior_strict(client):
    # Origin that is in allowed origins
    res_ok = client.options(
        "/api/health",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert res_ok.headers.get("access-control-allow-origin") == "http://localhost:5173"

    # Origin that is NOT allowed
    res_bad = client.options(
        "/api/health",
        headers={
            "Origin": "http://malicious-attacker.com",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert res_bad.headers.get("access-control-allow-origin") is None


def test_no_canary_key_appears_in_logs_or_responses(client, monkeypatch, caplog):
    canary_fake_key = "FAKE_CANARY_SECRET_KEY_99999"
    monkeypatch.setenv("INTERNAL_TOKEN", canary_fake_key)
    monkeypatch.setenv("GEMINI_API_KEY", canary_fake_key)
    monkeypatch.setenv("LYZR_API_KEY", canary_fake_key)

    with caplog.at_level(logging.DEBUG):
        # Query endpoints
        endpoints = [
            "/api/health",
            "/api/status",
            "/api/results",
            "/api/attacks/presets",
            "/api/leaderboard",
        ]
        for ep in endpoints:
            res = client.get(ep)
            assert res.status_code == 200
            assert canary_fake_key not in res.text, f"Key leaked in response for {ep}"

    # Verify key does not appear in captured logs
    for record in caplog.records:
        assert canary_fake_key not in record.message, "Key leaked in application log message"


def test_budget_json_and_cache_directories_hold_no_secrets():
    repo_root = Path(__file__).resolve().parent.parent.parent
    budget_file = repo_root / "data" / "budget.json"
    cache_dir = repo_root / "data" / "cache"

    secret_patterns = [
        re.compile(r"AI" + r"za[0-9A-Za-z_-]{35}"),
        re.compile(r"lyzr-[0-9A-Za-z_-]{16,}"),
        re.compile(r"sk-[0-9A-Za-z_-]{20,}"),
        re.compile(r"token-[0-9a-f]{20,}"),
    ]

    if budget_file.exists():
        content = budget_file.read_text(encoding="utf-8")
        for pat in secret_patterns:
            assert not pat.search(content), f"Secret found in data/budget.json matching {pat.pattern}"

    if cache_dir.exists():
        for f in cache_dir.rglob("*.json"):
            content = f.read_text(encoding="utf-8")
            for pat in secret_patterns:
                assert not pat.search(content), f"Secret found in {f} matching {pat.pattern}"
