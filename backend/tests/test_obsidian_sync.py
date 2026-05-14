from __future__ import annotations

import json
from pathlib import Path

from sqlmodel import Session, SQLModel, create_engine, select

from app.models.knowledge import Flashcard, KnowledgeEntity, ObsidianSyncMapping, PaperKnowledge, UserAnnotation
from app.models.task import Task, TaskStatus
from app.models.user import User
from app.services import obsidian_sync as obsidian_sync_module
from app.services.obsidian_markdown import normalize_entity_key, sanitize_markdown_name
from app.services.obsidian_sync import ObsidianSyncService, ObsidianVaultDetector


def _session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    return Session(engine)


def _create_user_and_paper(session: Session, *, paper_id: str = "paper-1") -> PaperKnowledge:
    user = User(id=1, email="user@example.com", hashed_password="hash")
    paper = PaperKnowledge(
        id=paper_id,
        user_id=1,
        task_id="task-1",
        title="Transformer/BERT: A Study",
        extraction_status="completed",
        knowledge_json=json.dumps(
            {
                "id": paper_id,
                "metadata": {
                    "title": "Transformer/BERT: A Study",
                    "authors": [{"name": "Alice"}, {"name": "Bob"}],
                    "abstract": "A paper about Transformer/BERT.",
                    "keywords": ["Transformer/BERT", "F1-score"],
                    "url": "https://arxiv.org/pdf/2602.09000",
                },
                "title": "Transformer/BERT: A Study",
                "summary": "This paper studies Transformer/BERT.",
                "structure": {
                    "sections": [
                        {"id": "sec-1", "title": "Introduction", "level": 1, "summary": "介绍研究问题。"},
                        {"id": "sec-2", "title": "Method", "level": 1, "summary": "介绍方法设计。"},
                    ]
                },
                "entities": [
                    {
                        "id": "entity-1",
                        "name": "Transformer/BERT",
                        "type": "method",
                        "description": "A model family.",
                    },
                    {
                        "id": "entity-2",
                        "name": "F1-score",
                        "type": "metric",
                        "description": "An evaluation metric.",
                    },
                ],
                "relationships": [
                    {
                        "id": "rel-1",
                        "source": "Transformer/BERT",
                        "target": "F1-score",
                        "type": "evaluates_on",
                        "description": "模型使用 F1-score 评估效果。",
                        "confidence": 0.8,
                    }
                ],
                "findings": [
                    {
                        "title": "Better retrieval",
                        "description": "Entity notes improve navigation.",
                        "evidence": "Section 3",
                    }
                ],
                "methods": [
                    {
                        "name": "Training Pipeline",
                        "description": "A staged training pipeline.",
                        "inputs": ["raw papers", "labels"],
                        "outputs": ["trained model"],
                    }
                ],
                "datasets": [
                    {
                        "name": "PaperBench",
                        "description": "A benchmark for papers.",
                        "usage": "evaluation",
                    }
                ],
                "flashcards": [
                    {
                        "id": "fc-json",
                        "front": "What does the paper study?",
                        "back": "Transformer/BERT.",
                        "tags": ["method"],
                        "difficulty": 2,
                    }
                ],
                "extracted_at": "2026-05-14T10:00:00",
                "extraction_model": "test-model",
            }
        ),
    )
    session.add(user)
    session.add(
        Task(
            task_id="task-1",
            filename="paper.pdf",
            user_id=1,
            status=TaskStatus.COMPLETED,
            summary_json=json.dumps(
                {
                    "one_liner": "用实体笔记改善论文阅读",
                    "estimated_minutes": 12,
                    "novelty_score": 4,
                    "story": {
                        "problem": "论文阅读后的知识容易丢失。",
                        "method": "把论文内容转成可链接的结构化笔记。",
                        "results": "用户可以在 Obsidian 中复用知识。",
                        "impact": "减少重复整理成本。",
                    },
                    "key_numbers": [{"value": "10x", "label": "样本效率提升", "context": "实验对比"}],
                    "pipeline": {"input": "PDF", "steps": ["提取", "链接"], "output": "笔记"},
                    "contributions": ["提出完整同步模板"],
                    "limitations": ["依赖已有提取结果"],
                    "keywords": [{"text": "Obsidian", "type": "tool", "importance": 0.9}],
                },
                ensure_ascii=False,
            ),
        )
    )
    session.add(paper)
    session.add(
        KnowledgeEntity(
            id="entity-1",
            paper_id=paper_id,
            user_id=1,
            name="Transformer/BERT",
            type="method",
            definition="A model family.",
        )
    )
    session.add(
        Flashcard(
            id="fc-db",
            paper_id=paper_id,
            user_id=1,
            front="数据库里的闪卡问题是什么？",
            back="它应该被同步到 Obsidian。",
            tags_json=json.dumps(["sync"], ensure_ascii=False),
            difficulty=3,
        )
    )
    session.add(
        UserAnnotation(
            id="ann-1",
            paper_id=paper_id,
            user_id=1,
            type="note",
            content="这是一条用户笔记。",
        )
    )
    session.commit()
    session.refresh(paper)
    return paper


