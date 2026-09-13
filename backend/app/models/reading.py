"""Persistent source anchors and per-reader state, separate from PDF export jobs."""

from datetime import datetime

from sqlmodel import Field, SQLModel


class ReadingDocument(SQLModel, table=True):
    task_id: str = Field(primary_key=True)
    document_json: str
    schema_version: int = 1
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ReadingAid(SQLModel, table=True):
    id: str = Field(primary_key=True)
    task_id: str = Field(index=True)
    block_id: str = Field(index=True)
    content_json: str
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ReadingState(SQLModel, table=True):
    id: str = Field(primary_key=True)
    task_id: str = Field(index=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    block_id: str = ""
    offset: float = 0
    mode: str = "chinese"
    font_size: int = 18
    understood_json: str = "[]"
    bookmarked_terms_json: str = "[]"
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class ReaderDocument(SQLModel, table=True):
    """A user's immutable source, independent of transient translation tasks."""

    id: str = Field(primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    fingerprint: str = Field(index=True)
    title: str
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ReaderTaskLink(SQLModel, table=True):
    task_id: str = Field(primary_key=True)
    document_id: str = Field(foreign_key="readerdocument.id", index=True)


class ReaderVersion(SQLModel, table=True):
    id: str = Field(primary_key=True)
    document_id: str = Field(foreign_key="readerdocument.id", index=True)
    kind: str = Field(index=True)
    fingerprint: str
    path: str
    index_json: str
    mappings_json: str = "[]"
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ReaderBuild(SQLModel, table=True):
    id: str = Field(primary_key=True)
    document_id: str = Field(foreign_key="readerdocument.id", index=True)
    kind: str
    status: str = "running"
    error: str = ""
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class ReaderAnnotation(SQLModel, table=True):
    id: str = Field(primary_key=True)
    document_id: str = Field(foreign_key="readerdocument.id", index=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    source_version_id: str = Field(foreign_key="readerversion.id")
    data_json: str
    quote: str = ""
    anchors_json: str = "[]"
    projections_json: str = "{}"
    alignment_status: str = "pending"
    alignment_message: str = "正在匹配其他版本"
    revision: int = 1
    geometry_revision: int = 1
    deleted: bool = False
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class ReaderOperation(SQLModel, table=True):
    """Durable idempotency receipt and recoverable annotation history."""

    id: str = Field(primary_key=True)
    document_id: str = Field(foreign_key="readerdocument.id", index=True)
    annotation_id: str = Field(index=True)
    result_json: str
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ReaderPhraseAlignment(SQLModel, table=True):
    """Reusable phrase correspondence for immutable, user-owned PDF text."""

    id: str = Field(primary_key=True)
    document_id: str = Field(foreign_key="readerdocument.id", index=True)
    result_json: str
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class ReaderAlignmentRetry(SQLModel, table=True):
    """Retry budget survives closing the reader and restarting the service."""

    annotation_id: str = Field(primary_key=True)
    signature: str
    attempts: int = 0
    next_attempt_at: datetime | None = None
