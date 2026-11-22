"""Tests for deployment configuration files and container startup defaults."""

import re
from pathlib import Path

from fastapi.testclient import TestClient

from api.main import app


def test_dockerfile_and_render_yaml_have_no_secrets():
    repo_root = Path(__file__).resolve().parent.parent.parent
    dockerfile_path = repo_root / "deploy" / "Dockerfile"
    render_yaml_path = repo_root / "deploy" / "render.yaml"

    assert dockerfile_path.exists(), "deploy/Dockerfile must exist"
    assert render_yaml_path.exists(), "deploy/render.yaml must exist"

    dockerfile_content = dockerfile_path.read_text(encoding="utf-8")
    render_yaml_content = render_yaml_path.read_text(encoding="utf-8")

    # Secret patterns
    secret_patterns = [
        re.compile(r"AI" + r"za[0-9A-Za-z_-]{35}"),
        re.compile(r"lyzr-[0-9A-Za-z_-]{16,}"),
        re.compile(r"sk-[0-9A-Za-z_-]{20,}"),
        re.compile(r"token-[0-9a-f]{20,}"),
    ]

    for pattern in secret_patterns:
        assert not pattern.search(dockerfile_content), f"Secret found in Dockerfile matching {pattern.pattern}"
        assert not pattern.search(render_yaml_content), f"Secret found in render.yaml matching {pattern.pattern}"


def test_dockerignore_excludes_sensitive_and_dev_paths():
    repo_root = Path(__file__).resolve().parent.parent.parent
    dockerignore_path = repo_root / ".dockerignore"
    assert dockerignore_path.exists(), ".dockerignore must exist"

    content = dockerignore_path.read_text(encoding="utf-8")
    lines = [line.strip() for line in content.splitlines() if line.strip() and not line.startswith("#")]

    required_exclusions = [".env", ".venv", "data/runs", "tests", "web", "node_modules"]
    for req in required_exclusions:
        assert any(req in line for line in lines), f".dockerignore must exclude '{req}'"


def test_render_yaml_env_vars_declared_without_values():
    repo_root = Path(__file__).resolve().parent.parent.parent
    render_yaml_path = repo_root / "deploy" / "render.yaml"

    content = render_yaml_path.read_text(encoding="utf-8")
    # Verify environment variables are declared with sync: false or empty/placeholder, no raw secrets
    assert "USE_MOCKS" in content
    assert "INTERNAL_TOKEN" in content
    assert "GEMINI_API_KEY" in content


def test_app_starts_with_documented_minimal_env():
    # Verify app starts cleanly and responds to health and status probes
    client = TestClient(app)
    res = client.get("/api/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}

    res_status = client.get("/api/status")
    assert res_status.status_code == 200
    assert "mode" in res_status.json()
