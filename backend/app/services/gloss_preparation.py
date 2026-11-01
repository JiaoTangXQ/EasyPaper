"""Resolve which gloss preparation pipeline applies for a user."""

from __future__ import annotations

from typing import Any, Literal

from ..core.config import AppConfig

GlossPreparationMode = Literal["server", "remote_worker"]


def resolve_gloss_preparation(config: AppConfig, user_preferences: dict[str, Any] | None) -> GlossPreparationMode:
    site = config.processing.gloss_preparation
    if site == "user_choice":
        gloss = (user_preferences or {}).get("reading", {})
        if isinstance(gloss, dict):
            section = gloss.get("gloss")
            if isinstance(section, dict) and section.get("preparation") == "remote_worker":
                return "remote_worker"
        return "server"
    if site == "remote_worker":
        return "remote_worker"
    return "server"


def remote_worker_ready(config: AppConfig) -> bool:
    return bool(config.gloss_worker.token.strip())
