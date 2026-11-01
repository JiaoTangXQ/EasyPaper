"""Queue, lease, and finalize gloss work executed on a trusted local worker."""

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
from ..models.gloss_worker import GlossWorkerJob
from ..models.reading import ReaderBuild, ReaderGloss, ReaderVersion
from ..models.task import TaskStatus
from ..services.task_manager import TaskManager

logger = logging.getLogger(__name__)

MAX_SPANS_BYTES = 64 * 1024 * 1024


class GlossWorkerService:
    def __init__(self, config: AppConfig, engine, task_manager: TaskManager, synced_reader):
        self.config = config
        self.engine = engine
        self.task_manager = task_manager
        self.reader = synced_reader

    def job_id(self, document_id: str) -> str:
        return f"{document_id}:gloss"

    def enqueue(self, *, task_id: str, document_id: str, user_id: int) -> GlossWorkerJob:
        jid = self.job_id(document_id)
        now = datetime.utcnow()
        with Session(self.engine) as session:
            build = session.get(ReaderBuild, jid)
            if build and build.status == "running":
                raise HTTPException(409, "点读正在服务器上准备，请稍后再试。")
            if build and build.status == "claimed":
                raise HTTPException(409, "点读已被本地点读处理器领取，请稍后再试。")
            if not build:
                build = ReaderBuild(id=jid, document_id=document_id, kind="gloss")
            build.status = "awaiting_worker"
            build.error = ""
            build.updated_at = now
            session.add(build)
            job = session.get(GlossWorkerJob, jid)
            if not job:
                job = GlossWorkerJob(
                    id=jid,
                    task_id=task_id,
                    document_id=document_id,
                    user_id=user_id,
                )
            job.status = "queued"
            job.claim_token = None
            job.claimed_until = None
            job.worker_label = None
            job.progress_done = 0
            job.progress_total = 0
            job.error = ""
            job.updated_at = now
            session.add(job)
            session.commit()
            session.refresh(job)
            return job

    def release_expired_claims(self) -> int:
        now = datetime.utcnow()
        released = 0
        with Session(self.engine) as session:
            jobs = session.exec(
                select(GlossWorkerJob).where(
                    GlossWorkerJob.status == "claimed",
                    GlossWorkerJob.claimed_until.isnot(None),
                    GlossWorkerJob.claimed_until < now,
                )
            ).all()
            for job in jobs:
                job.status = "queued"
                job.claim_token = None
                job.claimed_until = None
                job.worker_label = None
                job.updated_at = now
                session.add(job)
                build = session.get(ReaderBuild, job.id)
                if build and build.status == "claimed":
                    build.status = "awaiting_worker"
                    build.updated_at = now
                    session.add(build)
                released += 1
            if released:
                session.commit()
        return released

    def claim_next(self, *, worker_label: str) -> dict[str, Any] | None:
        self.release_expired_claims()
        lease = max(60, int(self.config.gloss_worker.lease_seconds))
        token = secrets.token_urlsafe(32)
        until = datetime.utcnow() + timedelta(seconds=lease)
        with Session(self.engine) as session:
            query = (
                select(GlossWorkerJob)
                .where(GlossWorkerJob.status == "queued")
                .order_by(GlossWorkerJob.created_at)
            )
            if self.engine.dialect.name == "postgresql":
                job = session.exec(query.with_for_update(skip_locked=True)).first()
            else:
                job = session.exec(query).first()
            if not job:
                return None
            build = session.get(ReaderBuild, job.id)
            if not build or build.status not in {"awaiting_worker", "error"}:
                job.status = "failed"
                job.error = "阅读器状态不一致，请用户在网页上重试。"
                job.updated_at = datetime.utcnow()
                session.add(job)
                session.commit()
                return None
            job.status = "claimed"
            job.claim_token = token
            job.claimed_until = until
            job.worker_label = (worker_label or "worker")[:120]
            job.updated_at = datetime.utcnow()
            build.status = "claimed"
            build.error = ""
            build.updated_at = job.updated_at
            session.add(job)
            session.add(build)
            session.commit()
            task = self.task_manager.get_task(job.task_id)
            if task:
                self.task_manager.update_progress(
                    job.task_id,
                    TaskStatus.REWRITING,
                    15,
                    "本地点读处理器已领取任务…",
                )
            return self._job_payload(session, job)

    def _job_payload(self, session: Session, job: GlossWorkerJob) -> dict[str, Any]:
        source = session.exec(
            select(ReaderVersion).where(
                ReaderVersion.document_id == job.document_id,
                ReaderVersion.kind == "original",
            )
        ).first()
        if not source:
            raise HTTPException(500, "原文版本缺失")
        gloss = session.get(ReaderGloss, job.document_id)
        spans: list = []
        if gloss and gloss.spans_json:
            try:
                parsed = json.loads(gloss.spans_json)
                spans = parsed if isinstance(parsed, list) else []
            except json.JSONDecodeError:
                spans = []
        return {
            "claim_token": job.claim_token,
            "task_id": job.task_id,
            "document_id": job.document_id,
            "job_id": job.id,
            "lease_expires_at": job.claimed_until.isoformat() + "Z" if job.claimed_until else None,
            "original_pdf_sha256": source.fingerprint,
            "index_units": len(json.loads(source.index_json).get("units") or []),
            "resume_span_count": len(spans),
        }

    def _job_by_token(self, session: Session, claim_token: str) -> GlossWorkerJob:
        job = session.exec(select(GlossWorkerJob).where(GlossWorkerJob.claim_token == claim_token)).first()
        if not job or job.status != "claimed":
            raise HTTPException(404, "任务不存在或租约已失效")
        if job.claimed_until and job.claimed_until < datetime.utcnow():
            raise HTTPException(409, "租约已过期，请重新领取任务")
        return job

    def extend_lease(self, claim_token: str) -> None:
        lease = max(60, int(self.config.gloss_worker.lease_seconds))
        with Session(self.engine) as session:
            job = self._job_by_token(session, claim_token)
            job.claimed_until = datetime.utcnow() + timedelta(seconds=lease)
            job.updated_at = datetime.utcnow()
            session.add(job)
            session.commit()

    def build_package(self, claim_token: str) -> bytes:
        with Session(self.engine) as session:
            job = self._job_by_token(session, claim_token)
            source = session.exec(
                select(ReaderVersion).where(
                    ReaderVersion.document_id == job.document_id,
                    ReaderVersion.kind == "original",
                )
            ).first()
            if not source or not Path(source.path).is_file():
                raise HTTPException(404, "原文 PDF 不存在")
            gloss = session.get(ReaderGloss, job.document_id)
            spans_json = gloss.spans_json if gloss and gloss.spans_json else "[]"
        buffer = BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(
                "manifest.json",
                json.dumps(
                    {
                        "task_id": job.task_id,
                        "document_id": job.document_id,
                        "original_pdf_sha256": source.fingerprint,
                    },
                    ensure_ascii=False,
                ),
            )
            archive.write(source.path, "original.pdf")
            archive.writestr("index.json", source.index_json)
            archive.writestr("resume_spans.json", spans_json)
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
        if total > 0:
            percent = 20 + int(75 * done / total)
            self.task_manager.update_progress(
                job.task_id,
                TaskStatus.REWRITING,
                min(percent, 95),
                f"本地点读准备中（{done}/{total}）",
            )

    def complete(self, claim_token: str, spans: list) -> None:
        if not isinstance(spans, list):
            raise HTTPException(422, "spans 必须是数组")
        encoded = json.dumps(spans, ensure_ascii=False, separators=(",", ":"))
        if len(encoded.encode()) > MAX_SPANS_BYTES:
            raise HTTPException(413, "点读数据过大")
        digest = hashlib.sha256(encoded.encode()).hexdigest()
        with Session(self.engine) as session:
            job = self._job_by_token(session, claim_token)
            document_id = job.document_id
            row = session.get(ReaderGloss, document_id)
            if not row:
                row = ReaderGloss(document_id=document_id, spans_json="[]")
            row.spans_json = encoded
            row.updated_at = datetime.utcnow()
            session.add(row)
            build = session.get(ReaderBuild, job.id)
            if build:
                build.status = "completed"
                build.error = ""
                build.updated_at = row.updated_at
                session.add(build)
            job.status = "completed"
            job.error = ""
            job.progress_done = job.progress_total or job.progress_done
            job.claim_token = None
            job.claimed_until = None
            job.updated_at = row.updated_at
            session.add(job)
            task_id = job.task_id
            session.commit()
        self.task_manager.update_progress(task_id, TaskStatus.COMPLETED, 100, "原文点读已准备好")
        logger.info(
            "Gloss worker completed document=%s task=%s spans=%d sha256=%s",
            document_id,
            task_id,
            len(spans),
            digest[:12],
        )

    def fail(self, claim_token: str, message: str) -> None:
        detail = (message or "本地点读准备失败").strip()[:500]
        with Session(self.engine) as session:
            job = self._job_by_token(session, claim_token)
            job.status = "failed"
            job.error = detail
            job.claim_token = None
            job.claimed_until = None
            job.updated_at = datetime.utcnow()
            build = session.get(ReaderBuild, job.id)
            if build:
                build.status = "error"
                build.error = detail
                build.updated_at = job.updated_at
                session.add(build)
            session.add(job)
            session.commit()
            task_id = job.task_id
        self.task_manager.set_error(task_id, detail)

    def recover_after_restart(self) -> None:
        now = datetime.utcnow()
        with Session(self.engine) as session:
            for build in session.exec(select(ReaderBuild).where(ReaderBuild.status == "running")).all():
                if build.kind != "gloss":
                    continue
                build.status = "error"
                build.error = "生成因服务重启中断，可重试；已有版本和批注仍保留"
                build.updated_at = now
                session.add(build)
            for build in session.exec(select(ReaderBuild).where(ReaderBuild.status == "claimed")).all():
                build.status = "awaiting_worker"
                build.updated_at = now
                session.add(build)
            for job in session.exec(select(GlossWorkerJob).where(GlossWorkerJob.status == "claimed")).all():
                job.status = "queued"
                job.claim_token = None
                job.claimed_until = None
                job.updated_at = now
                session.add(job)
            session.commit()
