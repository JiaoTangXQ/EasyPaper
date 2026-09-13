"""Bounded, durable retries for annotations without relying on an open browser."""

from __future__ import annotations

import asyncio
import hashlib
import logging
from datetime import datetime, timedelta

from fastapi import BackgroundTasks
from sqlmodel import Session, select

from ..models.reading import ReaderAlignmentRetry, ReaderAnnotation, ReaderDocument, ReaderVersion

logger = logging.getLogger(__name__)
RETRY_DELAYS = (15, 60, 300)


class ReaderRecovery:
    def __init__(self, service):
        self.service = service

    def signature(self, row, versions=None):
        current = {}
        if versions is None:
            with Session(self.service.engine) as session:
                versions = session.exec(
                    select(ReaderVersion.id, ReaderVersion.kind)
                    .where(ReaderVersion.document_id == row.document_id)
                    .order_by(ReaderVersion.created_at.desc())
                ).all()
        for v in versions:
            current.setdefault(v.kind, v.id)
        return hashlib.sha256(repr((row.geometry_revision, sorted(current.items()))).encode()).hexdigest()

    def recorded(self, row):
        signature = self.signature(row)
        with Session(self.service.engine) as session:
            record = session.get(ReaderAlignmentRetry, row.id)
            return record if record and record.signature == signature else None

    def finished(self, started, *, force=False):
        with Session(self.service.engine) as session:
            row = session.get(ReaderAnnotation, started.id)
            if not row or row.geometry_revision != started.geometry_revision:
                return
            previous = session.get(ReaderAlignmentRetry, row.id)
            if row.deleted or row.alignment_status == "matched":
                if previous:
                    session.delete(previous)
                session.commit()
                return
            if row.alignment_status != "partial":
                return
            signature = self.signature(row)
            attempts = previous.attempts if previous and previous.signature == signature and not force else 0
            due = (
                datetime.utcnow() + timedelta(seconds=RETRY_DELAYS[attempts]) if attempts < len(RETRY_DELAYS) else None
            )
            record = previous or ReaderAlignmentRetry(annotation_id=row.id, signature=signature)
            record.signature, record.attempts, record.next_attempt_at = signature, attempts + 1, due
            session.add(record)
            session.commit()

    def schedule_due(self, bundle, background, *, opening=False):
        current = {}
        for version in bundle["versions"]:
            current.setdefault(version["kind"], version)
        active = [a for a in bundle["annotations"] if not a["deleted"]]
        # Work in another document cannot prevent this document's recovery.
        busy = any(a["id"] in self.service._scheduled or a["alignment_status"] == "pending" for a in active)
        with Session(self.service.engine) as session:
            attempts = {
                a["id"]: session.get(ReaderAlignmentRetry, a["id"])
                for a in active
                if a["alignment_status"] == "partial"
            }
            for a in sorted(
                active,
                key=lambda a: (
                    a["alignment_status"] != "pending",
                    attempts[a["id"]].attempts if attempts.get(a["id"]) else 0,
                    a["updated_at"],
                ),
            ):
                if a["id"] in self.service._scheduled:
                    continue
                elapsed = (datetime.utcnow() - datetime.fromisoformat(a["updated_at"])).total_seconds()
                new_version = any(
                    v["id"] != a["source_version_id"]
                    and not a["projections"].get(v["id"])
                    and v["created_at"] > a["updated_at"]
                    for v in current.values()
                )
                due = False
                if a["alignment_status"] == "partial" and not busy:
                    row = session.get(ReaderAnnotation, a["id"])
                    record = self.recorded(row)
                    due = (
                        record.next_attempt_at is not None and record.next_attempt_at <= datetime.utcnow()
                        if record
                        else True
                    )
                if new_version or (a["alignment_status"] == "pending" and (opening or elapsed > 60)) or due:
                    self.service.schedule_alignment(background, a["id"])
                    busy = True

    async def run_once(self):
        with Session(self.service.engine) as session:
            docs = session.exec(
                select(ReaderDocument).where(
                    ReaderDocument.id.in_(
                        select(ReaderAnnotation.document_id).where(
                            ReaderAnnotation.deleted == False,  # noqa: E712
                            ReaderAnnotation.alignment_status.in_(["partial", "pending"]),
                        )
                    )
                )
            ).all()
        background = BackgroundTasks()
        for doc in docs:
            self.schedule_due(self.service.bundle(doc.id, doc.user_id), background)
        await background()

    async def run(self):
        while True:
            try:
                await self.run_once()
            except Exception:
                logger.exception("Annotation recovery failed; retrying on next tick")
            await asyncio.sleep(5)
