"""Authenticated APIs for archived PDF versions and shared annotations."""

from __future__ import annotations

import json
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response, StreamingResponse
from pydantic import BaseModel, Field
from sqlmodel import Session

from ..models.task import Task
from ..models.user import User
from ..services.reader_backup import MAX_ARCHIVE_BYTES, restore_archive
from ..services.reader_geometry import public_units
from ..services.synced_reader import SyncedReader
from .deps import get_current_user


class AnnotationWrite(BaseModel):
    operation_id: str = Field(min_length=1, max_length=100, pattern=r"^[a-zA-Z0-9_-]+$")
    base_revision: int = Field(ge=0)
    version_id: str = Field(max_length=200)
    data: dict[str, Any]
    deleted: bool = False
    geometry_changed: bool = True


class AnnotationLink(BaseModel):
    version_id: str = Field(max_length=200)
    base_revision: int = Field(ge=1)
    data: dict[str, Any]


def create_reader_router(reading):
    router = APIRouter(prefix="/api/reader", tags=["reader-annotations"])
    service = SyncedReader(reading)
    reading.synced_reader = service

    def resume_alignment(bundle, background, opening=False):
        current_versions = {}
        for version in bundle["versions"]:
            current_versions.setdefault(version["kind"], version)
        recovery_busy = bool(service._scheduled) or any(
            not a["deleted"] and a["alignment_status"] == "pending" for a in bundle["annotations"]
        )
        for a in sorted(bundle["annotations"], key=lambda a: a["alignment_status"] != "pending"):
            elapsed = (datetime.utcnow() - datetime.fromisoformat(a["updated_at"])).total_seconds()
            new_version = any(
                v["id"] != a["source_version_id"]
                and v["id"] not in a["projections"]
                and v["created_at"] > a["updated_at"]
                for v in bundle["versions"]
            )
            if a["alignment_status"] == "partial" and not new_version:
                unresolved = [
                    fragment
                    for parts in a["projections"].values()
                    for part in parts
                    for fragment in part.get("unmatched_fragments", [])
                ]
                all_versions_present = all(
                    v["id"] == a["source_version_id"] or a["projections"].get(v["id"])
                    for v in current_versions.values()
                )
                # Clipped letters have no extra meaning for another model run
                # to discover. Keep the partial state and explicit retry option.
                if (
                    all_versions_present
                    and unresolved
                    and all(len(fragment) == 1 and fragment.isascii() and fragment.isalpha() for fragment in unresolved)
                ):
                    continue
                if recovery_busy:
                    continue
            if (
                not a["deleted"]
                and a["id"] not in service._scheduled
                and (
                    new_version
                    or a["alignment_status"] == "pending"
                    and (opening or elapsed > 60)
                    or a["alignment_status"] == "partial"
                    and elapsed > (60 if opening else 300)
                )
            ):
                service.schedule_alignment(background, a["id"])
                recovery_busy = True

    @router.get("/tasks/{task_id}")
    async def open_reader(task_id: str, background: BackgroundTasks, user: User = Depends(get_current_user)):
        with Session(reading.engine) as session:
            task = session.get(Task, task_id)
            if not task or task.user_id != user.id:
                raise HTTPException(404, "论文不存在或无权访问")
        bundle = await service.open_task(task, user.id)
        resume_alignment(bundle, background, opening=True)
        return bundle

    @router.get("/documents/{document_id}")
    async def document(document_id: str, background: BackgroundTasks, user: User = Depends(get_current_user)):
        bundle = service.bundle(document_id, user.id)
        resume_alignment(bundle, background)
        return bundle

    @router.get("/documents/{document_id}/versions/{version_id}/pdf")
    async def pdf(document_id: str, version_id: str, user: User = Depends(get_current_user)):
        service.owned(document_id, user.id)
        version = service.version(document_id, version_id)
        if not Path(version.path).is_file():
            raise HTTPException(404, "存档文件缺失；批注仍保留，请从备份恢复文件")
        return FileResponse(
            version.path,
            media_type="application/pdf",
            filename=f"{version.kind}.pdf",
            headers={"Cache-Control": "private, max-age=31536000, immutable"},
        )

    @router.get("/documents/{document_id}/versions/{version_id}/text")
    async def text_index(document_id: str, version_id: str, user: User = Depends(get_current_user)):
        service.owned(document_id, user.id)
        version = service.version(document_id, version_id)
        return {"units": public_units(json.loads(version.index_json))}

    @router.post("/documents/{document_id}/versions/{kind}", status_code=202)
    async def generate(
        document_id: str,
        kind: Literal["chinese", "simple", "bilingual"],
        background: BackgroundTasks,
        user: User = Depends(get_current_user),
    ):
        service.owned(document_id, user.id)
        if service.request_build(document_id, kind):
            background.add_task(service.build, document_id, kind)
        return {"status": "running"}

    @router.put("/documents/{document_id}/annotations/{annotation_id}")
    async def write(
        document_id: str,
        annotation_id: str,
        body: AnnotationWrite,
        background: BackgroundTasks,
        user: User = Depends(get_current_user),
    ):
        if len(annotation_id) > 100 or not annotation_id.replace("-", "").replace("_", "").isalnum():
            raise HTTPException(422, "批注标识无效")
        result = await service.mutate(document_id, user.id, annotation_id, body)
        if not body.deleted and (body.geometry_changed or result["alignment_status"] == "pending"):
            service.schedule_alignment(background, annotation_id)
        return result

    @router.post("/documents/{document_id}/annotations/{annotation_id}/align", status_code=202)
    async def retry(
        document_id: str, annotation_id: str, background: BackgroundTasks, user: User = Depends(get_current_user)
    ):
        bundle = service.bundle(document_id, user.id)
        if not any(a["id"] == annotation_id for a in bundle["annotations"]):
            raise HTTPException(404, "批注不存在")
        service.schedule_alignment(background, annotation_id, force=True)
        return {"status": "pending"}

    @router.put("/documents/{document_id}/annotations/{annotation_id}/link")
    async def link(
        document_id: str,
        annotation_id: str,
        body: AnnotationLink,
        background: BackgroundTasks,
        user: User = Depends(get_current_user),
    ):
        result = await service.link(document_id, user.id, annotation_id, body)
        service.schedule_alignment(background, annotation_id)
        return result

    @router.get("/documents/{document_id}/annotations/export")
    async def export(document_id: str, user: User = Depends(get_current_user)):
        return Response(
            json.dumps(service.bundle(document_id, user.id), ensure_ascii=False, indent=2),
            media_type="application/json",
            headers={"Content-Disposition": 'attachment; filename="paper-annotations.json"'},
        )

    @router.get("/documents/{document_id}/archive")
    async def archive(document_id: str, user: User = Depends(get_current_user)):
        bundle = service.bundle(document_id, user.id)
        stream = tempfile.TemporaryFile()
        try:
            with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive_file:
                archive_file.writestr("annotations.json", json.dumps(bundle, ensure_ascii=False, indent=2))
                for version in service.versions(document_id):
                    archive_file.write(version.path, f"{version.kind}-{version.fingerprint}.pdf")
                    archive_file.writestr(f"{version.kind}-{version.fingerprint}.index.json", version.index_json)
                    archive_file.writestr(f"{version.kind}-{version.fingerprint}.mappings.json", version.mappings_json)
            stream.seek(0)
        except Exception:
            stream.close()
            raise

        def chunks():
            try:
                while chunk := stream.read(256 * 1024):
                    yield chunk
            finally:
                stream.close()

        return StreamingResponse(
            chunks(),
            media_type="application/zip",
            headers={"Content-Disposition": 'attachment; filename="paper-with-annotations.zip"'},
        )

    @router.post("/documents/{document_id}/restore")
    async def restore(document_id: str, file: UploadFile, user: User = Depends(get_current_user)):
        import asyncio

        service.owned(document_id, user.id)
        try:
            file.file.seek(0, 2)
            if file.file.tell() > MAX_ARCHIVE_BYTES:
                raise HTTPException(413, "备份文件不能超过 128 MB")
            file.file.seek(0)
            async with service._locks[f"write:{document_id}"]:
                return await asyncio.to_thread(restore_archive, service, document_id, user.id, file.file)
        finally:
            await file.close()

    return router
