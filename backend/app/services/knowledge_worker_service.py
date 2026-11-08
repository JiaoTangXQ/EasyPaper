"""Queue, lease, and finalize knowledge extraction on a trusted local worker."""

from __future__ import annotations

import hashlib
import json
import logging
import secrets
import zipfile
from datetime import datetime, timedelta
from io import BytesIO
from pathlib import Path
from typing import Any

from fastapi import HTTPException
from sqlmodel import Session, select

from ..core.config import AppConfig
from ..models.knowledge import PaperKnowledge
from ..models.knowledge_worker import KnowledgeWorkerJob
from ..models.task import Task
from ..services.knowledge_extractor import KnowledgeExtractor

logger = logging.getLogger(__name__)

MAX_KNOWLEDGE_BYTES = 32 * 1024 * 1024


class KnowledgeWorkerService:
    def __init__(self, config: AppConfig, engine, extractor: KnowledgeExtractor):
        self.config = config
        self.engine = engine
        self.extractor = extractor

    def job_id(self, paper_id: str) -> str:
        return f"{paper_id}:knowledge"

    def enqueue(self, *, task_id: str, paper_id: str, user_id: int) -> KnowledgeWorkerJob:
        jid = self.job_id(paper_id)
        now = datetime.utcnow()
        with Session(self.engine) as session:
            paper = session.get(PaperKnowledge, paper_id)
            if not paper:
                raise HTTPException(404, "知识记录不存在")
            job = session.get(KnowledgeWorkerJob, jid)
            if not job:
                job = KnowledgeWorkerJob(
                    id=jid,
                    task_id=task_id,
                    paper_id=paper_id,
                    user_id=user_id,
                )
            if job.status == "claimed":
                raise HTTPException(409, "知识整理已被本机处理器领取，请稍后再试。")
            job.status = "queued"
            job.claim_token = None
            job.claimed_until = None
            job.worker_label = None
            job.progress_done = 0
            job.progress_total = 0
            job.error = ""
            job.updated_at = now
            paper.extraction_status = "extracting"
            paper.extraction_error = None
            paper.updated_at = now
            session.add(paper)
            session.add(job)
            session.commit()
            session.refresh(job)
            return job

    def release_expired_claims(self) -> int:
        now = datetime.utcnow()
        released = 0
        with Session(self.engine) as session:
            jobs = session.exec(
                select(KnowledgeWorkerJob).where(
                    KnowledgeWorkerJob.status == "claimed",
                    KnowledgeWorkerJob.claimed_until.isnot(None),
                    KnowledgeWorkerJob.claimed_until < now,
                )
            ).all()
            for job in jobs:
                job.status = "queued"
                job.claim_token = None
                job.claimed_until = None
                job.worker_label = None
                job.updated_at = now
                session.add(job)
                released += 1
            if released:
                session.commit()
        return released

    def claim_next(self, *, worker_label: str) -> dict[str, Any] | None:
        self.release_expired_claims()
        lease = max(120, int(self.config.knowledge_worker.lease_seconds))
        token = secrets.token_urlsafe(32)
        until = datetime.utcnow() + timedelta(seconds=lease)
        with Session(self.engine) as session:
            query = (
                select(KnowledgeWorkerJob)
                .where(KnowledgeWorkerJob.status == "queued")
                .order_by(KnowledgeWorkerJob.created_at)
            )
            if self.engine.dialect.name == "postgresql":
                job = session.exec(query.with_for_update(skip_locked=True)).first()
            else:
                job = session.exec(query).first()
            if not job:
                return None
            paper = session.get(PaperKnowledge, job.paper_id)
            if not paper or paper.extraction_status not in {"extracting", "pending", "error"}:
                job.status = "failed"
                job.error = "论文状态不一致，请用户在网页上重试。"
                job.updated_at = datetime.utcnow()
                session.add(job)
                session.commit()
                return None
            job.status = "claimed"
            job.claim_token = token
            job.claimed_until = until
            job.worker_label = (worker_label or "worker")[:120]
            job.updated_at = datetime.utcnow()
            paper.extraction_status = "extracting"
            paper.extraction_error = None
            paper.updated_at = job.updated_at
            session.add(paper)
            session.add(job)
            session.commit()
            return self._job_payload(session, job)

    def _job_payload(self, session: Session, job: KnowledgeWorkerJob) -> dict[str, Any]:
        task = session.get(Task, job.task_id)
        pdf_path = (task.original_pdf_path or "") if task else ""
        digest = ""
        if pdf_path and Path(pdf_path).is_file():
            digest = hashlib.sha256(Path(pdf_path).read_bytes()).hexdigest()
        return {
            "claim_token": job.claim_token,
            "task_id": job.task_id,
            "paper_id": job.paper_id,
            "job_id": job.id,
            "lease_expires_at": job.claimed_until.isoformat() + "Z" if job.claimed_until else None,
            "original_pdf_sha256": digest,
        }

    def _job_by_token(self, session: Session, claim_token: str) -> KnowledgeWorkerJob:
        job = session.exec(select(KnowledgeWorkerJob).where(KnowledgeWorkerJob.claim_token == claim_token)).first()
        if not job or job.status != "claimed":
            raise HTTPException(404, "任务不存在或租约已失效")
        if job.claimed_until and job.claimed_until < datetime.utcnow():
            raise HTTPException(409, "租约已过期，请重新领取任务")
        return job

    def extend_lease(self, claim_token: str) -> None:
        lease = max(120, int(self.config.knowledge_worker.lease_seconds))
        with Session(self.engine) as session:
            job = self._job_by_token(session, claim_token)
            job.claimed_until = datetime.utcnow() + timedelta(seconds=lease)
            job.updated_at = datetime.utcnow()
            session.add(job)
            session.commit()

    def build_package(self, claim_token: str) -> bytes:
        with Session(self.engine) as session:
            job = self._job_by_token(session, claim_token)
            task = session.get(Task, job.task_id)
            if not task or not task.original_pdf_path:
                raise HTTPException(404, "原始 PDF 不存在")
            pdf_path = Path(task.original_pdf_path)
            if not pdf_path.is_file():
                raise HTTPException(404, "原始 PDF 文件已过期")
            digest = hashlib.sha256(pdf_path.read_bytes()).hexdigest()
        buffer = BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(
                "manifest.json",
                json.dumps(
                    {
                        "task_id": job.task_id,
                        "paper_id": job.paper_id,
                        "user_id": job.user_id,
                        "original_pdf_sha256": digest,
                    },
                    ensure_ascii=False,
                ),
            )
            archive.write(pdf_path, "original.pdf")
        return buffer.getvalue()

    def report_progress(self, claim_token: str, done: int, total: int) -> None:
        done = max(0, int(done))
        total = max(0, int(total))
        with Session(self.engine) as session:
            job = self._job_by_token(session, claim_token)
            job.progress_done = done
            job.progress_total = total
            job.updated_at = datetime.utcnow()
            session.add(job)
            session.commit()

    def complete(self, claim_token: str, knowledge: dict) -> None:
        if not isinstance(knowledge, dict):
            raise HTTPException(422, "knowledge 必须是对象")
        encoded = json.dumps(knowledge, ensure_ascii=False, separators=(",", ":"))
        if len(encoded.encode()) > MAX_KNOWLEDGE_BYTES:
            raise HTTPException(413, "知识数据过大")
        digest = hashlib.sha256(encoded.encode()).hexdigest()
        with Session(self.engine) as session:
            job = self._job_by_token(session, claim_token)
            paper_id = job.paper_id
            user_id = job.user_id
            task_id = job.task_id
        self.extractor.apply_knowledge(paper_id, user_id, knowledge, db_engine=self.engine)
        with Session(self.engine) as session:
            job = self._job_by_token(session, claim_token)
            job.status = "completed"
            job.error = ""
            job.progress_done = job.progress_total or job.progress_done
            job.claim_token = None
            job.claimed_until = None
            job.updated_at = datetime.utcnow()
            session.add(job)
            session.commit()
        logger.info(
            "Knowledge worker completed paper=%s task=%s sha256=%s",
            paper_id,
            task_id,
            digest[:12],
        )

    def fail(self, claim_token: str, message: str) -> None:
        detail = (message or "本机知识整理失败").strip()[:500]
        with Session(self.engine) as session:
            job = self._job_by_token(session, claim_token)
            paper = session.get(PaperKnowledge, job.paper_id)
            if paper:
                paper.extraction_status = "error"
                paper.extraction_error = detail
                paper.updated_at = datetime.utcnow()
                session.add(paper)
            job.status = "failed"
            job.error = detail
            job.claim_token = None
            job.claimed_until = None
            job.updated_at = datetime.utcnow()
            session.add(job)
            session.commit()

    def recover_after_restart(self) -> None:
        now = datetime.utcnow()
        with Session(self.engine) as session:
            for job in session.exec(select(KnowledgeWorkerJob).where(KnowledgeWorkerJob.status == "claimed")).all():
                job.status = "queued"
                job.claim_token = None
                job.claimed_until = None
                job.updated_at = now
                session.add(job)
            session.commit()
