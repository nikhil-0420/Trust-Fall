"""Load, abuse, and safety checks for the API in mock mode (H9.3)."""

import asyncio
import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from api.challenge import get_challenge_manager
from api.limits import get_rate_limiter
from api.main import app


@pytest.fixture
def client():
    return TestClient(app)


@pytest.mark.asyncio
async def test_50_concurrent_sse_subscribers_on_one_attempt():
    """50 concurrent SSE subscribers on one attempt do not crash and disconnect cleanly."""
    mgr = get_challenge_manager()
    # Enqueue attempt directly in manager
    attempt_id = await mgr.enqueue_attempt({
        "level": "L0",
        "goal": "leak",
        "text": "Concurrent subscribers test payload",
        "nickname": "LoadTester",
        "share": False,
        "preset_id": "preset-1",
    })

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as ac:
        async def subscribe():
            res = await ac.get(f"/api/break/{attempt_id}/stream")
            assert res.status_code == 200
            assert "text/event-stream" in res.headers["content-type"]
            return len(res.text)

        # Run 50 concurrent requests
        tasks = [subscribe() for _ in range(50)]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for r in results:
            assert not isinstance(r, Exception), f"Subscriber failed with: {r}"
            assert isinstance(r, int)


def test_100_rapid_break_calls_hit_rate_limits():
    """100 rapid POST /api/break calls hit rate limits correctly (429 status)."""
    client = TestClient(app)
    limiter = get_rate_limiter()
    # Reset limiter for this session
    with limiter.lock:
        limiter.session_counts.clear()
        limiter.ip_counts.clear()

    session_id = "sess-load-test-100"
    status_codes = []

    for i in range(100):
        res = client.post(
            "/api/break",
            json={
                "level": "L0",
                "goal": "leak",
                "text": f"Rapid attack payload number {i}",
                "nickname": "Tester",
                "share": False,
                "website": "",
            },
            headers={"X-Session-Id": session_id},
        )
        status_codes.append(res.status_code)

    # First few should be 202, subsequent requests must be 429
    assert 202 in status_codes
    assert 429 in status_codes
    rate_limited_count = status_codes.count(429)
    assert rate_limited_count >= 80, f"Expected most requests to be 429, got {rate_limited_count}"


def test_oversized_and_malformed_bodies_return_4xx_never_500(client):
    """Oversized and malformed bodies return 4xx, never 500, with no stack traces."""
    # 1. Oversized body (> 500 chars)
    oversized_text = "A" * 501
    res = client.post(
        "/api/break",
        json={"level": "L0", "goal": "leak", "text": oversized_text},
        headers={"X-Session-Id": "sess-oversized"},
    )
    assert res.status_code in (400, 422)
    assert "Traceback" not in res.text

    # 2. Malformed JSON
    res_malformed = client.post(
        "/api/break",
        content="{'invalid_json': true}",
        headers={"Content-Type": "application/json", "X-Session-Id": "sess-malformed"},
    )
    assert res_malformed.status_code in (400, 422)
    assert "Traceback" not in res_malformed.text

    # 3. Missing required fields
    res_missing = client.post(
        "/api/break",
        json={"level": "L0"},
        headers={"X-Session-Id": "sess-missing"},
    )
    assert res_missing.status_code in (400, 422)
    assert "Traceback" not in res_missing.text

    # 4. Forbidden control characters
    res_ctrl = client.post(
        "/api/break",
        json={"level": "L0", "goal": "leak", "text": "Hello\x00World"},
        headers={"X-Session-Id": "sess-ctrl"},
    )
    assert res_ctrl.status_code == 400
    assert "Traceback" not in res_ctrl.text


def test_honeypot_rejection(client):
    """Honeypot field 'website' when non-empty returns 400 Bad Request."""
    res = client.post(
        "/api/break",
        json={
            "level": "L0",
            "goal": "leak",
            "text": "Payload from automated bot",
            "website": "http://spamsite.example.com",
        },
        headers={"X-Session-Id": "sess-bot"},
    )
    assert res.status_code == 400
    assert "Bot detected" in res.text


def test_attack_text_never_reflected_unescaped(client):
    """Attack text with HTML characters is escaped in leaderboard responses."""
    xss_payload = '<script>alert("XSS")</script>&<foo>'
    res = client.post(
        "/api/break",
        json={
            "level": "L0",
            "goal": "leak",
            "text": xss_payload,
            "nickname": "evil_tester",
            "share": True,
            "website": "",
        },
        headers={"X-Session-Id": "sess-xss-test"},
    )
    assert res.status_code in (202, 429)

    # Check leaderboard
    res_lb = client.get("/api/leaderboard")
    assert res_lb.status_code == 200
    lb_text = res_lb.text
    # Raw unescaped <script> must NEVER be present
    assert '<script>alert("XSS")</script>' not in lb_text


def test_heldout_texts_never_leak_through_any_endpoint(client):
    """Held-out attack texts from attacks/library.json never leak in presets, status, R0/R1 events."""
    lib_path = Path("attacks/library.json")
    if not lib_path.exists():
        pytest.skip("attacks/library.json not found")

    with open(lib_path, "r", encoding="utf-8") as f:
        attacks = json.load(f)

    heldout_texts = [a["text"].strip() for a in attacks if not a.get("known", True)]
    assert len(heldout_texts) >= 6, "Must have at least 6 held-out attacks"

    endpoints_to_check = [
        "/api/status",
        "/api/attacks/presets",
        "/api/leaderboard",
        "/api/events/R0",
        "/api/events/R1",
    ]

    for ep in endpoints_to_check:
        res = client.get(ep)
        assert res.status_code == 200, f"Endpoint {ep} failed"
        body_text = res.text
        for h_text in heldout_texts:
            assert h_text not in body_text, f"Held-out attack text leaked in {ep}: '{h_text[:30]}...'"
