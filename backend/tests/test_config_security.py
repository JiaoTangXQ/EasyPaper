from __future__ import annotations

import pytest

from app.core.config import AppConfig, validate_security


def _config(secret: str | None = None, agent_keys: list[str] | None = None) -> AppConfig:
    raw: dict = {"llm": {"api_key": "real-key"}}
    if secret is not None:
        raw["security"] = {"secret_key": secret}
    if agent_keys is not None:
        raw["agent"] = {"api_keys": agent_keys}
    return AppConfig(**raw)


def test_default_secret_raises_in_production() -> None:
    cfg = _config()  # keeps the default CHANGE_THIS... secret
    with pytest.raises(RuntimeError):
        validate_security(cfg, "production")


def test_default_secret_only_warns_in_development() -> None:
    cfg = _config()
    validate_security(cfg, "development")  # must not raise


def test_default_agent_key_raises_in_production() -> None:
    cfg = _config(secret="a-strong-secret", agent_keys=["CHANGE_ME"])
    with pytest.raises(RuntimeError):
        validate_security(cfg, "production")


def test_strong_secrets_pass_in_production() -> None:
    cfg = _config(secret="a-strong-secret", agent_keys=["a-strong-agent-key"])
    validate_security(cfg, "production")  # must not raise
