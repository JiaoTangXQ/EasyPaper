"""知识库模型 - 可迁移的学术论文知识存储"""

from __future__ import annotations

from datetime import datetime

from sqlmodel import Field, SQLModel


class PaperKnowledge(SQLModel, table=True):
    """论文知识根表，knowledge_json 存储完整可迁移 JSON 文档。"""

    id: str = Field(primary_key=True)
    task_id: str | None = Field(default=None, index=True)
    user_id: int = Field(foreign_key="user.id", index=True)

    # 元数据（索引用）
    title: str = Field(default="")
    doi: str | None = Field(default=None, index=True)
    arxiv_id: str | None = Field(default=None)
    year: int | None = Field(default=None)
    venue: str | None = Field(default=None)

    # 完整可迁移 JSON 文档
    knowledge_json: str | None = Field(default=None)

    # 提取状态
    extraction_status: str = Field(default="pending")  # pending|extracting|completed|error
    extraction_model: str | None = Field(default=None)
    extraction_error: str | None = Field(default=None)

    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class KnowledgeEntity(SQLModel, table=True):
    """实体索引表，支持图谱查询和跨论文去重。"""

    id: str = Field(primary_key=True)
    paper_id: str = Field(foreign_key="paperknowledge.id", index=True)
    user_id: int = Field(foreign_key="user.id", index=True)

    name: str = Field(index=True)
    type: str  # method|model|dataset|metric|concept|task|person|organization
    aliases_json: str | None = Field(default=None)
    definition: str | None = Field(default=None)
    importance: float = Field(default=0.5)


class KnowledgeRelationship(SQLModel, table=True):
    """实体间关系索引表。"""

    id: str = Field(primary_key=True)
    paper_id: str = Field(foreign_key="paperknowledge.id", index=True)
    user_id: int = Field(foreign_key="user.id", index=True)

    source_entity_id: str = Field(index=True)
    target_entity_id: str = Field(index=True)
    type: str  # extends|uses|evaluates_on|outperforms|similar_to|contradicts|part_of|requires
    description: str | None = Field(default=None)
    confidence: float = Field(default=0.5)


class Flashcard(SQLModel, table=True):
    """间隔重复闪卡，SM-2 算法字段。"""

    id: str = Field(primary_key=True)
    paper_id: str = Field(foreign_key="paperknowledge.id", index=True)
    user_id: int = Field(foreign_key="user.id", index=True)

    front: str
    back: str
    tags_json: str | None = Field(default=None)
    difficulty: int = Field(default=3)

    # SM-2 SRS 字段
    interval_days: float = Field(default=1.0)
    ease_factor: float = Field(default=2.5)
    repetitions: int = Field(default=0)
    next_review: datetime = Field(default_factory=datetime.utcnow)
    last_review: datetime | None = Field(default=None)


class UserAnnotation(SQLModel, table=True):
    """用户笔记/标注。"""

    id: str = Field(primary_key=True)
    paper_id: str = Field(foreign_key="paperknowledge.id", index=True)
    user_id: int = Field(foreign_key="user.id", index=True)

    type: str  # note|highlight|question|todo
    content: str
    target_type: str = Field(default="paper")  # paper|section|entity|finding
    target_id: str = Field(default="")
    tags_json: str | None = Field(default=None)

    created_at: datetime = Field(default_factory=datetime.utcnow)


class UserSetting(SQLModel, table=True):
    """用户级运行时设置，避免把本地路径写入 config.yaml。"""

    id: str = Field(primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    key: str = Field(index=True)
    value_json: str
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class ObsidianSyncMapping(SQLModel, table=True):
    """EasyPaper 对应到 Obsidian 文件的映射。"""

    id: str = Field(primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    paper_id: str = Field(foreign_key="paperknowledge.id", index=True)
    item_type: str = Field(index=True)  # paper|entity
    item_id: str = Field(index=True)
    source_name: str
    normalized_key: str = Field(index=True)
    vault_path: str
    relative_path: str
    content_hash: str
    updated_at: datetime = Field(default_factory=datetime.utcnow)
