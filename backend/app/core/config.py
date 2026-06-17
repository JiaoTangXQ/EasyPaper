from __future__ import annotations

import logging
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class LLMConfig(BaseModel):
    api_key: str = Field(..., alias="api_key")
    base_url: str = Field("https://api.zhizengzeng.com/v1", alias="base_url")
    model: str = Field("gemini-2.5-flash", alias="model")
    judge_model: str = Field("gemini-2.5-flash", alias="judge_model")


class ProcessingConfig(BaseModel):
    max_pages: int = Field(100, alias="max_pages")
    max_upload_mb: int = Field(50, alias="max_upload_mb")
    max_concurrent: int = Field(3, alias="max_concurrent")
    preview_html: bool = Field(True, alias="preview_html")


class StorageConfig(BaseModel):
    cleanup_minutes: int = Field(30, alias="cleanup_minutes")
    temp_dir: str = Field("./backend/tmp", alias="temp_dir")


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


class AgentConfig(BaseModel):
    api_keys: list[str] = Field(default=["CHANGE_ME"], alias="api_keys")
    draft_ttl_minutes: int = Field(30, alias="draft_ttl_minutes")
    mcp_mount_path: str = Field("/mcp", alias="mcp_mount_path")


class AppConfig(BaseModel):
    llm: LLMConfig
    processing: ProcessingConfig = ProcessingConfig()
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

    if "CHANGE_THIS" in config.security.secret_key:
        message = "security.secret_key is still the default value. Set a strong secret key in config.yaml."
        if is_prod:
            raise RuntimeError(f"Refusing to start in production: {message}")
        logger.warning("SECURITY WARNING: %s", message)

    if any("CHANGE_ME" in key for key in config.agent.api_keys):
        message = "agent.api_keys still contains the default 'CHANGE_ME'."
        if is_prod:
            raise RuntimeError(f"Refusing to start in production: {message}")
        logger.warning("SECURITY WARNING: %s", message)

    if not config.llm.api_key or config.llm.api_key == "YOUR_API_KEY":
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
    config = AppConfig(**raw)

    # Validate critical settings at startup (fail-fast in production).
    validate_security(config, os.getenv("APP_ENV", "development"))

    return config
