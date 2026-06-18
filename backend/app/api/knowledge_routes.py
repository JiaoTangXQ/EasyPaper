"""知识库 API 路由"""

from __future__ import annotations

import io
import json
import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlmodel import Session, select

from ..core.db import engine
from ..models.knowledge import (
    Flashcard,
    KnowledgeEntity,
    KnowledgeRelationship,
    ObsidianSyncMapping,
    PaperKnowledge,
    UserAnnotation,
)
from ..models.task import Task, TaskStatus
from ..models.user import User
from ..services.background_tasks import create_tracked_task
from ..services.knowledge_export import to_bibtex
from ..services.knowledge_extractor import KnowledgeExtractor
from ..services.obsidian_sync import ObsidianSyncService, get_obsidian_sync_lock
from .deps import get_current_user

logger = logging.getLogger(__name__)


class FlashcardReviewRequest(BaseModel):
    quality: int


class CreateFlashcardRequest(BaseModel):
    paper_id: str
    front: str
    back: str
    tags: str | list[str] = ""
    difficulty: int = 3


class CreateAnnotationRequest(BaseModel):
    type: str
    content: str
    target_type: str = "paper"
    target_id: str = ""
    tags: str | list[str] = ""


class ObsidianSettingsRequest(BaseModel):
    vault_path: str
    root_folder: str = "EasyPaper"


def _normalize_tags(tags: str | list[str]) -> list[str]:
    if isinstance(tags, str):
        raw_tags = tags.split(",")
    else:
        raw_tags = tags
    return [tag.strip() for tag in raw_tags if tag.strip()]


def _ensure_extracting_paper(
    session: Session,
    task: Task,
    user_id: int,
    extraction_model: str,
) -> tuple[PaperKnowledge, bool]:
    """Claim a paper for extraction. Returns (paper, started), where ``started``
    is True only if this call transitioned it into "extracting". An extraction
    already in progress returns started=False so the caller doesn't launch a
    duplicate run (which would create duplicate entities/flashcards)."""
    existing = session.exec(select(PaperKnowledge).where(PaperKnowledge.task_id == task.task_id)).first()
    if existing:
        if existing.extraction_status == "extracting":
            return existing, False
        existing.extraction_status = "extracting"
        existing.extraction_error = None
        existing.extraction_model = extraction_model
        existing.updated_at = datetime.utcnow()
        session.add(existing)
        session.commit()
        session.refresh(existing)
        return existing, True

    paper = PaperKnowledge(
        id=f"pk_{uuid.uuid4().hex[:12]}",
        task_id=task.task_id,
        user_id=user_id,
        extraction_status="extracting",
        extraction_model=extraction_model,
    )
    session.add(paper)
    session.commit()
    session.refresh(paper)
    return paper, True


