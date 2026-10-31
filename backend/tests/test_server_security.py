from datetime import timedelta

import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.api.deps import get_current_user
from app.cli import change_user, create_user
from app.core.config import AppConfig, get_config, validate_security
from app.core.security import create_access_token
from app.core.server_guard import ServerGuard, charge_usage
from app.models.usage import DailyUsage  # noqa: F401
from app.services.job_queue import JobQueue
from app.services.pdf_validation import validate_pdf


@pytest.fixture
def account(session):
    return create_user("owner@example.com", "example-password-123", session=session)


@pytest.fixture
def server(engine, account):
    config = AppConfig(llm={}, agent={"enabled": False}, security={"allow_registration": False, "daily_operations": 2})
    app = FastAPI()
    app.add_middleware(ServerGuard, config=config, engine=engine)

    @app.api_route("/api/protected", methods=["GET", "POST"])
    async def endpoint(request: Request):
        return {"size": len(await request.body())}

    @app.post("/api/upload")
    async def upload(request: Request):
        return {"size": len(await request.body())}

    @app.post("/api/settings/preferences")
    async def preferences():
        return {"ok": True}

    @app.post("/api/reader/tts")
    async def tts():
        return {"ok": True}

    return TestClient(app), {"Authorization": "Bearer " + create_access_token(account.id)}, config


