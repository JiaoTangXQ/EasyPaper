from __future__ import annotations

import logging
import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field

GlossPreparationSite = Literal["server", "remote_worker", "user_choice"]

logger = logging.getLogger(__name__)


class CodexConfig(BaseModel):
    executable: str = "codex"
    # Empty uses the installed CLI's default; never reuse an API vendor's model.
    model: str = ""
    reasoning_effort: Literal["low", "medium", "high"] = "low"
    timeout_seconds: float = Field(180, ge=1, le=1800)
    max_concurrent: int = Field(2, ge=1, le=16)


class CursorConfig(BaseModel):
    executable: str = "cursor-p"
    # Flat catalog id. The bracket form is rejected when Cursor's parameterized
    # model catalog does not return within its 2 second limit.
    model: str = "grok-4.7-high-fast"
    timeout_seconds: float = Field(180, ge=1, le=1800)
    max_concurrent: int = Field(1, ge=1, le=4)


class LLMConfig(BaseModel):
    provider: Literal["api", "codex", "cursor"] = "api"
    codex: CodexConfig = Field(default_factory=CodexConfig)
    cursor: CursorConfig = Field(default_factory=CursorConfig)
    api_key: str = Field("", alias="api_key")
    base_url: str = Field("https://api.zhizengzeng.com/v1", alias="base_url")
    model: str = Field("gemini-2.5-flash", alias="model")
    judge_model: str = Field("gemini-2.5-flash", alias="judge_model")

    @property
    def uses_cli(self) -> bool:
        return self.provider in {"codex", "cursor"}

    @property
    def request_timeout(self) -> float:
        if self.provider == "cursor":
            return self.cursor.timeout_seconds
        if self.provider == "codex":
            return self.codex.timeout_seconds
        return 180

    @property
    def is_configured(self) -> bool:
        if self.provider in {"codex", "cursor"}:
            return True  # CLI authentication is checked when invoked.
        return bool(
            self.api_key.strip() and self.api_key != "YOUR_API_KEY" and self.base_url.strip() and self.model.strip()
        )


class GlossWorkerConfig(BaseModel):
    token: str = Field("", alias="token")
    lease_seconds: int = Field(900, ge=60, le=86400, alias="lease_seconds")


class ProcessingConfig(BaseModel):
    max_pages: int = Field(100, ge=1, le=500, alias="max_pages")
    max_upload_mb: int = Field(50, ge=1, le=128, alias="max_upload_mb")
    gloss_preparation: Literal["server", "remote_worker", "user_choice"] = Field(
        "server",
        alias="gloss_preparation",
    )
    max_concurrent: int = Field(3, ge=1, le=8, alias="max_concurrent")
    # Paragraph requests per document; independent of the concurrent document limit.
    translation_threads: int = Field(8, ge=1, le=16)
    max_pending: int = Field(8, ge=1, le=32)
    max_pending_per_user: int = Field(2, ge=1, le=8)
    preview_html: bool = Field(True, alias="preview_html")


class StorageConfig(BaseModel):
    cleanup_minutes: int = Field(30, alias="cleanup_minutes")
    temp_dir: str = Field("./backend/tmp", alias="temp_dir")
    # Empty means a reader-library directory inside temp_dir (which must be persisted).
    library_dir: str = ""


class LoggingConfig(BaseModel):
    level: str = Field("INFO", alias="level")
    file: str = Field("./backend/logs/app.log", alias="file")


class DatabaseConfig(BaseModel):
    url: str = Field("sqlite:///./backend/data/app.db", alias="url")


class SecurityConfig(BaseModel):
    secret_key: str = Field("CHANGE_THIS_TO_A_SECURE_SECRET_KEY", alias="secret_key")
    cors_origins: list[str] = Field(
        default=["http://localhost:5173", "http://127.0.0.1:5173"],
        alias="cors_origins",
    )
    # Public deployments should disable self-service registration and create
    # accounts via `python -m app.cli create-user`.
    allow_registration: bool = Field(True, alias="allow_registration")
    local_sync_enabled: bool = True
    daily_operations: int = Field(300, ge=1, le=10000)
    daily_imports: int = Field(20, ge=1, le=1000)
    max_users: int = Field(5, ge=1, le=100)
    min_free_disk_mb: int = Field(2048, ge=0)


class AgentConfig(BaseModel):
    enabled: bool = True
    api_keys: list[str] = Field(default=["CHANGE_ME"], alias="api_keys")
    draft_ttl_minutes: int = Field(30, alias="draft_ttl_minutes")
    mcp_mount_path: str = Field("/mcp", alias="mcp_mount_path")


class AppConfig(BaseModel):
    llm: LLMConfig
    processing: ProcessingConfig = ProcessingConfig()
    gloss_worker: GlossWorkerConfig = Field(default_factory=GlossWorkerConfig)
    storage: StorageConfig = StorageConfig()
    logging: LoggingConfig = LoggingConfig()
    database: DatabaseConfig = DatabaseConfig()
    security: SecurityConfig = SecurityConfig()
    agent: AgentConfig = AgentConfig()