def create_knowledge_router(extractor: KnowledgeExtractor) -> APIRouter:
    router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])
    limiter = Limiter(key_func=get_remote_address)

    # ------------------------------------------------------------------
    # Obsidian 本地同步设置
    # ------------------------------------------------------------------

    @router.get("/settings/obsidian/vaults")
    async def detect_obsidian_vaults(
        user: User = Depends(get_current_user),  # noqa: ARG001
    ) -> dict[str, Any]:
        with Session(engine) as session:
            service = ObsidianSyncService(session)
            return {"vaults": service.detect_vaults()}

    @router.get("/settings/obsidian")
    async def get_obsidian_settings(
        user: User = Depends(get_current_user),
    ) -> dict[str, Any]:
        with Session(engine) as session:
            service = ObsidianSyncService(session)
            settings = service.get_settings(user.id)
        return settings or {"vault_path": "", "root_folder": "EasyPaper", "updated_at": None}

    @router.post("/settings/obsidian")
    async def save_obsidian_settings(
        payload: ObsidianSettingsRequest,
        user: User = Depends(get_current_user),
    ) -> dict[str, Any]:
        with Session(engine) as session:
            service = ObsidianSyncService(session)
            try:
                return service.save_settings(
                    user_id=user.id,
                    vault_path=payload.vault_path,
                    root_folder=payload.root_folder,
                )
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/settings/obsidian/test")
    async def test_obsidian_settings(
        payload: ObsidianSettingsRequest,
        user: User = Depends(get_current_user),  # noqa: ARG001
    ) -> dict[str, Any]:
        with Session(engine) as session:
            service = ObsidianSyncService(session)
            try:
                return service.test_write(vault_path=payload.vault_path, root_folder=payload.root_folder)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc

    # ------------------------------------------------------------------
    # 知识提取
    # ------------------------------------------------------------------

    @router.post("/extract/{task_id}")
    @limiter.limit("5/minute")
    async def extract_knowledge(
        request: Request,
        task_id: str,
        user: User = Depends(get_current_user),
    ) -> dict[str, str]:
        """对已完成的 task 触发知识提取。"""
        with Session(engine) as session:
            task = session.get(Task, task_id)
        if not task:
            raise HTTPException(status_code=404, detail="任务不存在")
        if task.user_id != user.id:
            raise HTTPException(status_code=403, detail="无权访问此任务")
        if task.status != TaskStatus.COMPLETED:
            raise HTTPException(status_code=400, detail="任务尚未完成，无法提取知识")

        # 检查是否已提取
        with Session(engine) as session:
            existing = session.exec(select(PaperKnowledge).where(PaperKnowledge.task_id == task_id)).first()
        if existing and existing.extraction_status == "completed":
            return {"paper_id": existing.id, "status": "already_completed"}

        # 读取原始 PDF
        if not task.original_pdf_path or not Path(task.original_pdf_path).exists():
            raise HTTPException(status_code=404, detail="原始 PDF 文件不存在或已过期")

        pdf_bytes = Path(task.original_pdf_path).read_bytes()
        with Session(engine) as session:
            paper, started = _ensure_extracting_paper(
                session=session,
                task=task,
                user_id=user.id,
                extraction_model=extractor.model,
            )
            paper_id = paper.id

        # 已有提取在进行中：直接返回，不再启动第二个提取任务（避免重复实体/闪卡）。
        if not started:
            return {"paper_id": paper_id, "status": "extracting"}

        # 异步执行提取
        async def _do_extract():
            try:
                await extractor.extract(pdf_bytes, task_id, user.id, paper_id)
            except Exception:
                logger.exception("Knowledge extraction failed for task %s", task_id)

        create_tracked_task(_do_extract())

        return {"paper_id": paper_id, "status": "extracting"}

    @router.get("/extract/status/{paper_id}")
    async def extraction_status(
        paper_id: str,
        user: User = Depends(get_current_user),
    ) -> dict[str, Any]:
        """查询知识提取状态。"""
        with Session(engine) as session:
            paper = session.get(PaperKnowledge, paper_id)
        if not paper:
            raise HTTPException(status_code=404, detail="论文不存在")
        if paper.user_id != user.id:
            raise HTTPException(status_code=403, detail="无权访问")
        return {
            "paper_id": paper.id,
            "status": paper.extraction_status,
            "error": paper.extraction_error,
            "title": paper.title,
        }

    # ------------------------------------------------------------------
    # 论文知识 CRUD
    # ------------------------------------------------------------------

    @router.get("/papers")
    async def list_papers(
        user: User = Depends(get_current_user),
    ) -> list[dict[str, Any]]:
        """列出用户知识库中的所有论文。"""
        with Session(engine) as session:
            papers = session.exec(
                select(PaperKnowledge)
                .where(PaperKnowledge.user_id == user.id)
                .order_by(PaperKnowledge.created_at.desc())
            ).all()
        return [
            {
                "id": p.id,
                "task_id": p.task_id,
                "title": p.title,
                "doi": p.doi,
                "year": p.year,
                "venue": p.venue,
                "extraction_status": p.extraction_status,
                "created_at": p.created_at.isoformat() if p.created_at else None,
            }
            for p in papers
        ]

    @router.get("/papers/{paper_id}")
    async def get_paper(
        paper_id: str,
        user: User = Depends(get_current_user),
    ) -> dict[str, Any]:
        """获取单篇论文的完整知识 JSON。"""
        with Session(engine) as session:
            paper = session.get(PaperKnowledge, paper_id)
            if not paper:
                raise HTTPException(status_code=404, detail="论文不存在")
            if paper.user_id != user.id:
                raise HTTPException(status_code=403, detail="无权访问")
            if paper.knowledge_json:
                data = json.loads(paper.knowledge_json)
                cards = session.exec(
                    select(Flashcard).where(Flashcard.paper_id == paper_id).where(Flashcard.user_id == user.id)
                ).all()
                annotations = session.exec(
                    select(UserAnnotation)
                    .where(UserAnnotation.paper_id == paper_id)
                    .where(UserAnnotation.user_id == user.id)
                    .order_by(UserAnnotation.created_at.desc())
                ).all()
                data["flashcards"] = [_flashcard_to_dict(card) for card in cards]
                data["annotations"] = [_annotation_to_dict(annotation) for annotation in annotations]
                return data
            return {"id": paper.id, "title": paper.title, "extraction_status": paper.extraction_status}

    @router.post("/papers/{paper_id}/sync/obsidian")
    async def sync_paper_to_obsidian(
        paper_id: str,
        user: User = Depends(get_current_user),
    ) -> dict[str, Any]:
        """同步单篇论文知识到本地 Obsidian vault。"""
        lock = get_obsidian_sync_lock(user.id, paper_id)
        if not lock.acquire(blocking=False):
            raise HTTPException(status_code=409, detail="该论文正在同步到 Obsidian")

        try:
            with Session(engine) as session:
                service = ObsidianSyncService(session)
                try:
                    return service.sync_paper(user_id=user.id, paper_id=paper_id)
                except LookupError as exc:
                    raise HTTPException(status_code=404, detail=str(exc)) from exc
                except ValueError as exc:
                    raise HTTPException(status_code=400, detail=str(exc)) from exc
        finally:
            lock.release()

    @router.delete("/papers/{paper_id}")
    async def delete_paper(
        paper_id: str,
        user: User = Depends(get_current_user),
    ) -> dict[str, str]:
        """删除论文及其所有知识数据。"""
        with Session(engine) as session:
            paper = session.get(PaperKnowledge, paper_id)
            if not paper:
                raise HTTPException(status_code=404, detail="论文不存在")
            if paper.user_id != user.id:
                raise HTTPException(status_code=403, detail="无权访问")

            # 删除关联数据
            for model in (Flashcard, UserAnnotation, KnowledgeRelationship, KnowledgeEntity, ObsidianSyncMapping):
                items = session.exec(select(model).where(model.paper_id == paper_id)).all()
                for item in items:
                    session.delete(item)

            session.delete(paper)
            session.commit()
        return {"status": "deleted"}

    # ------------------------------------------------------------------
    # 知识图谱
    # ------------------------------------------------------------------

    @router.get("/graph")
    async def get_graph(
        user: User = Depends(get_current_user),
    ) -> dict[str, Any]:
        """获取用户的知识图谱（所有实体和关系）。"""
        with Session(engine) as session:
            entities = session.exec(select(KnowledgeEntity).where(KnowledgeEntity.user_id == user.id)).all()
            relationships = session.exec(
                select(KnowledgeRelationship).where(KnowledgeRelationship.user_id == user.id)
            ).all()

        nodes = [
            {
                "id": e.id,
                "name": e.name,
                "type": e.type,
                "definition": e.definition,
                "importance": e.importance,
                "paper_id": e.paper_id,
            }
            for e in entities
        ]
        edges = [
            {
                "id": r.id,
                "source": r.source_entity_id,
                "target": r.target_entity_id,
                "type": r.type,
                "description": r.description,
                "confidence": r.confidence,
            }
            for r in relationships
        ]
        return {"nodes": nodes, "edges": edges}

    @router.get("/graph/search")
    async def search_entities(
        q: str,
        user: User = Depends(get_current_user),
    ) -> list[dict[str, Any]]:
        """搜索实体。"""
        with Session(engine) as session:
            entities = session.exec(
                select(KnowledgeEntity)
                .where(KnowledgeEntity.user_id == user.id)
                .where(KnowledgeEntity.name.contains(q))
            ).all()
        return [
            {
                "id": e.id,
                "name": e.name,
                "type": e.type,
                "definition": e.definition,
                "paper_id": e.paper_id,
            }
            for e in entities
        ]

    # ------------------------------------------------------------------
    # 闪卡
    # ------------------------------------------------------------------

    @router.get("/flashcards")
    async def list_flashcards(
        user: User = Depends(get_current_user),
    ) -> list[dict[str, Any]]:
        """列出用户的所有闪卡。"""
        with Session(engine) as session:
            cards = session.exec(select(Flashcard).where(Flashcard.user_id == user.id)).all()
        return [_flashcard_to_dict(c) for c in cards]

    @router.get("/flashcards/due")
    async def get_due_flashcards(
        user: User = Depends(get_current_user),
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """获取到期需要复习的闪卡。"""
        from datetime import datetime

        with Session(engine) as session:
            cards = session.exec(
                select(Flashcard)
                .where(Flashcard.user_id == user.id)
                .where(Flashcard.next_review <= datetime.utcnow())
                .order_by(Flashcard.next_review)
                .limit(limit)
            ).all()
        return [_flashcard_to_dict(c) for c in cards]

    @router.post("/flashcards/{card_id}/review")
    async def review_flashcard(
        card_id: str,
        payload: FlashcardReviewRequest,
        user: User = Depends(get_current_user),
    ) -> dict[str, Any]:
        """提交闪卡复习结果 (quality: 0-5)。"""
        quality = payload.quality
        if not 0 <= quality <= 5:
            raise HTTPException(status_code=400, detail="quality must be 0-5")

        from ..services.srs_engine import SRSEngine

        with Session(engine) as session:
            card = session.get(Flashcard, card_id)
            if not card:
                raise HTTPException(status_code=404, detail="闪卡不存在")
            if card.user_id != user.id:
                raise HTTPException(status_code=403, detail="无权访问")

            SRSEngine.review(card, quality)
            session.add(card)
            session.commit()
            session.refresh(card)

        return _flashcard_to_dict(card)

    @router.post("/flashcards")
    async def create_flashcard(
        payload: CreateFlashcardRequest,
        user: User = Depends(get_current_user),
    ) -> dict[str, Any]:
        """手动创建闪卡。"""
        import uuid
        from datetime import datetime

        with Session(engine) as session:
            paper = session.get(PaperKnowledge, payload.paper_id)
            if not paper or paper.user_id != user.id:
                raise HTTPException(status_code=404, detail="论文不存在")

            card = Flashcard(
                id=f"fc_{uuid.uuid4().hex[:12]}",
                paper_id=payload.paper_id,
                user_id=user.id,
                front=payload.front,
                back=payload.back,
                tags_json=json.dumps(_normalize_tags(payload.tags), ensure_ascii=False),
                difficulty=payload.difficulty,
                next_review=datetime.utcnow(),
            )
            session.add(card)
            session.commit()
            session.refresh(card)

        return _flashcard_to_dict(card)

    @router.delete("/flashcards/{card_id}")
    async def delete_flashcard(
        card_id: str,
        user: User = Depends(get_current_user),
    ) -> dict[str, str]:
        with Session(engine) as session:
            card = session.get(Flashcard, card_id)
            if not card:
                raise HTTPException(status_code=404, detail="闪卡不存在")
            if card.user_id != user.id:
                raise HTTPException(status_code=403, detail="无权访问")
            session.delete(card)
            session.commit()
        return {"status": "deleted"}

    # ------------------------------------------------------------------
    # 笔记 / 标注
    # ------------------------------------------------------------------

    @router.get("/papers/{paper_id}/annotations")
    async def list_annotations(
        paper_id: str,
        user: User = Depends(get_current_user),
    ) -> list[dict[str, Any]]:
        with Session(engine) as session:
            anns = session.exec(
                select(UserAnnotation)
                .where(UserAnnotation.paper_id == paper_id)
                .where(UserAnnotation.user_id == user.id)
                .order_by(UserAnnotation.created_at.desc())
            ).all()
        return [
            {
                "id": a.id,
                "type": a.type,
                "content": a.content,
                "target_type": a.target_type,
                "target_id": a.target_id,
                "tags": json.loads(a.tags_json) if a.tags_json else [],
                "created_at": a.created_at.isoformat() if a.created_at else None,
            }
            for a in anns
        ]

    @router.post("/papers/{paper_id}/annotations")
    async def create_annotation(
        paper_id: str,
        payload: CreateAnnotationRequest,
        user: User = Depends(get_current_user),
    ) -> dict[str, Any]:
        import uuid
        from datetime import datetime

        with Session(engine) as session:
            paper = session.get(PaperKnowledge, paper_id)
            if not paper or paper.user_id != user.id:
                raise HTTPException(status_code=404, detail="论文不存在")

            ann = UserAnnotation(
                id=f"ann_{uuid.uuid4().hex[:12]}",
                paper_id=paper_id,
                user_id=user.id,
                type=payload.type,
                content=payload.content,
                target_type=payload.target_type,
                target_id=payload.target_id,
                tags_json=json.dumps(_normalize_tags(payload.tags), ensure_ascii=False),
                created_at=datetime.utcnow(),
            )
            session.add(ann)
            session.commit()
            session.refresh(ann)

        return {
            "id": ann.id,
            "type": ann.type,
            "content": ann.content,
            "created_at": ann.created_at.isoformat() if ann.created_at else None,
        }

    @router.delete("/annotations/{ann_id}")
    async def delete_annotation(
        ann_id: str,
        user: User = Depends(get_current_user),
    ) -> dict[str, str]:
        with Session(engine) as session:
            ann = session.get(UserAnnotation, ann_id)
            if not ann:
                raise HTTPException(status_code=404, detail="笔记不存在")
            if ann.user_id != user.id:
                raise HTTPException(status_code=403, detail="无权访问")
            session.delete(ann)
            session.commit()
        return {"status": "deleted"}

    # ------------------------------------------------------------------
    # 导出
    # ------------------------------------------------------------------

    @router.get("/export/json")
    async def export_full_json(
        user: User = Depends(get_current_user),
    ) -> dict[str, Any]:
        """导出完整知识库为可迁移 JSON。"""
        from datetime import datetime

        with Session(engine) as session:
            papers = session.exec(
                select(PaperKnowledge)
                .where(PaperKnowledge.user_id == user.id)
                .where(PaperKnowledge.extraction_status == "completed")
            ).all()

        papers_json = []
        for p in papers:
            if p.knowledge_json:
                papers_json.append(json.loads(p.knowledge_json))

        # 构建全局实体去重
        global_entities: dict[str, dict] = {}
        for pj in papers_json:
            for ent in pj.get("entities", []):
                key = ent.get("name", "").lower().strip()
                if key and key not in global_entities:
                    global_entities[key] = ent

        return {
            "schema_version": "1.0.0",
            "exported_at": datetime.utcnow().isoformat(),
            "papers": papers_json,
            "global_entities": list(global_entities.values()),
            "global_relationships": [],
        }

    @router.get("/export/paper/{paper_id}")
    async def export_paper_json(
        paper_id: str,
        user: User = Depends(get_current_user),
    ) -> dict[str, Any]:
        """导出单篇论文的 .epaper.json。"""
        with Session(engine) as session:
            paper = session.get(PaperKnowledge, paper_id)
        if not paper:
            raise HTTPException(status_code=404, detail="论文不存在")
        if paper.user_id != user.id:
            raise HTTPException(status_code=403, detail="无权访问")
        if not paper.knowledge_json:
            raise HTTPException(status_code=400, detail="知识尚未提取")
        return json.loads(paper.knowledge_json)

    @router.get("/export/bibtex")
    async def export_bibtex(
        user: User = Depends(get_current_user),
    ) -> str:
        """导出所有论文的 BibTeX 引用。"""
        from fastapi.responses import PlainTextResponse

        with Session(engine) as session:
            papers = session.exec(
                select(PaperKnowledge)
                .where(PaperKnowledge.user_id == user.id)
                .where(PaperKnowledge.extraction_status == "completed")
            ).all()

        bib_entries = []
        for p in papers:
            if not p.knowledge_json:
                continue
            kj = json.loads(p.knowledge_json)
            metadata = kj.get("metadata", {})
            bibtex = metadata.get("bibtex")
            if bibtex:
                bib_entries.append(bibtex)
            else:
                bib_entries.append(to_bibtex(metadata, p.id.replace("pk_", "")))

        return PlainTextResponse(
            content="\n".join(bib_entries),
            media_type="text/plain",
            headers={"Content-Disposition": "attachment; filename=easypaper_references.bib"},
        )

    @router.get("/export/obsidian")
    async def export_obsidian(
        user: User = Depends(get_current_user),
    ):
        """导出为 Obsidian vault (ZIP)。"""
        from fastapi.responses import Response

        from ..services.knowledge_export import KnowledgeExporter

        papers_json = _get_completed_papers_json(user.id)
        zip_bytes = KnowledgeExporter.export_obsidian_vault(papers_json)
        return Response(
            content=zip_bytes,
            media_type="application/zip",
            headers={"Content-Disposition": "attachment; filename=easypaper_vault.zip"},
        )

    @router.get("/export/csv")
    async def export_csv(
        user: User = Depends(get_current_user),
    ):
        """导出实体和关系为 CSV (ZIP)。"""
        import zipfile as zf_mod

        from fastapi.responses import Response

        from ..services.knowledge_export import KnowledgeExporter

        papers_json = _get_completed_papers_json(user.id)
        ent_csv, rel_csv = KnowledgeExporter.export_csv(papers_json)

        buf = io.BytesIO()
        with zf_mod.ZipFile(buf, "w", zf_mod.ZIP_DEFLATED) as zf:
            zf.writestr("entities.csv", ent_csv)
            zf.writestr("relationships.csv", rel_csv)

        return Response(
            content=buf.getvalue(),
            media_type="application/zip",
            headers={"Content-Disposition": "attachment; filename=easypaper_csv.zip"},
        )

    @router.get("/export/csl-json")
    async def export_csl_json(
        user: User = Depends(get_current_user),
    ):
        """导出为 CSL-JSON 格式（Zotero/Mendeley 兼容）。"""
        from fastapi.responses import Response

        from ..services.knowledge_export import KnowledgeExporter

        papers_json = _get_completed_papers_json(user.id)
        csl_bytes = KnowledgeExporter.export_csl_json(papers_json)
        return Response(
            content=csl_bytes,
            media_type="application/json",
            headers={"Content-Disposition": "attachment; filename=easypaper_references.json"},
        )

    # ------------------------------------------------------------------
    # 内部辅助函数
    # ------------------------------------------------------------------

    def _get_completed_papers_json(user_id: int) -> list[dict]:
        """获取用户所有已完成提取的论文知识 JSON。"""
        with Session(engine) as session:
            papers = session.exec(
                select(PaperKnowledge)
                .where(PaperKnowledge.user_id == user_id)
                .where(PaperKnowledge.extraction_status == "completed")
            ).all()
        return [json.loads(p.knowledge_json) for p in papers if p.knowledge_json]

    # ------------------------------------------------------------------
    # 辅助函数
    # ------------------------------------------------------------------

    def _flashcard_to_dict(card: Flashcard) -> dict[str, Any]:
        return {
            "id": card.id,
            "paper_id": card.paper_id,
            "front": card.front,
            "back": card.back,
            "tags": json.loads(card.tags_json) if card.tags_json else [],
            "difficulty": card.difficulty,
            "srs": {
                "interval_days": card.interval_days,
                "ease_factor": card.ease_factor,
                "repetitions": card.repetitions,
                "next_review": card.next_review.isoformat() if card.next_review else None,
                "last_review": card.last_review.isoformat() if card.last_review else None,
            },
        }

    def _annotation_to_dict(annotation: UserAnnotation) -> dict[str, Any]:
        return {
            "id": annotation.id,
            "type": annotation.type,
            "content": annotation.content,
            "target_type": annotation.target_type,
            "target_id": annotation.target_id,
            "tags": json.loads(annotation.tags_json) if annotation.tags_json else [],
            "created_at": annotation.created_at.isoformat() if annotation.created_at else None,
        }

    return router
