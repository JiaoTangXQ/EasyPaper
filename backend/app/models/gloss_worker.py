"""Remote gloss preparation jobs claimed by a trusted local worker."""

from __future__ import annotations

from datetime import datetime

from sqlmodel import Field, SQLModel


class GlossWorkerJob(SQLModel, table=True):
    """One gloss import task delegated to an external worker process."""

    id: str = Field(primary_key=True)
    task_id: str = Field(index=True)
    document_id: str = Field(index=True)
    user_id: int = Field(index=True)
    status: str = Field(default="queued", index=True)  # queued | claimed | completed | failed
    claim_token: str | None = Field(default=None, index=True)
    claimed_until: datetime | None = None
    worker_label: str | None = None
    progress_done: int = 0
    progress_total: int = 0
    error: str = ""
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
