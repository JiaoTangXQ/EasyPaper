"""Run gloss and knowledge remote workers in one process (optional Mac setup)."""

from __future__ import annotations

import asyncio
import logging

from ..gloss_worker.runner import GlossWorkerRunner
from ..knowledge_worker.runner import KnowledgeWorkerRunner

logger = logging.getLogger(__name__)


async def run_local_workers(
    *,
    base_url: str,
    gloss_token: str,
    knowledge_token: str,
    gloss_label: str,
    knowledge_label: str,
    poll_seconds: float,
    knowledge_enabled: bool,
) -> None:
    gloss = GlossWorkerRunner(
        base_url=base_url,
        token=gloss_token,
        worker_label=gloss_label,
        poll_seconds=poll_seconds,
    )
    tasks = [asyncio.create_task(gloss.run_forever(), name="gloss-worker")]
    if knowledge_enabled and knowledge_token.strip():
        knowledge = KnowledgeWorkerRunner(
            base_url=base_url,
            token=knowledge_token,
            worker_label=knowledge_label,
            poll_seconds=poll_seconds,
        )
        tasks.append(asyncio.create_task(knowledge.run_forever(), name="knowledge-worker"))
    elif knowledge_enabled:
        logger.warning("Knowledge worker enabled but token is empty; only gloss worker will run.")
    await asyncio.gather(*tasks)


def run_local_worker(
    *,
    base_url: str,
    gloss_token: str,
    knowledge_token: str,
    gloss_label: str,
    knowledge_label: str,
    poll_seconds: float,
    knowledge_enabled: bool,
) -> int:
    try:
        asyncio.run(
            run_local_workers(
                base_url=base_url,
                gloss_token=gloss_token,
                knowledge_token=knowledge_token,
                gloss_label=gloss_label,
                knowledge_label=knowledge_label,
                poll_seconds=poll_seconds,
                knowledge_enabled=knowledge_enabled,
            )
        )
    except KeyboardInterrupt:
        return 0
    return 0
