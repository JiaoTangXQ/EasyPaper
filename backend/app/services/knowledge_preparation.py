"""Where knowledge extraction LLM work runs (server vs trusted local worker)."""

from __future__ import annotations

from typing import Literal

from ..core.config import AppConfig

KnowledgePreparationMode = Literal["server", "remote_worker"]


def resolve_knowledge_preparation(config: AppConfig) -> KnowledgePreparationMode:
    site = config.processing.knowledge_preparation
    if site == "remote_worker":
        return "remote_worker"
    return "server"


def remote_worker_ready(config: AppConfig) -> bool:
    return bool(config.knowledge_worker.token.strip())
