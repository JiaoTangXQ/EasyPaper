"""Server boundary: authenticate before parsing uploads, bound bodies and usage.

The server runs one worker. Burst/concurrent limits are per process; daily
admission counters are atomic and persisted across restarts in the database.
"""

import asyncio
import re
from collections import OrderedDict
from datetime import UTC, datetime
from time import monotonic

from fastapi import HTTPException
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session
from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse

from ..api.deps import get_current_user
from ..models.usage import DailyUsage

AI_OPERATION = re.compile(
    r"/api/(?:upload|upload-url|summary/[^/]+|tasks/[^/]+/(?:retry|title-translation)|knowledge/extract/[^/]+"
    r"|reading/[^/]+/(?:ask|summary|blocks/[^/]+/(?:aid|explain))"
    r"|reader/documents/[^/]+/(?:versions/[^/]+|annotations/[^/]+/align))/?$"
)


class BurstLimits:
    def __init__(self):
        self.entries = OrderedDict()

    def allow(self, key, limit):
        now = monotonic()
        # Bound attacker-controlled IP keys, including entries never used again.
        while self.entries and next(iter(self.entries.values()))[0] <= now:
            self.entries.popitem(last=False)
        if key not in self.entries:
            if len(self.entries) >= 10000:
                return False
            self.entries[key] = [now + 60, 0]
        self.entries[key][1] += 1
        return self.entries[key][1] <= limit


def charge_usage(session, user_id, kind, limit):
    key = f"{datetime.now(UTC):%Y-%m-%d}:{user_id}:{kind}"
    if session.get(DailyUsage, key) is None:
        try:
            session.add(DailyUsage(id=key))
            session.commit()
        except IntegrityError:
            session.rollback()
    result = session.execute(
        update(DailyUsage).where(DailyUsage.id == key, DailyUsage.count < limit).values(count=DailyUsage.count + 1)
    )
    session.commit()
    if result.rowcount != 1:
        raise HTTPException(429, "今日操作额度已用完，请明天再试或联系管理员")


class ServerGuard:
    def __init__(self, app, config, engine):
        self.app, self.config, self.engine = app, config, engine
        self.bursts = BurstLimits()
        self.active = 0
        self.large_active = 0

    def authenticate(self, token, method, path):
        with Session(self.engine) as session:
            user = get_current_user(session=session, token=token)
            if method == "POST" and AI_OPERATION.fullmatch(path) and not self.config.llm.is_configured:
                raise HTTPException(503, "AI 服务尚未配置，请联系管理员；已有论文仍可阅读。")
            # Read/save-state/delete stay usable after the expensive-operation
            # allowance is exhausted. Failed admitted attempts still cost a unit.
            # Preferences and short TTS reads are authenticated state/read
            # operations. They must remain available even when the daily AI
            # operation allowance is exhausted; automatic point-reading can
            # legitimately request one audio clip per click.
            billable = not path.startswith("/api/settings/") and path != "/api/reader/tts"
            if method in {"POST", "PUT"} and not path.endswith("/cancel") and billable:
                is_import = path in {"/api/upload", "/api/upload-url"}
                charge_usage(
                    session,
                    user.id,
                    "imports" if is_import else "operations",
                    self.config.security.daily_imports if is_import else self.config.security.daily_operations,
                )
            return user.id

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        path, method = scope["path"], scope["method"]
        headers = {k.lower(): v for k, v in scope["headers"]}

        async def reject(code, detail):
            response = JSONResponse({"detail": detail}, code, headers={"Retry-After": "60"} if code == 429 else None)
            await response(scope, receive, send)

        if not self.config.agent.enabled and (
            path.startswith("/api/agent") or path.startswith(self.config.agent.mcp_mount_path)
        ):
            return await reject(404, "接口未启用")
        if path == "/api/auth/register" and not self.config.security.allow_registration:
            return await reject(403, "注册已关闭，请联系管理员创建账号")
        ip = (scope.get("client") or ("unknown", 0))[0]
        auth_request = path.startswith("/api/auth/") and method == "POST"
        if not self.bursts.allow((ip, "auth" if auth_request else "all"), 10 if auth_request else 600):
            return await reject(429, "请求过于频繁，请稍后重试")
        if self.active >= 24:
            return await reject(429, "服务器繁忙，请稍后重试")

        # Login needs only a few KB; JSON 1 MB; uploads include multipart overhead.
        limit = 16384 if path.startswith("/api/auth/") else 1024 * 1024
        if path == "/api/upload":
            limit = (self.config.processing.max_upload_mb + 1) * 1024 * 1024
        if path.startswith("/api/reader/") and path.endswith("/restore"):
            limit = 129 * 1024 * 1024
        try:
            if int(headers.get(b"content-length", b"0")) > limit:
                return await reject(413, "请求内容超过大小限制")
        except ValueError:
            return await reject(400, "无效的请求长度")

        large = path in {"/api/upload", "/api/upload-url"} or path.endswith(("/restore", "/archive"))
        if large and self.large_active >= 2:
            return await reject(429, "文件服务繁忙，请稍后重试")
        self.active += 1
        self.large_active += int(large)
        try:
            public = {"/api/auth/login", "/api/auth/register", "/api/auth/features"}
            if path.startswith("/api/") and path not in public and method != "OPTIONS":
                value = headers.get(b"authorization", b"").decode("latin-1")
                scheme, _, token = value.partition(" ")
                if scheme.lower() != "bearer" or not token:
                    return await reject(401, "请先登录")
                try:
                    uid = await run_in_threadpool(self.authenticate, token, method, path)
                except HTTPException as exc:
                    return await reject(exc.status_code, exc.detail)
                if method not in {"GET", "HEAD", "OPTIONS"} and not self.bursts.allow((uid, "writes"), 60):
                    return await reject(429, "操作过于频繁，请稍后重试")
            received = 0

            async def limited_receive():
                nonlocal received
                try:
                    message = await asyncio.wait_for(receive(), timeout=30)
                except TimeoutError as exc:
                    raise HTTPException(408, "请求读取超时") from exc
                received += len(message.get("body", b""))
                if received > limit:
                    # HTTPException is handled by Starlette while parsing forms.
                    raise HTTPException(413, "请求内容超过大小限制")
                return message

            await self.app(scope, limited_receive, send)
        finally:
            self.active -= 1
            self.large_active -= int(large)
