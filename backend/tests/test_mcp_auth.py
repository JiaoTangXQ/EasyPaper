from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.agent_deps import MCPAuthMiddleware


def _client() -> TestClient:
    app = FastAPI()
    app.add_middleware(MCPAuthMiddleware, mount_path="/mcp", api_keys=["good-key"])

    @app.get("/mcp")
    def mcp_root() -> dict:
        return {"ok": True}

    @app.post("/mcp/messages")
    def mcp_sub() -> dict:
        return {"ok": True}

    @app.get("/api/other")
    def other() -> dict:
        return {"ok": True}

    return TestClient(app)


def test_mcp_rejected_without_key() -> None:
    client = _client()
    assert client.get("/mcp").status_code == 403
    assert client.post("/mcp/messages").status_code == 403


def test_mcp_rejected_with_wrong_key() -> None:
    client = _client()
    assert client.get("/mcp", headers={"X-Agent-Api-Key": "nope"}).status_code == 403


def test_mcp_allowed_with_valid_key() -> None:
    client = _client()
    assert client.get("/mcp", headers={"X-Agent-Api-Key": "good-key"}).status_code == 200
    assert client.post("/mcp/messages", headers={"X-Agent-Api-Key": "good-key"}).status_code == 200


def test_non_mcp_paths_not_affected() -> None:
    client = _client()
    assert client.get("/api/other").status_code == 200