def validate_security(config: AppConfig, app_env: str) -> None:
    """Warn (dev) or fail-fast (prod) on insecure default credentials.

    Production is opted into with ``APP_ENV=production``; in that mode a default
    JWT secret or agent API key aborts startup instead of merely logging.
    """
    is_prod = app_env.lower() in {"production", "prod"}

    if "CHANGE_THIS" in config.security.secret_key or len(config.security.secret_key.encode()) < 32:
        message = "security.secret_key must contain at least 32 bytes and must not be a placeholder. Set a strong secret key in config.yaml."
        if is_prod:
            raise RuntimeError(f"Refusing to start in production: {message}")
        logger.warning("SECURITY WARNING: %s", message)

    if config.agent.enabled and any("CHANGE_ME" in key or len(key) < 32 for key in config.agent.api_keys):
        message = "agent.api_keys still contains the default 'CHANGE_ME'."
        if is_prod:
            raise RuntimeError(f"Refusing to start in production: {message}")
        logger.warning("SECURITY WARNING: %s", message)

    if config.llm.provider == "api" and (not config.llm.api_key or config.llm.api_key == "YOUR_API_KEY"):
        logger.warning("LLM api_key is not configured. LLM features will fail.")


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    with path.open("r", encoding="utf-8") as file:
        data = yaml.safe_load(file) or {}
    return data


@lru_cache
def get_config() -> AppConfig:
    # Try multiple paths
    candidates = [
        Path(os.getenv("APP_CONFIG_PATH", "")),
        Path("config/config.yaml"),
        Path("backend/config/config.yaml"),
    ]

    config_path = None
    for path in candidates:
        if path and path.exists() and path.is_file():
            config_path = path
            break

    if not config_path:
        # Fallback to example if exists, or raise error
        if Path("config/config.example.yaml").exists():
            config_path = Path("config/config.example.yaml")
        elif Path("backend/config/config.example.yaml").exists():
            config_path = Path("backend/config/config.example.yaml")
        else:
            raise FileNotFoundError("Config file not found in config/config.yaml or backend/config/config.yaml")

    raw = _load_yaml(config_path)
    if provider := os.getenv("EASYPAPER_AI_PROVIDER"):
        raw.setdefault("llm", {})["provider"] = provider
    for variable, section, key in [
        ("EASYPAPER_SECRET_KEY", "security", "secret_key"),
        ("LLM_API_KEY", "llm", "api_key"),
        ("LLM_BASE_URL", "llm", "base_url"),
        ("LLM_MODEL", "llm", "model"),
    ]:
        if value := os.getenv(variable):
            raw.setdefault(section, {})[key] = value
    for variable, key in [
        ("EASYPAPER_CODEX_EXECUTABLE", "executable"),
        ("EASYPAPER_CODEX_MODEL", "model"),
        ("EASYPAPER_CODEX_REASONING_EFFORT", "reasoning_effort"),
        ("EASYPAPER_CODEX_TIMEOUT_SECONDS", "timeout_seconds"),
        ("EASYPAPER_CODEX_MAX_CONCURRENT", "max_concurrent"),
    ]:
        if value := os.getenv(variable):
            raw.setdefault("llm", {}).setdefault("codex", {})[key] = value
    for variable, key in [
        ("EASYPAPER_CURSOR_EXECUTABLE", "executable"),
        ("EASYPAPER_CURSOR_MODEL", "model"),
        ("EASYPAPER_CURSOR_TIMEOUT_SECONDS", "timeout_seconds"),
        ("EASYPAPER_CURSOR_MAX_CONCURRENT", "max_concurrent"),
    ]:
        if value := os.getenv(variable):
            raw.setdefault("llm", {}).setdefault("cursor", {})[key] = value
    # The server edition is invitation-only. Local filesystem access and shared
    # agent credentials are intentionally unavailable, even with an old config.
    if site := os.getenv("EASYPAPER_GLOSS_PREPARATION"):
        raw.setdefault("processing", {})["gloss_preparation"] = site
    if token := os.getenv("GLOSS_WORKER_TOKEN"):
        raw.setdefault("gloss_worker", {})["token"] = token
    if lease := os.getenv("EASYPAPER_GLOSS_WORKER_LEASE_SECONDS"):
        raw.setdefault("gloss_worker", {})["lease_seconds"] = lease
    if os.getenv("APP_ENV", "").lower() in {"production", "prod"}:
        raw.setdefault("security", {}).update(allow_registration=False, local_sync_enabled=False)
        raw.setdefault("agent", {}).update(enabled=False, api_keys=[])
    config = AppConfig(**raw)
    if config.processing.gloss_preparation in {"remote_worker", "user_choice"} and not config.gloss_worker.token.strip():
        if os.getenv("APP_ENV", "").lower() in {"production", "prod"} and config.processing.gloss_preparation == "remote_worker":
            raise RuntimeError(
                "Refusing to start in production: gloss_preparation=remote_worker requires gloss_worker.token "
                "(set GLOSS_WORKER_TOKEN or gloss_worker.token in config)."
            )
        logger.warning(
            "Gloss remote worker is enabled but gloss_worker.token is empty; remote jobs cannot be claimed."
        )

    # Validate critical settings at startup (fail-fast in production).
    validate_security(config, os.getenv("APP_ENV", "development"))

    return config
