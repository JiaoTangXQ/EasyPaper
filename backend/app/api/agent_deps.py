from __future__ import annotations

from fastapi import Header, HTTPException, status
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from ..core.config import get_config


def require_agent_api_key(x_agent_api_key: str | None = Header(default=None)) -> None:
    config = get_config()
    if not x_agent_api_key or x_agent_api_key not in config.agent.api_keys:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid agent API key",
        )


class MCPAuthMiddleware(BaseHTTPMiddleware):
    """Enforce the agent API key on the MCP mount path.

    The MCP transport is mounted directly on the app and, unlike the HTTP agent
    routes, has no per-route dependency. This middleware guards every request to
    ``mount_path`` (and its sub-paths) with the same ``X-Agent-Api-Key`` check.
    """

    def __init__(self, app, mount_path: str, api_keys: list[str]) -> None:
        super().__init__(app)
        self._mount_path = "/" + mount_path.strip("/")
        self._api_keys = set(api_keys)

    async def dispatch(self, request, call_next):
        path = request.url.path
        if path == self._mount_path or path.startswith(self._mount_path + "/"):
            key = request.headers.get("x-agent-api-key")
            if not key or key not in self._api_keys:
                return JSONResponse({"detail": "Invalid agent API key"}, status_code=403)
        return await call_next(request)