def test_production_disables_old_config_entrypoints(monkeypatch, tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text("llm: {}\nsecurity:\n  allow_registration: true\nagent:\n  api_keys: [CHANGE_ME]\n")
    monkeypatch.setenv("APP_CONFIG_PATH", str(path))
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("EASYPAPER_SECRET_KEY", "a" * 64)
    get_config.cache_clear()
    try:
        config = get_config()
        assert not config.security.allow_registration
        assert not config.security.local_sync_enabled
        assert not config.agent.enabled
        assert not config.agent.api_keys
    finally:
        get_config.cache_clear()


@pytest.mark.parametrize("secret", ["", "short", "CHANGE_THIS" + "x" * 64])
def test_production_rejects_invalid_secret(secret):
    config = AppConfig(llm={}, security={"secret_key": secret}, agent={"enabled": False})
    with pytest.raises(RuntimeError):
        validate_security(config, "production")


def test_codex_container_configuration_preserves_explicit_model(monkeypatch, tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text("llm: {}\n")
    monkeypatch.setenv("APP_CONFIG_PATH", str(path))
    monkeypatch.setenv("EASYPAPER_AI_PROVIDER", "codex")
    monkeypatch.setenv("EASYPAPER_CODEX_EXECUTABLE", "/opt/codex/bin/codex")
    monkeypatch.setenv("EASYPAPER_CODEX_MODEL", "configured-codex-model")
    monkeypatch.setenv("EASYPAPER_CODEX_REASONING_EFFORT", "low")
    monkeypatch.setenv("EASYPAPER_CODEX_MAX_CONCURRENT", "1")
    monkeypatch.setenv("EASYPAPER_CODEX_TIMEOUT_SECONDS", "180")
    get_config.cache_clear()
    try:
        llm = get_config().llm
        assert llm.provider == "codex"
        assert llm.codex.executable == "/opt/codex/bin/codex"
        assert llm.codex.model == "configured-codex-model"
        assert llm.codex.max_concurrent == 1
        assert llm.codex.reasoning_effort == "low"
        assert llm.codex.timeout_seconds == 180
    finally:
        get_config.cache_clear()


def test_cursor_container_configuration_preserves_explicit_model(monkeypatch, tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text("llm: {}\n")
    monkeypatch.setenv("APP_CONFIG_PATH", str(path))
    monkeypatch.setenv("EASYPAPER_AI_PROVIDER", "cursor")
    monkeypatch.setenv("EASYPAPER_CURSOR_EXECUTABLE", "/opt/cursor-p/bin/cursor-p")
    monkeypatch.setenv("EASYPAPER_CURSOR_MODEL", "configured-cursor-model")
    monkeypatch.setenv("EASYPAPER_CURSOR_MAX_CONCURRENT", "1")
    monkeypatch.setenv("EASYPAPER_CURSOR_TIMEOUT_SECONDS", "180")
    get_config.cache_clear()
    try:
        llm = get_config().llm
        assert llm.provider == "cursor"
        assert llm.uses_cli
        assert llm.cursor.executable == "/opt/cursor-p/bin/cursor-p"
        assert llm.cursor.model == "configured-cursor-model"
        assert llm.cursor.max_concurrent == 1
        assert llm.cursor.timeout_seconds == 180
        assert llm.is_configured
    finally:
        get_config.cache_clear()


def test_closed_registration_and_agent_interfaces(server):
    client, _, _ = server
    assert client.post("/api/auth/register", content=b"invalid").status_code == 403
    for path in ("/mcp", "/mcp/", "/api/agent/v1/translate"):
        assert client.post(path).status_code == 404
    assert client.get("/api/protected").status_code == 401


def test_unconfigured_ai_rejects_before_consuming_upload_or_charging_quota(server, session):
    from sqlmodel import select

    client, headers, config = server
    assert client.post("/api/upload", content=b"invalid").status_code == 401
    for path in (
        "/api/upload",
        "/api/upload-url",
        "/api/tasks/example/retry",
        "/api/tasks/example/title-translation",
        "/api/reading/example/ask",
        "/api/reader/documents/example/versions/translated",
    ):
        response = client.post(path, content=b"invalid", headers=headers)
        assert response.status_code == 503
        assert "尚未配置" in response.json()["detail"]
    assert not session.exec(select(DailyUsage)).all()
    assert client.get("/api/protected", headers=headers).status_code == 200
    config.llm.api_key = "configured-test-key"
    assert client.post("/api/upload", content=b"example", headers=headers).status_code == 200


def test_features_expose_capabilities_without_credentials(client, monkeypatch):
    config = AppConfig(llm={}, processing={"max_pages": 30, "max_upload_mb": 15})
    monkeypatch.setattr("app.api.auth.get_config", lambda: config)
    data = client.get("/api/auth/features").json()
    assert data == {
        "ai_available": False,
        "max_pages": 30,
        "max_upload_mb": 15,
        "registration": True,
        "local_sync": True,
    }
    config.llm.api_key = "private-value"
    assert client.get("/api/auth/features").json()["ai_available"] is True
    assert "private-value" not in client.get("/api/auth/features").text


def test_rejects_oversized_body_with_and_without_content_length(server):
    client, headers, _ = server
    assert (
        client.post("/api/protected", content=b"x", headers={**headers, "Content-Length": str(2 * 1024**2)}).status_code
        == 413
    )
    # Streaming payload: enforce size while consuming, even without Content-Length.
    response = client.post("/api/protected", content=iter([b"x" * (1024**2 + 1)]), headers=headers)
    assert response.status_code == 413


def test_daily_quota_persists_across_requests_and_keeps_reads_available(server):
    client, headers, _ = server
    assert client.post("/api/protected", headers=headers).status_code == 200
    assert client.post("/api/protected", headers=headers).status_code == 200
    assert client.post("/api/protected", headers=headers).status_code == 429
    assert client.get("/api/protected", headers=headers).status_code == 200


def test_preferences_and_reader_tts_do_not_consume_daily_operation_quota(server, session):
    from sqlmodel import select

    client, headers, _ = server
    assert client.post("/api/settings/preferences", headers=headers).status_code == 200
    assert client.post("/api/reader/tts", headers=headers).status_code == 200
    assert not session.exec(select(DailyUsage)).all()


def test_daily_quota_is_per_account_and_persistent(engine, account):
    with Session(engine) as session:
        charge_usage(session, account.id, "imports", 1)
    with Session(engine) as session:
        with pytest.raises(HTTPException) as exc:
            charge_usage(session, account.id, "imports", 1)
        assert exc.value.status_code == 429
        charge_usage(session, account.id + 1, "imports", 1)


def test_disabling_then_enabling_does_not_restore_old_token(session, account):
    token = create_access_token(account.id)
    change_user(account.email, "disable-user", session=session)
    with pytest.raises(HTTPException):
        get_current_user(session=session, token=token)
    change_user(account.email, "enable-user", session=session)
    with pytest.raises(HTTPException):
        get_current_user(session=session, token=token)
    token = create_access_token(account.id, token_version=account.token_version)
    assert get_current_user(session=session, token=token).id == account.id


def test_reset_password_revokes_existing_login(session, account):
    token = create_access_token(account.id)
    change_user(account.email, "reset-password", session=session, password="replacement-password-456")
    with pytest.raises(HTTPException):
        get_current_user(session=session, token=token)


def test_expired_token_rejected(session, account):
    token = create_access_token(account.id, timedelta(seconds=-1))
    with pytest.raises(HTTPException):
        get_current_user(session=session, token=token)


def test_account_cap_and_password_policy(session, monkeypatch):
    config = AppConfig(llm={}, security={"max_users": 1})
    monkeypatch.setattr("app.cli.get_config", lambda: config)
    with pytest.raises(ValueError):
        create_user("short@example.com", "short", session=session)
    create_user("first@example.com", "test-password-123", session=session)
    with pytest.raises(ValueError):
        create_user("second@example.com", "test-password-123", session=session)


@pytest.mark.asyncio
async def test_queue_bounds_owners_and_releases_after_success_failure_and_cancel():
    import asyncio

    config = AppConfig(llm={}, processing={"max_pending": 2, "max_pending_per_user": 1})
    queue = JobQueue(config.processing)
    ready = asyncio.Event()
    with queue.reserve(1) as start:
        task = start(ready.wait())
    with pytest.raises(HTTPException):
        with queue.reserve(1):
            pass
    with queue.reserve(2):
        with pytest.raises(HTTPException):
            with queue.reserve(3):
                pass
    ready.set()
    await task
    await asyncio.sleep(0)
    assert not queue.owners
    with pytest.raises(ValueError), queue.reserve(1):
        raise ValueError("upload failed")
    assert not queue.owners
    with queue.reserve(1) as start:
        task = start(asyncio.sleep(100))
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await asyncio.sleep(0)
    assert not queue.owners


def test_pdf_page_limit_and_invalid_content():
    import fitz

    with fitz.open() as doc:
        doc.new_page()
        doc.new_page()
        data = doc.tobytes()
    validate_pdf(data, 2)
    with pytest.raises(HTTPException):
        validate_pdf(data, 1)
    with pytest.raises(HTTPException):
        validate_pdf(b"not a PDF", 10)


def test_uploaded_absolute_filename_cannot_overwrite_server_file(monkeypatch, tmp_path):
    from types import SimpleNamespace

    import pdf2zh
    from pdf2zh.doclayout import DocLayoutModel

    from app.services.document_processor import DocumentProcessor

    outside = tmp_path / "existing.pdf"
    outside.write_bytes(b"must survive")
    monkeypatch.setattr(DocLayoutModel, "load_available", lambda: object())
    monkeypatch.setattr(pdf2zh, "translate", lambda **kwargs: [(kwargs["files"][0], None)])
    processor = DocumentProcessor(
        AppConfig(llm={"api_key": "fixture"}), SimpleNamespace(update_progress=lambda *args: None)
    )
    translated, _, _ = processor._translate_with_pdf2zh(b"%PDF-fixture", str(outside), "fixture")
    assert translated == b"%PDF-fixture"
    assert outside.read_bytes() == b"must survive"


def test_existing_accounts_survive_token_version_migration(engine, session, account, monkeypatch):
    from sqlalchemy import text

    from app.core import db
    from app.models.user import User

    uid, email = account.id, account.email
    session.close()
    with engine.begin() as connection:
        connection.execute(text('ALTER TABLE "user" DROP COLUMN token_version'))
    monkeypatch.setattr(db, "engine", engine)
    monkeypatch.setattr(db, "_database_url", lambda: "sqlite://")
    db.init_db()
    db.init_db()  # Restart / repeated administrative commands are safe.
    with Session(engine) as fresh:
        user = fresh.get(User, uid)
        assert user.email == email
        assert user.token_version == 0