def test_detects_obsidian_vaults_from_config(tmp_path: Path) -> None:
    vault = tmp_path / "Research Vault"
    vault.mkdir()
    config_path = tmp_path / "obsidian.json"
    config_path.write_text(
        json.dumps({"vaults": {"abc": {"path": str(vault), "open": True}}}),
        encoding="utf-8",
    )

    vaults = ObsidianVaultDetector(config_path=config_path).detect()

    assert len(vaults) == 1
    assert vaults[0].name == "Research Vault"
    assert vaults[0].path == str(vault)
    assert vaults[0].exists is True
    assert vaults[0].writable is True


def test_default_obsidian_config_paths_are_cross_platform(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(obsidian_sync_module.sys, "platform", "darwin")
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    assert ObsidianVaultDetector._default_config_path() == (
        tmp_path / "Library" / "Application Support" / "obsidian" / "obsidian.json"
    )

    monkeypatch.setattr(obsidian_sync_module.sys, "platform", "win32")
    monkeypatch.setenv("APPDATA", str(tmp_path / "AppData" / "Roaming"))
    assert ObsidianVaultDetector._default_config_path() == (
        tmp_path / "AppData" / "Roaming" / "obsidian" / "obsidian.json"
    )

    monkeypatch.setattr(obsidian_sync_module.sys, "platform", "linux")
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    assert ObsidianVaultDetector._default_config_path() == tmp_path / ".config" / "obsidian" / "obsidian.json"


def test_normalizes_entity_keys_and_sanitizes_names() -> None:
    assert normalize_entity_key("  BERT  ") == normalize_entity_key("bert")
    assert normalize_entity_key("ＢＥＲＴ") == normalize_entity_key("bert")
    assert normalize_entity_key("Attention Mechanism") != normalize_entity_key("注意力机制")

    assert sanitize_markdown_name("Transformer/BERT") == "Transformer_BERT"
    assert sanitize_markdown_name("F1-score") == "F1-score"
    assert sanitize_markdown_name("[CLS] token") == "CLS token"
    assert sanitize_markdown_name("model#1") == "model 1"


def test_sync_writes_paper_and_entity_notes_without_creating_notes_file(tmp_path: Path) -> None:
    session = _session()
    _create_user_and_paper(session)
    service = ObsidianSyncService(session)
    service.save_settings(user_id=1, vault_path=str(tmp_path), root_folder="EasyPaper")

    result = service.sync_paper(user_id=1, paper_id="paper-1")

    assert result["status"] == "synced"
    paper_note = tmp_path / "EasyPaper" / "Papers" / "Transformer_BERT A Study.md"
    entity_note = tmp_path / "EasyPaper" / "Entities" / "Transformer_BERT.md"
    user_note = tmp_path / "EasyPaper" / "Papers" / "Transformer_BERT A Study - Notes.md"
    assert paper_note.exists()
    assert entity_note.exists()
    assert not user_note.exists()

    paper_text = paper_note.read_text(encoding="utf-8")
    assert 'easypaper_id: "paper-1"' in paper_text
    assert "[[Transformer_BERT A Study - Notes]]" in paper_text
    assert "[[Transformer_BERT]]" in paper_text
    assert "Better retrieval" in paper_text

    mappings = session.exec(select(ObsidianSyncMapping)).all()
    assert {mapping.item_type for mapping in mappings} == {"paper", "entity"}
    assert all(mapping.content_hash for mapping in mappings)


def test_sync_paper_note_includes_detail_page_content(tmp_path: Path) -> None:
    session = _session()
    _create_user_and_paper(session)
    service = ObsidianSyncService(session)
    service.save_settings(user_id=1, vault_path=str(tmp_path), root_folder="EasyPaper")

    service.sync_paper(user_id=1, paper_id="paper-1")

    paper_note = tmp_path / "EasyPaper" / "Papers" / "Transformer_BERT A Study.md"
    text = paper_note.read_text(encoding="utf-8")
    assert "## AI 速览" in text
    assert "用实体笔记改善论文阅读" in text
    assert "### 问题" in text
    assert "论文阅读后的知识容易丢失。" in text
    assert "## 章节结构" in text
    assert "Introduction" in text
    assert "介绍研究问题。" in text
    assert "## 关系" in text
    assert "[[Transformer_BERT]] **evaluates_on** [[F1-score]]" in text
    assert "模型使用 F1-score 评估效果。" in text
    assert "## 闪卡" in text
    assert "数据库里的闪卡问题是什么？" in text
    assert "它应该被同步到 Obsidian。" in text
    assert "## 用户笔记" in text
    assert "这是一条用户笔记。" in text
    assert "输入：raw papers, labels" in text
    assert "输出：trained model" in text
    assert "用途：evaluation" in text
    assert "提取模型：test-model" in text


def test_sync_entity_note_includes_relationship_context(tmp_path: Path) -> None:
    session = _session()
    _create_user_and_paper(session)
    service = ObsidianSyncService(session)
    service.save_settings(user_id=1, vault_path=str(tmp_path), root_folder="EasyPaper")

    service.sync_paper(user_id=1, paper_id="paper-1")

    entity_note = tmp_path / "EasyPaper" / "Entities" / "Transformer_BERT.md"
    text = entity_note.read_text(encoding="utf-8")
    assert "## 相关关系" in text
    assert "[[Transformer_BERT]] **evaluates_on** [[F1-score]]" in text
    assert "模型使用 F1-score 评估效果。" in text


def test_sync_uses_frontmatter_fallback_when_mapping_path_is_missing(tmp_path: Path) -> None:
    session = _session()
    _create_user_and_paper(session)
    service = ObsidianSyncService(session)
    service.save_settings(user_id=1, vault_path=str(tmp_path), root_folder="EasyPaper")
    service.sync_paper(user_id=1, paper_id="paper-1")

    mapping = session.exec(
        select(ObsidianSyncMapping).where(ObsidianSyncMapping.item_type == "paper")
    ).one()
    original = tmp_path / mapping.relative_path
    renamed = original.with_name("Renamed Paper.md")
    original.rename(renamed)

    result = service.sync_paper(user_id=1, paper_id="paper-1")
    session.refresh(mapping)

    assert result["status"] == "synced"
    assert mapping.relative_path == str(renamed.relative_to(tmp_path))
    assert renamed.exists()
    assert not original.exists()


def test_filename_collision_adds_short_hash_suffix(tmp_path: Path) -> None:
    session = _session()
    paper = _create_user_and_paper(session)
    knowledge = json.loads(paper.knowledge_json or "{}")
    knowledge["entities"] = [
        {"id": "entity-a", "name": "Transformer/BERT", "type": "method", "description": "Slash"},
        {"id": "entity-b", "name": "Transformer_BERT", "type": "method", "description": "Underscore"},
    ]
    paper.knowledge_json = json.dumps(knowledge)
    session.add(paper)
    session.commit()

    service = ObsidianSyncService(session)
    service.save_settings(user_id=1, vault_path=str(tmp_path), root_folder="EasyPaper")

    result = service.sync_paper(user_id=1, paper_id="paper-1")

    assert result["status"] == "synced"
    entity_files = sorted((tmp_path / "EasyPaper" / "Entities").glob("Transformer_BERT*.md"))
    entity_file_names = {path.name for path in entity_files}
    assert len(entity_file_names) == 2
    assert "Transformer_BERT.md" in entity_file_names
    assert any(path.stem.startswith("Transformer_BERT-") for path in entity_files)
